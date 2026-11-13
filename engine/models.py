"""Shared JSON-compatible types."""

from typing import Any, Literal, NotRequired, TypedDict

Config = dict[str, Any]
FactValue = str | int | bool | list[str] | None


class Fact(TypedDict):
    value: FactValue
    label: Literal["CONFIRMED", "UNKNOWN", "CONFIRMED (by PM)"]
    evidence: str


class Seed(TypedDict):
    id: str
    linked_icm_id: str
    linked_case_id: str
    reported_at: str
    reporter_team: str
    channel: str
    root_cause_category: str
    raw_description: str
    known_fields: NotRequired[dict[str, FactValue]]


class Severity(TypedDict):
    severity: str
    rationale: list[str]
    closure_suggested: bool


class Purview(TypedDict):
    status: str
    rationale: list[str]
    receiving_team: str | None


class Routing(TypedDict):
    lane: str
    rationale: list[str]


class Stakeholder(TypedDict):
    name: str
    reason: str


class Decision(TypedDict):
    value: str | list[str]
    disposition: Literal["Accepted", "Overridden"]
    reason: str


class Draft(TypedDict):
    text: str
    status: str
    approved_at: str | None


class AuditEvent(TypedDict):
    timestamp: str
    actor: str
    action: str
    before: Any
    after: Any


class Incident(Seed):
    facts: dict[str, Fact]
    purview: Purview
    severity: Severity
    routing: Routing
    stakeholders: list[Stakeholder]
    decisions: dict[str, Decision]
    questions_asked: dict[str, bool]
    status: str
    events: dict[str, str]
    drafts: dict[str, Draft]
    audit: list[AuditEvent]
    revision: int


class Clock(TypedDict):
    id: str
    label: str
    start: str | None
    deadline: str | None
    remaining_hours: float | None
    status: str
    completed_at: str | None
    met: bool | None
    rationale: str
