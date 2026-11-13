"""JSON persistence and auditable PM workflow transitions."""

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path

from engine.audit import append_event
from engine.clocks import calculate_clocks, parse_time
from engine.drafts import suggest_draft, validate_status_text
from engine.extract import suggest_extract, validate_fact
from engine.models import Config, Decision, FactValue, Incident, Seed
from engine.plan import plan_rationale
from engine.purview import handoff_team, suggest_purview
from engine.routing import suggest_routing, suggest_stakeholders
from engine.severity import suggest_severity


def effective_severity(incident: Incident) -> str:
    """Use a PM severity decision when present, otherwise the provisional value."""
    decision = incident["decisions"].get("severity")
    return str(decision["value"]) if decision else incident["severity"]["severity"]


def effective_lane(incident: Incident) -> str:
    """Use the PM lane decision when present, otherwise show the suggestion."""
    decision = incident["decisions"].get("routing")
    return str(decision["value"]) if decision else incident["routing"]["lane"]


def effective_purview(incident: Incident) -> str:
    """Keep the PM purview decision distinct from the evidence-based suggestion."""
    decision = incident["decisions"].get("purview")
    return str(decision["value"]) if decision else incident["purview"]["status"]


def _record(incident: Incident, config: Config, action: str, before: object, after: object) -> None:
    append_event(incident, config["demo_now"], "PM", action, before, after)
    incident["revision"] += 1


def _invalidate_drafts(incident: Incident, config: Config, kinds: tuple[str, ...] = ("deletion", "status", "handoff")) -> None:
    for kind, draft in incident["drafts"].items():
        if kind in kinds and draft["status"] != "Needs regeneration":
            before = deepcopy(draft)
            draft.update(status="Needs regeneration", approved_at=None)
            append_event(
                incident, config["demo_now"], "System suggestion",
                f"{kind} draft invalidated by changed incident context", before, draft,
            )


def refresh_suggestions(incident: Incident, config: Config) -> None:
    """Recompute suggestions after facts change and explicitly revoke stale decisions."""
    before = deepcopy(incident["decisions"])
    incident["decisions"] = {}
    if before:
        append_event(
            incident, config["demo_now"], "System suggestion",
            "Prior decisions invalidated by changed facts", before, {},
        )
    previous_purview = deepcopy(incident["purview"])
    incident["purview"] = suggest_purview(incident["raw_description"], incident["facts"], config)
    append_event(
        incident, config["demo_now"], "System suggestion",
        "purview suggestion", previous_purview, incident["purview"],
    )
    suggestions = {
        "severity": suggest_severity(incident["raw_description"], incident["facts"], config),
        "stakeholders": suggest_stakeholders(incident["raw_description"], incident["facts"], config),
    }
    for key in ("severity", "stakeholders"):
        previous = deepcopy(incident.get(key))
        incident[key] = suggestions[key]
        append_event(
            incident, config["demo_now"], "System suggestion",
            f"{key} suggestion", previous, suggestions[key],
        )
    _refresh_routing(incident, config)
    _invalidate_drafts(incident, config)


def _refresh_routing(incident: Incident, config: Config) -> None:
    previous = deepcopy(incident.get("routing"))
    purview = effective_purview(incident)
    if purview == config["purview"]["out_of_scope_label"] and incident["purview"]["status"] != purview:
        purview = config["purview"]["review_label"]
    incident["routing"] = suggest_routing(
        incident["raw_description"], incident["facts"], effective_severity(incident), config, purview
    )
    prior_decision = incident["decisions"].pop("routing", None)
    if prior_decision:
        append_event(
            incident, config["demo_now"], "System suggestion",
            "Routing decision invalidated", prior_decision, None,
        )
    append_event(
        incident, config["demo_now"], "System suggestion", "routing suggestion",
        previous, incident["routing"],
    )


def initialize_incident(seed: Seed, config: Config) -> Incident:
    """Create one incident without silently accepting any recommendation."""
    parse_time(seed["reported_at"])
    if parse_time(seed["reported_at"]) > parse_time(config["demo_now"]):
        raise ValueError(f"{seed['id']} was reported after demo_now.")
    incident: Incident = {
        **deepcopy(seed), "facts": suggest_extract(seed, config),
        "purview": {"status": "", "rationale": [], "receiving_team": None},
        "severity": {"severity": "", "rationale": [], "closure_suggested": False},
        "routing": {"lane": "", "rationale": []}, "stakeholders": [],
        "decisions": {}, "questions_asked": {}, "status": config["workflow"]["initial_status"],
        "events": {}, "drafts": {}, "audit": [], "revision": 0,
    }
    append_event(
        incident, config["demo_now"], "System suggestion", "extraction", None, incident["facts"]
    )
    refresh_suggestions(incident, config)
    return incident


def record_question(incident: Incident, key: str, asked: bool, config: Config) -> None:
    """Persist the reporter-question checklist without confirming an answer."""
    if key not in config["facts"]:
        raise ValueError("Unknown reporter question.")
    before = incident["questions_asked"].get(key, False)
    incident["questions_asked"][key] = asked
    _record(incident, config, f"reporter question checklist: {key}", before, asked)


def edit_fact(
    incident: Incident, key: str, value: FactValue, note: str, config: Config
) -> None:
    """Confirm a fact by PM with a required source note and invalidate stale output."""
    validate_fact(key, value, config)
    if not note.strip():
        raise ValueError("A source or confirmation note is required.")
    before = deepcopy(incident["facts"][key])
    incident["facts"][key] = {
        "value": value, "label": "CONFIRMED (by PM)",
        "evidence": plan_rationale(config, "fact_edit", note.strip()),
    }
    if key == "deletion_attested" and value is True:
        incident["events"].setdefault("deletion_attested_at", config["demo_now"])
    elif key == "deletion_attested":
        incident["events"].pop("deletion_attested_at", None)
    _record(incident, config, f"fact edit: {key}", before, incident["facts"][key])
    refresh_suggestions(incident, config)


def record_decision(
    incident: Incident, kind: str, value: str | list[str], override: bool,
    reason: str, config: Config,
) -> None:
    """Accept an exact suggestion or override it with an explicit reason."""
    if kind == "purview":
        suggested: str | list[str] = incident["purview"]["status"]
        allowed = [config["purview"][key] for key in ("in_scope_label", "out_of_scope_label", "review_label")]
    elif kind == "receiving_team":
        suggested = handoff_team(incident["purview"], {}, config)
        if effective_purview(incident) != config["purview"]["out_of_scope_label"]:
            raise ValueError("Receiving-team selection requires out-of-scope purview.")
        allowed = list(config["purview"]["receiving_teams"].values())
    elif kind == "severity":
        suggested = incident["severity"]["severity"]
        allowed = config["severity"]["levels"]
    elif kind == "routing":
        suggested = incident["routing"]["lane"]
        allowed = [config["routing"]["fte_lane"], config["routing"]["routine_lane"]]
        if incident["routing"]["lane"] == config["routing"]["handoff_lane"]:
            allowed.append(config["routing"]["handoff_lane"])
    elif kind == "stakeholders":
        suggested = [item["name"] for item in incident["stakeholders"]]
        allowed = [item["name"] for item in config["stakeholders"]]
    elif kind == "closure" and incident["severity"]["closure_suggested"]:
        suggested = config["severity"]["closure_label"]
        allowed = [suggested, "Keep open"]
    else:
        raise ValueError("Unknown or unavailable suggestion.")
    values = value if isinstance(value, list) else [value]
    if any(item not in allowed for item in values):
        raise ValueError("Decision contains an unconfigured value.")
    if kind == "stakeholders":
        if not isinstance(value, list):
            raise ValueError("Stakeholders must be a list.")
    elif not isinstance(value, str):
        raise ValueError("This decision must be a single value.")
    if not override and value != suggested:
        raise ValueError("Accept must match the current suggestion.")
    if override and not reason.strip():
        raise ValueError("An override requires a reason.")
    before = deepcopy(incident["decisions"].get(kind))
    decision: Decision = {
        "value": deepcopy(value),
        "disposition": "Overridden" if override else "Accepted",
        "reason": reason.strip() if override else "PM accepted the displayed suggestion and rationale.",
    }
    incident["decisions"][kind] = decision
    _record(incident, config, f"{kind} {'override' if override else 'acceptance'}", before, decision)
    if kind == "purview":
        prior_team = incident["decisions"].pop("receiving_team", None)
        if prior_team:
            append_event(
                incident, config["demo_now"], "System suggestion",
                "Receiving-team decision invalidated", prior_team, None,
            )
    if kind in ("severity", "purview"):
        _refresh_routing(incident, config)
    _invalidate_drafts(incident, config)


def change_status(incident: Incident, status: str, config: Config) -> None:
    """Record a human workflow change; facts are never inferred from status."""
    if status not in config["statuses"]:
        raise ValueError("Unknown workflow status.")
    if status == incident["status"]:
        raise ValueError("Choose a different status.")
    deletion_context = (
        suggest_draft("deletion", incident, config)
        if "deletion" in incident["drafts"] else None
    )
    before = {"status": incident["status"], "events": deepcopy(incident["events"])}
    incident["status"] = status
    for event in config["workflow"]["status_events"].get(status, []):
        incident["events"].setdefault(event, config["demo_now"])
    _record(
        incident, config, "status change", before,
        {"status": status, "events": incident["events"]},
    )
    affected = ("status", "handoff")
    if deletion_context is not None and deletion_context != suggest_draft("deletion", incident, config):
        affected += ("deletion",)
    _invalidate_drafts(incident, config, kinds=affected)


def record_completion(incident: Incident, event: str, config: Config) -> None:
    """Record a PM-attested manual action, not an automated communication."""
    allowed = {
        rule["completed_by"] for rule in config["clocks"]["rules"]
        if rule.get("manual_completion")
    }
    if event not in allowed:
        raise ValueError("Unsupported manual completion event.")
    rule = next(rule for rule in config["clocks"]["rules"] if rule["completed_by"] == event)
    clock = next(clock for clock in calculate_clocks(incident, config) if clock["id"] == rule["id"])
    if clock["start"] is None:
        raise ValueError("This clock has not started yet or is not applicable.")
    if rule["start"] != "reported_at" and rule["start"] not in incident["events"]:
        raise ValueError("This clock has not started yet.")
    if event in incident["events"]:
        raise ValueError("This manual action has already been recorded.")
    incident["events"][event] = config["demo_now"]
    _record(incident, config, f"manual action: {event}", None, config["demo_now"])
    _invalidate_drafts(incident, config)


def generate_draft(incident: Incident, kind: str, config: Config) -> None:
    """Create or explicitly replace a draft, always clearing prior approval."""
    text = suggest_draft(kind, incident, config)
    before = deepcopy(incident["drafts"].get(kind))
    incident["drafts"][kind] = {"text": text, "status": "Draft", "approved_at": None}
    _record(incident, config, f"{kind} draft generated", before, incident["drafts"][kind])


def save_draft(
    incident: Incident, kind: str, text: str, approve: bool, config: Config
) -> None:
    """Save edits and optionally approve for manual delivery; never deliver anything."""
    if kind not in incident["drafts"]:
        raise ValueError("Generate the draft before editing or approving it.")
    if incident["drafts"][kind]["status"] == "Needs regeneration":
        raise ValueError("Incident context changed. Regenerate this draft before approval.")
    if not text.strip():
        raise ValueError("A draft cannot be empty.")
    if kind in ("status", "handoff"):
        validate_status_text(text, config)
    if kind == "handoff":
        handoff_team(incident["purview"], incident["decisions"], config)
        if approve and not all(key in incident["decisions"] for key in ("purview", "receiving_team")):
            raise ValueError("Approve the out-of-scope purview and receiving-team decisions before approving the handoff.")
    before = deepcopy(incident["drafts"][kind])
    incident["drafts"][kind] = {
        "text": text,
        "status": config["drafts"]["approved_label"] if approve else "Draft",
        "approved_at": config["demo_now"] if approve else None,
    }
    if approve and kind == "deletion":
        if "deletion_request_approved_at" not in incident["events"]:
            incident["events"]["deletion_request_approved_at"] = config["demo_now"]
            _invalidate_drafts(incident, config, kinds=("status",))
    _record(
        incident, config, f"{kind} draft {'approval' if approve else 'edit'}",
        before, incident["drafts"][kind],
    )


def load_state(seed_path: Path, state_path: Path, config: Config) -> list[Incident]:
    """Restore state or initialize the synthetic seed; corrupt files fail visibly."""
    if state_path.exists():
        with state_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError("Saved state must be a JSON object.")
        if payload["schema_version"] != 1:
            raise ValueError("Unsupported state schema. Preserve the file before resetting.")
        if payload["config"] != config:
            raise ValueError("Configuration changed. Reset demo data to apply the new rules.")
        incidents = payload["incidents"]
        if not isinstance(incidents, list) or not incidents:
            raise ValueError("Saved state must contain a non-empty incident list.")
        for incident in incidents:
            for key in (
                "id", "linked_icm_id", "linked_case_id", "reported_at", "reporter_team",
                "channel", "root_cause_category", "raw_description", "status", "facts",
                "purview", "severity", "routing", "stakeholders", "decisions", "questions_asked",
                "events", "drafts", "audit", "revision",
            ):
                if key not in incident:
                    raise ValueError(f"Saved incident is missing {key}; preserve the file before resetting.")
            if incident["status"] not in config["statuses"]:
                raise ValueError("Saved incident has an unconfigured status.")
            parse_time(incident["reported_at"])
            for timestamp in incident["events"].values():
                parse_time(timestamp)
            if set(incident["facts"]) != set(config["facts"]):
                raise ValueError("Saved incident fact fields do not match configuration.")
            for key, fact in incident["facts"].items():
                if fact["label"] not in ("UNKNOWN", "CONFIRMED", "CONFIRMED (by PM)"):
                    raise ValueError("Saved fact has an invalid evidence label.")
                if fact["label"] != "UNKNOWN":
                    validate_fact(key, fact["value"], config)
        return incidents
    return load_seed(seed_path, config)


def load_seed(seed_path: Path, config: Config) -> list[Incident]:
    """Create clean demo state without reading or deleting saved state."""
    with seed_path.open(encoding="utf-8") as handle:
        seeds = json.load(handle)
    if not isinstance(seeds, list) or not seeds:
        raise ValueError("Seed data must be a non-empty list.")
    ids = [seed["id"] for seed in seeds]
    if len(set(ids)) != len(ids):
        raise ValueError("Seed incident IDs must be unique.")
    return [initialize_incident(seed, config) for seed in seeds]


def persist_state(incidents: list[Incident], path: Path, config: Config) -> None:
    """Atomically replace JSON; retain the old state if writing fails."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix="state.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = handle.name
            json.dump(
                {"schema_version": 1, "config": config, "incidents": incidents},
                handle, ensure_ascii=False, indent=2,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and Path(temporary).exists():
            Path(temporary).unlink()
