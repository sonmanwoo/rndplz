from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Contribution:
    person_id: str | None
    name: str
    role: str
    corresponding: bool = False
    institutions: list[dict] = field(default_factory=list)
    individual_performance_verified: bool = False


@dataclass
class Person:
    id: str
    name: str
    kind: str = "researcher"
    org: str = "소속 미확인"
    org_type: str = "unknown"
    profile: dict[str, Any] = field(default_factory=dict)
    confirmed: bool = False
    virtual: bool = False


@dataclass
class Record:
    id: str
    kind: str
    title: str
    text: str
    date: str
    people: list[Contribution]
    tags: list[str]
    field: str
    scope: str
    source_system: str
    source_id: str
    source_url: str
    checked_at: str
    evidence_kind: str = "unknown"
    classification_basis: list[str] = field(default_factory=list)
    access_policy_ref: str = "public_metadata"
    virtual: bool = False
    details: dict[str, Any] = field(default_factory=dict)


def plain(value):
    return asdict(value)
