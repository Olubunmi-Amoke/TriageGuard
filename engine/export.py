"""Copy-ready output for manual use in an external case system."""

from engine.clocks import calculate_clocks
from engine.drafts import fact_text
from engine.models import Config, Incident
from engine.plan import plan_rationale


def export_summary(incident: Incident, config: Config) -> str:
    """Include labeled suggestions, decisions, clocks, and approved drafts only."""
    lines = [
        "TRIAGEGUARD SYNTHETIC CASE SUMMARY",
        config["banner"],
        f"Snapshot time: {config['demo_now']}",
        f"Response plan: {config['response_plan']['path']} ({config['response_plan']['version']}) — {config['clock_policy_label']}",
        plan_rationale(config, "export", "Manual copy/download only; no platform write or closure."),
        f"Incident: {incident['id']}",
        f"Linked IcM: {incident['linked_icm_id'] or 'Not linked'}",
        f"Linked case: {incident['linked_case_id'] or 'Not linked'}",
        f"Reported: {incident['reported_at']}",
        f"Status (PM workflow): {incident['status']}",
        "", "FACT SHEET",
    ]
    for key, fact in incident["facts"].items():
        value = "UNKNOWN" if fact["label"] == "UNKNOWN" else fact_text(fact["value"])
        lines.append(f"{config['facts'][key]}: {value} [{fact['label']}] | Evidence: {fact['evidence']}")
    lines.extend(["", "PRIVACY PURVIEW (SUGGESTION UNTIL ACCEPTED)", incident["purview"]["status"]])
    lines.extend(incident["purview"]["rationale"])
    lines.append(f"Suggested receiving team: {incident['purview']['receiving_team'] or 'None; purview not excluded'}")
    lines.extend(["", "SEVERITY / ROUTING (SUGGESTIONS UNTIL ACCEPTED)"])
    lines.append(f"Provisional severity: {incident['severity']['severity']}")
    lines.extend(f"- {reason}" for reason in incident["severity"]["rationale"])
    if incident["severity"]["closure_suggested"]:
        lines.append(f"PM review suggestion: {config['severity']['closure_label']}")
    lines.append(f"Suggested lane: {incident['routing']['lane']}")
    lines.extend(f"- {reason}" for reason in incident["routing"]["rationale"])
    lines.extend(["", "SUGGESTED STAKEHOLDERS"])
    lines.extend(f"- {item['name']}: {item['reason']}" for item in incident["stakeholders"])
    lines.extend(["", "PM DECISIONS"])
    for name in ("purview", "receiving_team", "severity", "routing", "stakeholders", "closure"):
        decision = incident["decisions"].get(name)
        if decision:
            lines.append(
                f"{name}: {fact_text(decision['value'])} [{decision['disposition']}]"
                f" | Reason: {decision['reason']}"
            )
        else:
            lines.append(f"{name}: Pending PM review")
    lines.extend(["", f"CLOCKS ({config['clock_policy_label']})"])
    for clock in calculate_clocks(incident, config):
        lines.append(
            f"- {clock['label']}: {clock['deadline'] or 'Not started'} | {clock['status']}"
            f" | completed: {clock['completed_at'] or 'No'} | met: {clock['met']}"
            f" | {clock['rationale']}"
        )
    lines.extend(["", "APPROVED DRAFTS — MANUAL DELIVERY ONLY"])
    approved = [
        (kind, draft) for kind, draft in incident["drafts"].items()
        if draft["status"] == config["drafts"]["approved_label"] and draft["approved_at"]
    ]
    if not approved:
        lines.append("None approved.")
    for kind, draft in approved:
        lines.extend([f"{kind} | approved: {draft['approved_at']}", draft["text"]])
    lines.extend(["", f"AUDIT SUMMARY ({len(incident['audit'])} actions)"])
    for event in incident["audit"]:
        lines.append(
            f"{event['timestamp']} | {event['actor']} | {event['action']}"
        )
    return "\n".join(lines)
