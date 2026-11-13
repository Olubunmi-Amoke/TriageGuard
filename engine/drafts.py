"""Offline templates only: approval is a record, not a delivery mechanism."""

import re

from engine.clocks import calculate_clocks
from engine.models import Config, Incident
from engine.purview import handoff_team


def fact_text(value: object) -> str:
    """Format confirmed values without treating False or zero as missing."""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def validate_status_text(text: str, config: Config) -> None:
    """Reject speculation/legal wording in facts-only status and handoff drafts."""
    for pattern in config["drafts"]["status_blocked_patterns"]:
        if re.search(pattern, text, re.IGNORECASE):
            raise ValueError(
                "Communication draft contains speculative or legal-assessment wording. "
                "Use explicit factual statements only; accountable owners decide legal matters."
            )


def suggest_draft(kind: str, incident: Incident, config: Config) -> str:
    """Build drafts solely from confirmed fields and recorded workflow events."""
    if kind not in ("deletion", "status", "handoff"):
        raise ValueError("Unknown draft type.")
    receiving_team = handoff_team(incident["purview"], incident["decisions"], config) if kind == "handoff" else ""
    confirmed_lines: list[str] = []
    unknowns: list[str] = []
    for key, fact in incident["facts"].items():
        label = config["facts"][key]
        if fact["label"] == "UNKNOWN":
            unknowns.append(f"- {label}: UNKNOWN")
        else:
            confirmed_lines.append(f"- {label}: {fact_text(fact['value'])} [{fact['label']}]")
    update = next(
        (clock["deadline"] for clock in calculate_clocks(incident, config) if clock["id"] == "stakeholder_update"),
        None,
    )
    actions = [f"- Recorded workflow status: {incident['status']}."]
    actions.extend(f"- {key}: {value}" for key, value in incident["events"].items())
    text = config["drafts"][kind]["template"].format(
        incident_id=incident["id"],
        confirmed="\n".join(confirmed_lines) or "- No facts confirmed.",
        unknowns="\n".join(unknowns) or "- None currently recorded.",
        actions="\n".join(actions),
        next_update=f"{update or 'Not configured; PM to set manually.'} ({config['clock_policy_label']})",
        purview_reasons="\n".join(f"- {reason}" for reason in incident["purview"]["rationale"]),
        receiving_team=receiving_team,
    )
    if kind in ("status", "handoff"):
        validate_status_text(text, config)
    return text
