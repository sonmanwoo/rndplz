"""Narrow adapter for the existing, pinned USD 30 owner ledger gate.

MAIN must provision the external gate, reconciled ledger and exact request
proof. This module never creates a ledger, confirms a baseline, refreshes a
proof or settles charges. Even a successful response retains its full reserve
until the owner separately reconciles final billing. No provider/network code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import re
from types import ModuleType
from typing import Mapping
from uuid import uuid4

from .responses_stream import LLMError


PINNED_GATE_SHA256 = "680bb15e9bc36d1efbf382a834fdd72197c0c23d7cb4aeb314808baa2c6c9be1"
_SETTINGS = (
    "OPENAI_BUDGET_GATE_FILE", "OPENAI_BUDGET_GATE_SHA256",
    "OPENAI_BUDGET_LEDGER", "OPENAI_BUDGET_PROOF_FILE",
    "OPENAI_BUDGET_PROOF_SHA256",
)
_MAX_GATE_BYTES = 128 * 1024
_MAX_PROOF_BYTES = 65536


def _fail(code: str = "budget_unverified") -> None:
    raise LLMError(code, provider="openai_api") from None


def _hash_value(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _pinned_bytes(path: Path, expected: str, limit: int) -> bytes:
    with path.open("rb") as source:
        raw = source.read(limit + 1)
    if len(raw) > limit or sha256(raw).hexdigest() != expected:
        _fail()
    return raw


def _load_gate(path: Path, expected: str) -> ModuleType:
    if expected != PINNED_GATE_SHA256:
        _fail()
    raw = _pinned_bytes(path, expected, _MAX_GATE_BYTES)
    module = ModuleType("_rndplz_verified_owner_budget_gate")
    module.__file__ = str(path)
    # Execute the verified bytes, not a second file read by an import loader.
    exec(compile(raw, "<verified-owner-budget-gate>", "exec"), module.__dict__)
    if any(not callable(getattr(module, name, None))
           for name in ("reserve", "begin_dispatch", "mark_uncertain", "evidence")):
        _fail()
    return module


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


@dataclass(frozen=True, repr=False)
class _Reservation:
    owner: object = field(repr=False)
    reservation_id: str = field(repr=False)


class OwnerBudgetGuard:
    """Three-method guard; all failures expose only fixed LLMError codes."""

    def __init__(self, gate: ModuleType, ledger: Path, proof: Path, proof_sha: str):
        self._gate = gate
        self._ledger = ledger
        self._proof = proof
        self._proof_sha = proof_sha
        self._owner = object()

    def reserve_request(self, body: bytes, model: str, endpoint: str,
                        output_cap: int) -> object:
        """Reserve only against an owner-verified proof for these exact bytes."""
        try:
            if (type(body) is not bytes or not body
                    or not isinstance(model, str) or not model
                    or not isinstance(endpoint, str) or not endpoint
                    or type(output_cap) is not int or output_cap <= 0):
                _fail()
            raw = _pinned_bytes(self._proof, self._proof_sha, _MAX_PROOF_BYTES)
            proof = json.loads(raw, object_pairs_hook=_unique_object)
            if not isinstance(proof, dict) or proof.get("verified") is not True:
                _fail()
            bound = proof.get("input_token_upper_bound")
            if type(bound) is not int or not 0 <= bound <= 1_000_000_000:
                _fail()
            result = self._gate.reserve(
                self._ledger,
                operation_id="rndplz-responses-" + uuid4().hex,
                request_sha256=sha256(body).hexdigest(),
                model=model, endpoint=endpoint,
                input_token_upper_bound=bound, output_token_cap=output_cap,
                proof_path=self._proof, proof_sha=self._proof_sha,
            )
            reservation_id = result["reservation_id"]
            if not isinstance(reservation_id, str) or not reservation_id:
                _fail()
            return _Reservation(self._owner, reservation_id)
        except LLMError:
            raise
        except Exception:
            _fail()

    def _reservation_id(self, reservation: object) -> str:
        if not isinstance(reservation, _Reservation) or reservation.owner is not self._owner:
            _fail()
        return reservation.reservation_id

    def begin_dispatch(self, reservation: object, body: bytes) -> None:
        """Must run immediately before one HTTP attempt; retries need a reserve."""
        try:
            if type(body) is not bytes:
                _fail()
            self._gate.begin_dispatch(
                self._ledger, self._reservation_id(reservation), sha256(body).hexdigest(),
            )
        except LLMError:
            raise
        except Exception:
            _fail()

    def finish_uncertain(self, reservation: object) -> None:
        """Retain maximum cost on success, failure, timeout or cancellation."""
        try:
            self._gate.mark_uncertain(self._ledger, self._reservation_id(reservation))
        except LLMError:
            raise
        except Exception:
            _fail()


def guard_from_env(env: Mapping[str, str]) -> OwnerBudgetGuard | None:
    """Load explicitly configured proof/gate; return None if wholly unconfigured.

The caller must reject a missing guard with ``budget_not_configured`` before
any paid request. Incomplete config is an immediate error. Deployment packaging
of the pinned gate and owner evidence is MAIN's responsibility.
"""
    try:
        values = [env.get(name) for name in _SETTINGS]
        if all(value is None or value == "" for value in values):
            return None
        if any(not isinstance(value, str) or not value.strip() for value in values):
            _fail("budget_not_configured")
        gate_file, gate_sha, ledger_file, proof_file, proof_sha = values
        if not _hash_value(gate_sha) or not _hash_value(proof_sha):
            _fail()
        gate_path, ledger_path, proof_path = map(Path, (gate_file, ledger_file, proof_file))
        if not all(path.is_absolute() for path in (gate_path, ledger_path, proof_path)):
            _fail()
        gate = _load_gate(gate_path, gate_sha)
        return OwnerBudgetGuard(gate, ledger_path, proof_path, proof_sha)
    except LLMError:
        raise
    except Exception:
        _fail()
