"""Explicit local/hosted-demo OAuth / deployed Responses / test routing.

No SDK, inference CLI, retries, refresh implementation or provider fallback.
This module is server-only. OAuth is a Codex backend integration, not a promise
of compatibility with the public OpenAI API.
"""
from __future__ import annotations

import base64
import copy
from dataclasses import dataclass, field
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import threading
import time
import urllib.error
import urllib.request

from .responses_stream import LLMError, StreamEvent, iter_response_events

CODEX_ENDPOINT = "https://chatgpt.com/backend-api/codex/responses"
OPENAI_ENDPOINT = "https://api.openai.com/v1/responses"
MOCK_TEXT = "[MOCK] 실제 모델을 호출하지 않은 테스트 응답입니다."
OAUTH_RUNTIMES = frozenset({"local", "hosted_demo"})
OAUTH_AUTH_ERRORS = frozenset({"auth_missing", "auth_invalid", "auth_expired", "oauth_unauthorized"})
NONRETRYABLE_RUNTIME_ERRORS = frozenset({
    "auth_missing", "auth_invalid", "auth_expired", "oauth_unauthorized",
    "model_access_denied", "local_only", "mock_fixture_required", "process_call_cap",
    "invalid_input", "redirect_blocked", "unexpected_tool_call",
})


def runtime_error_retryable(exc):
    """Manual product retry eligibility, never an automatic network retry."""
    code = getattr(exc, "code", "")
    return not isinstance(exc, RuntimeConfigError) and code not in NONRETRYABLE_RUNTIME_ERRORS and not code.startswith("budget_")


class RuntimeConfigError(ValueError):
    """Configuration messages never interpolate environment values."""


class RuntimeFailure(LLMError):
    def __init__(self, code, *, provider=None, http_status=None, runtime=None):
        super().__init__(code, provider=provider, http_status=http_status)
        if code in OAUTH_AUTH_ERRORS:
            if runtime == "hosted_demo":
                self.args = ("서버 OAuth 인증을 사용할 수 없습니다. 소유자가 전용 로그인 명령을 다시 실행하고 서버 인증 secret을 갱신해야 합니다.",)
            else:
                self.args = ("로컬 인증을 사용할 수 없습니다. 로컬 로그인 명령을 다시 실행하세요.",)
        elif code == "model_access_denied":
            self.args = ("선택한 계정 또는 모델의 접근 권한을 확인해 주세요. 다른 인증 경로로 전환하지 않았습니다.",)
        elif code == "rate_limited":
            self.args = ("모델 사용량 제한에 도달했습니다. 잠시 후 다시 시도해 주세요.",)
        elif code == "timeout":
            self.args = ("모델 응답 대기 시간을 초과했습니다.",)
        elif code.startswith("budget_"):
            self.args = ("배포 API의 비용 확인 또는 요청 예약이 준비되지 않아 호출하지 않았습니다.",)
        elif code == "local_only":
            self.args = ("로컬 AI 연결은 이 기기의 개발 서버에서만 사용할 수 있습니다.",)
        elif code == "mock_fixture_required":
            self.args = ("이 구조화 출력 테스트에는 명시적인 mock 응답 fixture가 필요합니다.",)


def _fail(code, provider=None, status=None, *, runtime=None):
    raise RuntimeFailure(code, provider=provider, http_status=status, runtime=runtime) from None


def _inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("nonfinite_json")


def _safe_string(value, name):
    if (not isinstance(value, str) or not value or value != value.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or len(value) > 2048 or any(s in value.lower() for s in ("<", ">", "placeholder", "replace_me", "your_model"))):
        raise RuntimeConfigError(name + " 설정이 없거나 올바르지 않습니다.")
    return value


@dataclass(frozen=True)
class RuntimeConfig:
    runtime: str
    provider: str
    model: str
    auth_file: Path | None = field(default=None, repr=False)
    api_key: str = field(default="", repr=False)
    max_calls: int = 20

    @classmethod
    def from_env(cls, env=None, *, repo_root=None):
        env = os.environ if env is None else env
        runtime, provider = env.get("APP_RUNTIME"), env.get("LLM_PROVIDER")
        if runtime not in {"local", "hosted_demo", "deployed", "test"}:
            raise RuntimeConfigError("APP_RUNTIME은 local, hosted_demo, deployed, test 중 하나로 명시해야 합니다.")
        expected = {"local": "codex_oauth", "hosted_demo": "codex_oauth", "deployed": "openai_api", "test": "mock"}[runtime]
        if provider != expected:
            raise RuntimeConfigError("APP_RUNTIME과 LLM_PROVIDER 조합이 올바르지 않습니다. test는 mock을 사용합니다.")
        if runtime == "test":
            return cls(runtime, provider, "mock")
        if runtime == "deployed":
            # Deliberately do not read CODEX_AUTH_FILE or any OAuth credential.
            return cls(runtime, provider, _safe_string(env.get("OPENAI_MODEL"), "OPENAI_MODEL"),
                       api_key=_safe_string(env.get("OPENAI_API_KEY"), "OPENAI_API_KEY"))
        max_calls = 20
        if runtime == "hosted_demo":
            raw_limit = env.get("RNDPLZ_DEMO_MAX_CALLS", "20")
            if (not isinstance(raw_limit, str) or not re.fullmatch(r"[0-9]{1,3}", raw_limit)
                    or not 1 <= int(raw_limit) <= 200):
                raise RuntimeConfigError("RNDPLZ_DEMO_MAX_CALLS는 1부터 200까지의 정수여야 합니다.")
            max_calls = int(raw_limit)
        model = _safe_string(env.get("CODEX_MODEL"), "CODEX_MODEL")
        raw_path = _safe_string(env.get("CODEX_AUTH_FILE"), "CODEX_AUTH_FILE")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            if runtime == "hosted_demo":
                raise RuntimeConfigError("CODEX_AUTH_FILE은 저장소 밖 전용 인증 파일의 절대 경로여야 합니다.")
            raise RuntimeConfigError("CODEX_AUTH_FILE은 저장소 밖 전용 auth.json의 절대 경로여야 합니다.")
        root = Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[1]
        resolved = path.resolve()
        global_file = (Path.home() / ".codex" / "auth.json").resolve()
        allowed_names = {"auth.json", "codex-auth.json"} if runtime == "hosted_demo" else {"auth.json"}
        if (_inside(resolved, root) or resolved == global_file or resolved.name not in allowed_names
                or any(p.is_symlink() or bool(getattr(p, "is_junction", lambda: False)()) for p in (path, *path.parents))):
            if runtime == "hosted_demo":
                raise RuntimeConfigError("CODEX_AUTH_FILE은 기존 Codex 인증과 분리된 저장소 밖 전용 auth.json 또는 codex-auth.json이어야 합니다.")
            raise RuntimeConfigError("CODEX_AUTH_FILE은 기존 Codex 인증과 분리된 저장소 밖 전용 auth.json이어야 합니다.")
        # Deliberately never inspect OPENAI_API_KEY for either OAuth runtime.
        return cls(runtime, provider, model, auth_file=resolved, max_calls=max_calls)

    def diagnostics(self):
        present = self.auth_file.is_file() if self.runtime in OAUTH_RUNTIMES else bool(self.api_key) if self.runtime == "deployed" else False
        return {"runtime": self.runtime, "provider": self.provider, "model": self.model,
                "auth_configured": present}


def read_codex_auth(path):
    """Read each request; consume access_token/account_id only, never refresh."""
    try:
        path = Path(path)
        if any(p.is_symlink() or bool(getattr(p, "is_junction", lambda: False)()) for p in (path, *path.parents)):
            _fail("auth_invalid", "codex_oauth")
        with path.open("rb") as stream:
            raw = stream.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024:
            _fail("auth_invalid", "codex_oauth")
        document = json.loads(raw)
        if not isinstance(document, dict) or document.get("auth_mode") != "chatgpt":
            _fail("auth_invalid", "codex_oauth")
        tokens = document.get("tokens")
        if not isinstance(tokens, dict):
            _fail("auth_invalid", "codex_oauth")
        token, account = tokens.get("access_token"), tokens.get("account_id")
        for value in (token, account):
            if (not isinstance(value, str) or not value or len(value) > 20000
                    or any(ord(c) < 33 or ord(c) > 126 for c in value)):
                _fail("auth_invalid", "codex_oauth")
        # This decode only detects expiry; it does not establish authorization.
        if token.count(".") == 2:
            part = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
            exp = claims.get("exp") if isinstance(claims, dict) else None
            if type(exp) not in (int, float) or exp <= time.time():
                _fail("auth_expired", "codex_oauth")
        return {"Authorization": "Bearer " + token, "ChatGPT-Account-ID": account}
    except FileNotFoundError:
        _fail("auth_missing", "codex_oauth")
    except LLMError:
        raise
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        _fail("auth_invalid", "codex_oauth")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _fail("redirect_blocked")


def _check(deadline, cancelled, provider=None):
    try:
        stopped = cancelled() if cancelled else False
    except Exception:
        _fail("cancellation_check_failed", provider)
    if stopped:
        _fail("cancelled", provider)
    if time.monotonic() >= deadline:
        _fail("timeout", provider)


def _http_chunks(endpoint, headers, body, *, deadline, cancelled):
    """One POST, no retries or redirects, close on EOF/error/generator cancel."""
    _check(deadline, cancelled)
    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    with urllib.request.build_opener(_NoRedirect()).open(request, timeout=max(0.001, deadline-time.monotonic())) as response:
        # Official Codex accepts a successful HTTP byte stream without a MIME
        # gate (including its unit fixture with no Content-Type). The bounded
        # semantic SSE parser still requires response.completed; raw JSON or
        # HTML cannot become a successful generation merely through HTTP 200.
        while True:
            _check(deadline, cancelled)
            # urllib's socket timeout otherwise stays at its initial value.
            raw = getattr(getattr(response, "fp", None), "raw", None)
            sock = getattr(raw, "_sock", None)
            if sock is not None:
                sock.settimeout(max(0.001, deadline-time.monotonic()))
            chunk = response.read1(8192)
            _check(deadline, cancelled)
            if not chunk:
                break
            yield chunk


def _safe_transport(transport, endpoint, headers, body, *, deadline, cancelled, provider):
    chunks = None
    try:
        chunks = transport(endpoint, headers, body, deadline=deadline, cancelled=cancelled)
        yield from chunks
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        code = "oauth_unauthorized" if status == 401 and provider == "codex_oauth" else "model_access_denied" if status in {401, 403, 404} else "rate_limited" if status == 429 else "provider_http_error"
        _fail(code, provider, status)
    except (TimeoutError, socket.timeout):
        _fail("timeout", provider)
    except urllib.error.URLError as exc:
        _fail("timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "transport_error", provider)
    except LLMError:
        raise
    except Exception:
        _fail("transport_error", provider)
    finally:
        if chunks is not None and callable(getattr(chunks, "close", None)):
            try:
                chunks.close()
            except Exception:
                pass


class ResponsesRuntime:
    def __init__(self, config, *, transport=None, auth_loader=None, budget_guard=None,
                 mock_responses=None):
        self.config = config
        self._transport = transport or _http_chunks
        self._auth_loader = auth_loader or read_codex_auth
        self._budget = budget_guard
        self._mock_responses = dict(mock_responses or {})

    def stream(self, messages, *, instructions, output_schema=None, output_cap=1800,
               contract_name="chat", deadline=None, cancelled=None, request_observer=None):
        config = self.config
        deadline = time.monotonic() + 60 if deadline is None else deadline
        _check(deadline, cancelled, config.provider)
        if (not isinstance(messages, list) or not messages or not isinstance(instructions, str)
                or any(not isinstance(m, dict) or m.get("role") not in {"user", "assistant"}
                       or not isinstance(m.get("content"), str) for m in messages)
                or len(instructions) + sum(len(m["content"]) for m in messages) > 42000
                or type(output_cap) is not int or not 1 <= output_cap <= 8192
                or (output_schema is not None and not isinstance(output_schema, dict))):
            _fail("invalid_input", config.provider)
        if config.runtime == "test":
            text = self._mock_responses.get(contract_name)
            if text is None and output_schema is not None:
                _fail("mock_fixture_required", config.provider)
            yield StreamEvent("text", text=MOCK_TEXT if text is None else text)
            yield StreamEvent("completed", model="mock", usage={})
            return

        # Responses requires a root object for strict JSON schema. Preserve
        # existing union contracts inside one result field and unwrap only
        # after semantic completion; the existing server validator still runs.
        wrapped = output_schema is not None and output_schema.get("type") != "object"
        schema = copy.deepcopy(output_schema)
        if wrapped:
            schema = {"type": "object", "properties": {"result": schema},
                      "required": ["result"], "additionalProperties": False}
            instructions += '\nReturn a JSON object with exactly one field, "result", containing the complete output described above.'
        payload = {"model": config.model, "instructions": instructions,
                   "input": [{"type": "message", "role": m["role"],
                              "content": [{"type": "input_text" if m["role"] == "user" else "output_text", "text": m["content"]}]} for m in messages],
                   "tools": [], "tool_choice": "auto", "parallel_tool_calls": False,
                   "store": False, "stream": True}
        if schema is not None:
            name = re.sub(r"[^A-Za-z0-9_-]", "_", contract_name)[:64] or "response"
            payload["text"] = {"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}}
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream", "User-Agent": "rndplz-local/1"}
        if config.runtime in OAUTH_RUNTIMES:
            endpoint = CODEX_ENDPOINT
            if config.runtime == "hosted_demo":
                headers["User-Agent"] = "rndplz-hosted-demo/1"
            try:
                headers.update(self._auth_loader(config.auth_file))
            except LLMError as exc:
                if config.runtime == "hosted_demo" and exc.code in OAUTH_AUTH_ERRORS:
                    _fail(exc.code, config.provider, exc.http_status, runtime=config.runtime)
                raise
            except Exception:
                _fail("auth_invalid", config.provider, runtime=config.runtime)
        else:
            endpoint = OPENAI_ENDPOINT
            headers["User-Agent"] = "rndplz-deployed/1"
            headers["Authorization"] = "Bearer " + config.api_key
            payload["max_output_tokens"] = output_cap
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        reservation = None
        if config.runtime == "deployed":
            if self._budget is None:
                _fail("budget_not_configured", config.provider)
            try:
                reservation = self._budget.reserve_request(body, config.model, endpoint, output_cap)
            except LLMError:
                raise
            except Exception:
                _fail("budget_unverified", config.provider)
        chunks = None
        text_parts = []
        completed = None
        try:
            _check(deadline, cancelled, config.provider)
            if reservation is not None:
                try:
                    self._budget.begin_dispatch(reservation, body)
                except LLMError:
                    raise
                except Exception:
                    _fail("budget_unverified", config.provider)
            if callable(request_observer):
                try:
                    request_observer(config.provider, copy.deepcopy(payload))
                except Exception:
                    pass
            chunks = _safe_transport(self._transport, endpoint, headers, body,
                                     deadline=deadline, cancelled=cancelled, provider=config.provider)
            for event in iter_response_events(chunks, provider=config.provider, cancelled=cancelled, final_only=schema is not None):
                _check(deadline, cancelled, config.provider)
                if event.kind == "completed":
                    completed = event
                elif schema is not None:
                    text_parts.append(event.text)
                else:
                    yield event
            if completed is None:
                _fail("incomplete_response", config.provider)
            if schema is not None:
                try:
                    value = json.loads("".join(text_parts), object_pairs_hook=_strict_object,
                                       parse_constant=_reject_constant)
                    if wrapped:
                        if not isinstance(value, dict) or set(value) != {"result"}:
                            _fail("invalid_structured_output", config.provider)
                        value = value["result"]
                    yield StreamEvent("text", text=json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
                except (ValueError, TypeError, RecursionError):
                    _fail("invalid_structured_output", config.provider)
            yield completed
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            code = "oauth_unauthorized" if status == 401 and config.runtime in OAUTH_RUNTIMES else "model_access_denied" if status in {401, 403, 404} else "rate_limited" if status == 429 else "provider_http_error"
            _fail(code, config.provider, status, runtime=config.runtime)
        except (TimeoutError, socket.timeout):
            _fail("timeout", config.provider)
        except LLMError as exc:
            if config.runtime == "hosted_demo" and exc.code in OAUTH_AUTH_ERRORS:
                _fail(exc.code, config.provider, exc.http_status, runtime=config.runtime)
            raise
        except Exception:
            _fail("transport_error", config.provider)
        finally:
            if chunks is not None and callable(getattr(chunks, "close", None)):
                chunks.close()
            if reservation is not None:
                # Keep the maximum reservation on success as well as every
                # uncertain failure. Usage counters are not final billing proof.
                try:
                    self._budget.finish_uncertain(reservation)
                except Exception:
                    pass  # Gate still holds RESERVED / IN_FLIGHT amount.


def build_runtime(env=None, *, repo_root=None, **kwargs):
    env = os.environ if env is None else env
    config = RuntimeConfig.from_env(env, repo_root=repo_root)
    if config.runtime == "deployed" and "budget_guard" not in kwargs:
        from .llm_budget import guard_from_env
        kwargs["budget_guard"] = guard_from_env(env)
    return ResponsesRuntime(config, **kwargs)


def enforce_local_request(config, remote_addr):
    """Check local OAuth peers; never infer runtime from forwarded addresses."""
    if config.runtime != "local":
        return
    try:
        allowed = ipaddress.ip_address(remote_addr).is_loopback
    except (TypeError, ValueError):
        allowed = False
    if not allowed:
        _fail("local_only", config.provider)


class RuntimeChatModels:
    """Existing catalog/get/stream surface with exactly one configured route."""
    def __init__(self, env=None, *, runtime=None, repo_root=None, **kwargs):
        self.runtime = runtime or build_runtime(env, repo_root=repo_root, **kwargs)
        self.lock = threading.Lock()
        self.calls = {}

    def catalog(self, refresh=False):
        config = self.runtime.config
        # Keep implementation/auth diagnostics out of the product selector.
        option = {"id": "runtime", "provider": config.provider, "model": config.model,
                  "name": config.model if config.runtime != "test" else "테스트 응답 (mock)",
                  "enabled": True, "local": False, "vision": False}
        return {"models": [option], "default": "runtime"}

    def get(self, identifier):
        if identifier != "runtime":
            raise ValueError("현재 연결된 모델을 선택해 주세요.")
        return self.catalog()["models"][0]

    def configure(self, payload):
        raise ValueError("모델 연결은 서버 환경 설정에서 관리합니다.")

    def has_call_capacity(self, identifier, *, provider, required_calls=1):
        if (identifier != "runtime" or provider != self.runtime.config.provider
                or type(required_calls) is not int or required_calls < 1):
            return False
        with self.lock:
            return self.runtime.config.runtime == "test" or self.calls.get(identifier, 0) + required_calls <= self.runtime.config.max_calls

    def stream(self, identifier, messages, *, contract=None):
        from .chat_models import CHAT_SYSTEM, validate_generation_input
        self.get(identifier)
        spec = validate_generation_input(messages, contract) if contract is not None else None
        with self.lock:
            if self.runtime.config.runtime != "test" and self.calls.get(identifier, 0) >= self.runtime.config.max_calls:
                # MAIN's current integration baseline owns this shared error.
                # Older ROOT snapshots do not yet contain the class.
                try:
                    from .chat_models import ModelProviderCapacity
                except ImportError:
                    _fail("process_call_cap", self.runtime.config.provider)
                raise ModelProviderCapacity()
            self.calls[identifier] = self.calls.get(identifier, 0) + 1
        pieces = []
        for event in self.runtime.stream(messages, instructions=spec["system"] if spec else CHAT_SYSTEM,
                                         output_schema=spec.get("format") if spec else None,
                                         output_cap=spec["max_tokens"] if spec else 1800,
                                         contract_name=contract or "chat",
                                         deadline=getattr(messages, "generation_deadline", None),
                                         request_observer=getattr(self, "diagnostic_observer", None)):
            if event.kind == "text":
                pieces.append(event.text)
                yield event.text
            else:
                observer = getattr(self, "diagnostic_response_observer", None)
                if callable(observer):
                    try:
                        observer(self.runtime.config.provider, {"model": event.model, "done": True,
                                 "done_reason": "stop", "message": {"content": "".join(pieces)}})
                    except Exception:
                        pass


from .models import ExternalModel, ModelUnavailable, SYSTEM


class RuntimeLegacyModel(ExternalModel):
    """Preserve structure/draft validation and safe audit through same route."""
    def __init__(self, runtime, *, audit_path=None):
        # Never let ExternalModel inspect the process environment or a key.
        super().__init__(env={}, audit_path=audit_path)
        self.runtime = runtime
        self.provider = runtime.config.provider
        self.model = runtime.config.model
        self.enabled = True

    def call(self, task, data, output_schema):
        user = json.dumps({"task": task, "data": data}, ensure_ascii=False)
        if len(user) > 40000:
            raise ModelUnavailable("input_limit")
        with self._lock:
            if self.calls >= self.limit:
                raise ModelUnavailable("budget")
            self.calls += 1
        try:
            parts = [event.text for event in self.runtime.stream(
                [{"role": "user", "content": user}], instructions=SYSTEM,
                output_schema=output_schema, output_cap=2200, contract_name="research_assistance") if event.kind == "text"]
            parsed = json.loads("".join(parts))
            if not isinstance(parsed, dict) or set(parsed) != set(output_schema["required"]):
                raise ModelUnavailable("schema")
            for key, description in output_schema["properties"].items():
                if not isinstance(parsed[key], str) or len(parsed[key]) > 2000:
                    raise ModelUnavailable("schema")
                if "enum" in description and parsed[key] not in description["enum"]:
                    raise ModelUnavailable("enum")
            return parsed
        except LLMError as exc:
            raise ModelUnavailable(exc.code) from None
        except (ValueError, TypeError, KeyError):
            raise ModelUnavailable("schema") from None

    def fallback(self, reason):
        result = super().fallback(reason)
        if reason in OAUTH_AUTH_ERRORS:
            result["message"] = str(RuntimeFailure(reason, provider=self.provider, runtime=self.runtime.config.runtime))
        return result
