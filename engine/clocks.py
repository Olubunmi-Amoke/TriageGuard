"""Deterministic, UTC clocks with weekend-skipping business-day arithmetic."""

from datetime import datetime, timedelta, timezone

from engine.models import Clock, Config, Incident
from engine.plan import plan_rationale
from engine.extract import keyword_matches


def parse_time(value: str) -> datetime:
    """Parse timezone-aware ISO timestamps and normalize them to UTC."""
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamps must include a timezone.")
    return result.astimezone(timezone.utc)


def iso_time(value: datetime) -> str:
    """Serialize a timezone-aware instant as UTC ISO text."""
    if value.tzinfo is None:
        raise ValueError("Timestamps must include a timezone.")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def add_business_days(start: datetime, days: int) -> datetime:
    """Advance whole weekdays, preserving UTC time; holidays are not modeled."""
    if not isinstance(days, int) or isinstance(days, bool) or days < 0:
        raise ValueError("Business days must be a non-negative integer.")
    remaining = days
    result = start
    while remaining:
        result += timedelta(days=1)
        if result.weekday() < 5:
            remaining -= 1
    return result


def calculate_clocks(incident: Incident, config: Config) -> list[Clock]:
    """Calculate active, completed, not-started, and closed-case clock states."""
    now = parse_time(config["demo_now"])
    result: list[Clock] = []
    for rule in config["clocks"]["rules"]:
        start = (
            incident["reported_at"] if rule["start"] == "reported_at"
            else incident["events"].get(rule["start"])
        )
        completed_at = incident["events"].get(rule["completed_by"])
        clock: Clock = {
            "id": rule["id"], "label": rule["label"], "start": start,
            "deadline": None, "remaining_hours": None, "status": "Not started",
            "completed_at": completed_at, "met": None,
            "rationale": plan_rationale(config, rule["plan_rule"], f"{rule['label']}: starts at {rule['start']}; {config['clock_policy_label']}."),
        }
        if rule.get("when_keyword") and not keyword_matches(incident["raw_description"], rule["when_keyword"], config):
            clock.update(start=None, completed_at=None, status="Not applicable (no assessment requested)")
            result.append(clock)
            continue
        if start is not None:
            beginning = parse_time(start)
            deadline = (
                add_business_days(beginning, rule["business_days"])
                if "business_days" in rule else beginning + timedelta(hours=rule["hours"])
            )
            clock["deadline"] = iso_time(deadline)
            remaining = (deadline - now).total_seconds() / 3600
            clock["remaining_hours"] = remaining
            if completed_at:
                clock["status"] = "Completed"
                clock["met"] = parse_time(completed_at) <= deadline
            elif incident["status"] == config["workflow"]["closed_status"]:
                clock["status"] = "Stopped (closed)"
            elif remaining <= 0:
                clock["status"] = "Breached"
            elif remaining / ((deadline - beginning).total_seconds() / 3600) < config["clocks"]["at_risk_fraction"]:
                clock["status"] = "At risk"
            else:
                clock["status"] = "OK"
        result.append(clock)
    return result


def next_clock(incident: Incident, config: Config) -> Clock | None:
    """Return the earliest outstanding clock, including overdue deadlines."""
    active = [
        clock for clock in calculate_clocks(incident, config)
        if clock["status"] in ("OK", "At risk", "Breached")
    ]
    return min(active, key=lambda clock: clock["deadline"] or "") if active else None
