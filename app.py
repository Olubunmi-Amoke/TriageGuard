"""TriageGuard: a single-operator, synthetic-data Streamlit prototype."""

from collections import Counter
from copy import deepcopy
from html import escape
from pathlib import Path
from typing import Callable

import pandas as pd
import streamlit as st
import yaml

from engine.audit import append_event, audit_csv
from engine.clocks import calculate_clocks, next_clock, parse_time
from engine.config import load_config
from engine.drafts import fact_text
from engine.export import export_summary
from engine.models import Config, FactValue, Incident
from engine.plan import plan_rationale, response_plan_path
from engine.queue import order_incidents
from engine.state import (
    change_status,
    edit_fact,
    effective_lane,
    effective_purview,
    effective_severity,
    generate_draft,
    load_seed,
    load_state,
    persist_state,
    record_completion,
    record_decision,
    record_question,
    save_draft,
)

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "data" / "state.json"
SEED_PATH = ROOT / "data" / "incidents.json"

st.set_page_config(page_title="TriageGuard | Synthetic prototype", page_icon="🛡️", layout="wide")

STATUS_PALETTE = {
    "green": ("#E5F4EA", "#14532D"),
    "amber": ("#FFF3CD", "#713F12"),
    "red": ("#FDE8E7", "#991B1B"),
    "blue": ("#E8F0FC", "#1E40AF"),
    "neutral": ("#F2F5FA", "#334155"),
}


def status_style(value: object, config: Config) -> str:
    """Share accessible status colors between badges and tables; always retain text."""
    tones = {
        "OK": "green", "Completed": "green", "CONFIRMED": "green", "CONFIRMED (by PM)": "green",
        "At risk": "amber", "UNKNOWN": "amber", "Breached": "red",
        "Out of scope": "blue",
        config["purview"]["in_scope_label"]: "green",
        config["purview"]["review_label"]: "amber",
        config["purview"]["out_of_scope_label"]: "blue",
    }
    background, foreground = STATUS_PALETTE[tones.get(str(value), "neutral")]
    return f"background-color: {background}; color: {foreground}; font-weight: 600"


def status_badge(value: str, config: Config) -> None:
    """Render a labeled status without interpreting its color as a safety judgment."""
    st.html(
        f'<span style="{status_style(value, config)}; display:inline-block; padding:0.3rem 0.6rem; '
        f'border-radius:0.4rem; overflow-wrap:anywhere">{escape(value)}</span>'
    )


def commit_change(incident_id: str, action: Callable[[Incident], None], config: Config) -> None:
    """Persist a complete action before replacing the UI's session state."""
    incidents = deepcopy(st.session_state["incidents"])
    incident = next(item for item in incidents if item["id"] == incident_id)
    try:
        action(incident)
        persist_state(incidents, STATE_PATH, config)
    except (OSError, ValueError) as error:
        st.error(f"Action not saved: {error}")
        return
    st.session_state["incidents"] = incidents
    st.session_state.pop("export_snapshot", None)
    st.rerun()


def reset_demo(config: Config) -> None:
    """Replace only the known local demo state after explicit user confirmation."""
    try:
        incidents = load_seed(SEED_PATH, config)
        persist_state(incidents, STATE_PATH, config)
    except (OSError, ValueError, KeyError, TypeError) as error:
        st.error(f"Reset failed: {error}")
        return
    st.session_state.clear()
    st.rerun()


def deadline_table(rows: list[dict[str, object]], config: Config) -> None:
    """Wrap table cells instead of placing evidence behind horizontal scrolling."""
    st.caption(f"Clock values: {config['clock_policy_label']}. All dates UTC.")
    if not rows:
        st.info("No outstanding deadlines in this view.")
        return
    frame = pd.DataFrame(rows)
    for column in ("Next due (UTC)", "Due (UTC)", "Completed"):
        if column in frame:
            frame[column] = frame[column].map(
                lambda value: parse_time(value).strftime("%d %b %H:%M")
                if isinstance(value, str) and value.endswith("Z") else value
            )
    status_columns = [column for column in ("Clock status", "Purview") if column in frame]
    styled = frame.style.hide(axis="index").format(precision=1, escape="html")
    if status_columns:
        styled = styled.map(lambda value: status_style(value, config), subset=status_columns)
    st.table(styled)


def overview(config: Config) -> None:
    """Show the product's boundaries before the incident workflow."""
    st.title("TriageGuard")
    st.markdown("**The privacy lens. Human judgment stays in control.**")
    st.write(config["positioning"])
    st.caption("A local rehearsal, not a second summary agent or system of record. Synthetic data; nothing is sent.")
    st.subheader("Three paths · two minutes")
    for column, incident_id, title, steps in zip(
        st.columns(3),
        ("TG-DEMO-001", "TG-DEMO-002", "TG-DEMO-003"),
        ("Routine privacy triage", "Insider escalation", "Engineering handoff"),
        (
            "Confirm an UNKNOWN → review routine routing → approve a deletion draft.",
            "Explain P1 / FTE ownership → inspect red clocks → draft a facts-only update with UNKNOWNs.",
            "Confirm the exclusion → choose the receiving team → review a handoff note.",
        ),
    ):
        with column, st.container(border=True):
            st.caption(incident_id)
            st.markdown(f"**{title}**")
            st.write(steps)
    st.caption("Select a pinned ID in the sidebar, then open Incident. Every recommendation cites the numbered plan.")
    st.caption(f"Privacy response plan: {config['clock_policy_label']}.")
    with st.expander(f"Open privacy response plan · {config['response_plan']['path']}"):
        st.caption(f"Synthetic · {config['clock_policy_label']} · not Microsoft policy · {config['response_plan']['version']}")
        st.markdown((ROOT / response_plan_path(config)).read_text(encoding="utf-8"))
    with st.expander("Guardrails and boundaries"):
        st.markdown(
            "**Guardrails**\n"
            "- Synthetic data only; never paste real incident or customer data.\n"
            "- Rule-based suggestions, with reasons and explicit PM acceptance or override.\n"
            "- No legal or notification decisions; accountable owners retain control.\n"
            "- Drafts only: no delivery capability, external APIs, LLMs, or database.\n"
            "- State stays in this session and local `data/state.json`.\n"
            "- Configuration and business-day clocks are illustrative, not policy."
        )
    with st.expander("Demo controls · restore the starting state"):
        st.caption("Restores all 20 seed cases and clears edits, decisions, drafts, milestones, exports, and PM audit history.")
        confirm_reset = st.checkbox(
            "Replace all local demo edits, approvals, and audit history with the seed data.", key="confirm_reset",
        )
        if st.button("Reset demo data", key="reset_demo", disabled=not confirm_reset):
            reset_demo(config)


def lane_label(incident: Incident, config: Config) -> str:
    """Keep distinct privacy and engineering lanes compact in queue charts."""
    lane = effective_lane(incident)
    if lane == config["routing"]["fte_lane"]:
        return "FTE"
    if lane == config["routing"]["handoff_lane"]:
        return "Eng. handoff"
    return "Routine"


def queue(incidents: list[Incident], config: Config) -> None:
    """Show pinned walkthroughs first, then the soonest active deadlines."""
    st.header("Incident queue")
    st.caption(
        "Demo paths pinned first: " + ", ".join(config["demo"]["pinned_incident_ids"])
        + ". Remaining cases are sorted by the earliest outstanding deadline. "
        "Pins are presentation only, not operational priority. Lane/severity remain provisional until PM review."
    )
    rows: list[dict[str, object]] = []
    ordered = order_incidents(incidents, config)
    for incident in ordered:
        clock = next_clock(incident, config)
        age = (parse_time(config["demo_now"]) - parse_time(incident["reported_at"])).total_seconds() / 3600
        rows.append({
            "ID": incident["id"],
            "Age (h)": round(age, 1), "Severity": effective_severity(incident),
            "Purview": "Out of scope" if effective_purview(incident) == config["purview"]["out_of_scope_label"] else effective_purview(incident),
            "Lane": lane_label(incident, config),
            "Next due (UTC)": clock["deadline"] if clock and clock["deadline"] else "—",
            "Clock status": clock["status"] if clock else "No active clock",
            "Status": incident["status"],
        })
    deadline_table(rows, config)
    st.caption(
        f"Green: OK · Amber: less than {config['clocks']['at_risk_fraction']:.0%} of the clock remains "
        "· Red: deadline reached or breached. Purview: green = in scope, amber = review, blue = engineering handoff; "
        "in scope does not mean safe. All dates UTC; linked records are in Incident."
    )
    st.write("**Open an incident using the sidebar, then select the Incident tab.**")


def fact_editor(incident: Incident, config: Config) -> None:
    """Show evidence and require explicit PM confirmation for manual facts."""
    st.subheader("What we know")
    st.caption(plan_rationale(config, "extraction", "Privacy facts only. UNKNOWN is not a negative answer."))
    rows = [
        {
            "Fact": config["facts"][key],
            "Value": "UNKNOWN" if fact["label"] == "UNKNOWN" else fact_text(fact["value"]),
            "Evidence label": fact["label"],
            "Source": fact["evidence"],
        }
        for key, fact in incident["facts"].items()
    ]
    frame = pd.DataFrame(rows)
    st.table(
        frame.drop(columns="Source").style.hide(axis="index").format(escape="html").map(
            lambda value: status_style(value, config), subset=["Evidence label"],
        )
    )
    with st.expander("Fact sources and evidence"):
        st.table(frame.style.hide(axis="index").format(escape="html"))
    unknowns = [key for key, fact in incident["facts"].items() if fact["label"] == "UNKNOWN"]
    if not unknowns:
        st.success("All fact fields have an explicit value.")
    else:
        with st.expander(f"Questions to ask the reporter · {len(unknowns)} UNKNOWN"):
            for key in unknowns:
                asked = st.checkbox(
                    f"Ask reporter: {config['facts'][key]}?",
                    value=incident["questions_asked"].get(key, False),
                    key=f"question_{incident['id']}_{key}_{incident['revision']}",
                    help="Records that the question was asked, not that an answer is confirmed. Save the verified answer below.",
                )
                if asked != incident["questions_asked"].get(key, False):
                    commit_change(incident["id"], lambda item: record_question(item, key, asked, config), config)
    with st.expander("Confirm or correct a fact", expanded=bool(unknowns)):
        key = st.selectbox(
            "Fact to confirm", list(config["facts"]), format_func=lambda value: config["facts"][value],
            key=f"fact_field_{incident['id']}",
        )
        fact = incident["facts"][key]
        if key == "data_types":
            st.caption("Configured data types: " + ", ".join(config["extraction"]["data_types"]))
        widget_key = f"fact_{incident['id']}_{key}_{incident['revision']}"
        with st.form(f"fact_form_{incident['id']}_{key}_{incident['revision']}"):
            if key in ("contained", "deletion_attested", "privacy_data_involved", "security_process_only"):
                current = fact["value"]
                answer = st.selectbox(
                    "Explicit answer", ["Select an answer", "Yes", "No"],
                    index=1 if current is True else 2 if current is False else 0, key=widget_key,
                )
                value: FactValue = True if answer == "Yes" else False if answer == "No" else None
            elif key == "environment":
                options = ["Select an environment", *config["purview"]["environments"]]
                selection = st.selectbox("Confirmed environment", options, index=options.index(fact["value"]) if fact["value"] in options else 0)
                value = None if selection == options[0] else selection
            elif key == "record_count":
                raw = st.text_input("Non-negative whole record count", value="" if fact["value"] is None else str(fact["value"]), key=widget_key)
                value = int(raw) if raw.isdecimal() else None
            else:
                raw = st.text_input(
                    "Confirmed value (comma-separated for lists)",
                    value="" if fact["value"] is None else fact_text(fact["value"]), key=widget_key,
                )
                value = [item.strip() for item in raw.split(",") if item.strip()] if key in ("data_types", "customers", "regions") else raw.strip()
            note = st.text_input("Source / confirmation note (required)")
            verified = st.checkbox("I verified this answer; mark it CONFIRMED (by PM).")
            if st.form_submit_button("Save confirmed fact"):
                if not verified:
                    st.error("Confirm that you verified the fact before saving.")
                else:
                    commit_change(incident["id"], lambda item: edit_fact(item, key, value, note, config), config)
    st.caption("Fact changes revoke stale decisions and draft approvals; review the refreshed suggestions.")


def decision_control(
    incident: Incident, kind: str, suggested: str | list[str], options: list[str], config: Config
) -> None:
    """Offer explicit acceptance or an override with a required reason."""
    existing = incident["decisions"].get(kind)
    if existing:
        st.success(f"{existing['disposition']}: {fact_text(existing['value'])}")
        st.caption(existing["reason"])
    key = f"{incident['id']}_{kind}_{incident['revision']}"
    with st.form(f"decision_{key}"):
        mode = st.radio("PM decision", ["Accept", "Override"], horizontal=True)
        if isinstance(suggested, list):
            selection: str | list[str] = st.multiselect("Override stakeholders", options, default=suggested)
        else:
            selection = st.selectbox("Override value", options, index=options.index(suggested))
        reason = st.text_input("Override reason (required for Override)")
        if st.form_submit_button("Record decision"):
            value = selection if mode == "Override" else suggested
            commit_change(
                incident["id"],
                lambda item: record_decision(item, kind, value, mode == "Override", reason, config),
                config,
            )


def suggestions_panel(incident: Incident, config: Config) -> None:
    """Display every recommendation with its rationale and PM controls."""
    st.subheader("Recommended next actions (suggestions – PM approves)")
    st.markdown("**Privacy purview · suggestion**")
    status_badge(incident["purview"]["status"], config)
    for reason in incident["purview"]["rationale"]:
        st.write(reason)
    decision_control(
        incident, "purview", incident["purview"]["status"],
        [config["purview"][key] for key in ("in_scope_label", "out_of_scope_label", "review_label")], config,
    )
    if incident["purview"]["receiving_team"] and effective_purview(incident) == config["purview"]["out_of_scope_label"]:
        st.markdown(f"**Suggested receiving team: {incident['purview']['receiving_team']}**")
        st.caption(plan_rationale(config, "routing_handoff", "Synthetic engineering ownership proposal; PM coordinates acceptance in the existing platform."))
        decision_control(
            incident, "receiving_team", incident["purview"]["receiving_team"],
            list(config["purview"]["receiving_teams"].values()), config,
        )
        st.warning("Use the handoff/closure note below after PM review. Approval does not transfer ownership or close the case.")
    if effective_purview(incident) == config["purview"]["out_of_scope_label"]:
        st.caption("Privacy severity below is reference only, not an engineering severity or proof that the engineering concern is resolved.")
    severity_column, routing_column = st.columns(2)
    with severity_column:
        st.markdown(f"**Provisional severity: {incident['severity']['severity']}**")
        for reason in incident["severity"]["rationale"]:
            st.write(f"• {reason}")
        decision_control(incident, "severity", incident["severity"]["severity"], config["severity"]["levels"], config)
    with routing_column:
        st.markdown(f"**Suggested lane: {incident['routing']['lane']}**")
        for reason in incident["routing"]["rationale"]:
            st.write(f"• {reason}")
        decision_control(
            incident, "routing", incident["routing"]["lane"],
            [
                config["routing"]["fte_lane"], config["routing"]["routine_lane"],
                *([config["routing"]["handoff_lane"]] if incident["routing"]["lane"] == config["routing"]["handoff_lane"] else []),
            ], config,
        )
    if incident["routing"]["lane"] == config["routing"]["fte_lane"]:
        with st.expander("Why this was escalated", expanded=True):
            st.write("\n\n".join(incident["routing"]["rationale"]))
            st.caption("This is an ownership suggestion, not a notification or legal determination.")
    with st.expander("Suggested stakeholders and why", expanded=True):
        for item in incident["stakeholders"]:
            st.write(f"**{item['name']}** — {item['reason']}")
        decision_control(
            incident, "stakeholders", [item["name"] for item in incident["stakeholders"]],
            [item["name"] for item in config["stakeholders"]], config,
        )
    if incident["severity"]["closure_suggested"]:
        st.warning(f"PM review suggestion: {config['severity']['closure_label']}. No automatic closure.")
        decision_control(
            incident, "closure", config["severity"]["closure_label"],
            [config["severity"]["closure_label"], "Keep open"], config,
        )
        st.caption("Accepting this recommendation does not close the case. Use the separate status control.")


def clocks_panel(incident: Incident, config: Config) -> None:
    """Show countdowns and distinguish approval clocks from manual completion."""
    st.subheader(f"Response clocks — {config['clock_policy_label']}")
    rows: list[dict[str, object]] = []
    for clock in calculate_clocks(incident, config):
        remaining = clock["remaining_hours"]
        rows.append({
            "Clock": clock["label"], "Due (UTC)": clock["deadline"] or "Not started",
            "Countdown": (
                "—" if remaining is None else
                ("Complete" if clock["status"] == "Completed" else
                 "Stopped" if clock["status"] == "Stopped (closed)" else
                 f"{abs(remaining):.1f}h {'overdue' if remaining <= 0 else 'remaining'}")
            ),
            "Clock status": clock["status"],
            "Completed": clock["completed_at"] or "—",
        })
    deadline_table(rows, config)
    for clock in calculate_clocks(incident, config):
        st.caption(clock["rationale"])
    st.caption(
        "UTC; business days skip weekends, not holidays. Deletion clock starts at request approval, "
        "not delivery. Contained status does not confirm containment facts. Closed cases stop pending clocks."
    )
    st.info(
        "Notification-assessment review is coordination with accountable owners, not a notification deadline "
        "or legal decision. Actual statutory, contractual, and customer commitments are not determined here."
    )
    with st.expander("Record an action completed manually outside this prototype"):
        rules = {rule["completed_by"]: rule for rule in config["clocks"]["rules"] if rule.get("manual_completion")}
        event = st.selectbox(
            "Completed action", list(rules),
            format_func=lambda item: rules[item]["label"] + " completed manually",
            key=f"manual_action_{incident['id']}",
        )
        attested = st.checkbox("I confirm this action was completed manually.", key=f"manual_confirm_{incident['id']}")
        if st.button("Record manual completion", key=f"record_manual_{incident['id']}", disabled=not attested):
            commit_change(incident["id"], lambda item: record_completion(item, event, config), config)


def drafts_panel(incident: Incident, config: Config) -> None:
    """Edit drafts and explicitly gate manual-delivery approval."""
    st.subheader("Drafts and approval gate")
    st.info("No messages can be sent here. Approval means ready for a person to send manually.")
    st.caption(f"Any clock values in drafts: {config['clock_policy_label']}.")
    kinds = ["deletion", "status"]
    handoff_eligible = (
        incident["purview"]["status"] == config["purview"]["out_of_scope_label"]
        and effective_purview(incident) == config["purview"]["out_of_scope_label"]
    )
    if handoff_eligible or "handoff" in incident["drafts"]:
        kinds.append("handoff")
    for kind in kinds:
        with st.expander(config["drafts"][kind]["title"], expanded=kind in incident["drafts"]):
            st.caption(plan_rationale(config, config["drafts"][kind]["plan_rule"], config["drafts"][kind]["reason"]))
            if kind == "handoff":
                st.caption("Before approval: record out-of-scope purview and receiving-team decisions above. An approved note never closes or transfers a case.")
            if st.button(
                "Generate / regenerate draft", key=f"generate_{incident['id']}_{kind}",
                disabled=kind == "handoff" and not handoff_eligible,
            ):
                commit_change(incident["id"], lambda item: generate_draft(item, kind, config), config)
            draft = incident["drafts"].get(kind)
            if not draft:
                continue
            st.write(f"**{draft['status']}**")
            if draft["status"] == "Needs regeneration":
                st.warning("Incident context changed. Regenerate and review before approval.")
            with st.form(f"draft_{incident['id']}_{kind}_{incident['revision']}"):
                text = st.text_area("Draft text", draft["text"], height=300)
                override_reason = st.text_input("Reason for template edits (required if edited)")
                review = st.checkbox("I reviewed this text; approve for manual delivery only.")
                save = st.form_submit_button("Save edited draft")
                approve = st.form_submit_button("Approve — ready to send manually")
                if save or approve:
                    if text != draft["text"] and not override_reason.strip():
                        st.error("Provide a reason for overriding the suggested template.")
                    elif approve and not review:
                        st.error("Review and confirm approval before continuing.")
                    else:
                        def save_action(item: Incident) -> None:
                            save_draft(item, kind, text, approve, config)
                            if text != draft["text"]:
                                append_event(
                                    item, config["demo_now"], "PM", f"{kind} template override reason",
                                    None, override_reason.strip(),
                                )
                        commit_change(incident["id"], save_action, config)
            st.caption(plan_rationale(
                config, "approval",
                "Editing clears approval. Changed facts or decisions require regeneration. "
                "A status change preserves an unchanged deletion-request template, but invalidates status/handoff drafts.",
            ))


def exports_panel(incident: Incident, config: Config) -> None:
    """Prepare a persistent, audited export snapshot and expose audit evidence."""
    st.subheader("Case record and audit")
    if st.button("Export summary to case record", key=f"export_{incident['id']}"):
        def export_action(item: Incident) -> None:
            append_event(
                item, config["demo_now"], "PM", "export summary prepared",
                None, {"format": "txt", "integration": "None; manual copy/download only"},
            )
            item["revision"] += 1
        incidents = deepcopy(st.session_state["incidents"])
        item = next(candidate for candidate in incidents if candidate["id"] == incident["id"])
        export_action(item)
        try:
            summary = export_summary(item, config)
            persist_state(incidents, STATE_PATH, config)
        except (OSError, ValueError) as error:
            st.error(f"Export not saved: {error}")
        else:
            st.session_state["incidents"] = incidents
            st.session_state["export_snapshot"] = {"id": item["id"], "text": summary}
            st.rerun()
    snapshot = st.session_state.get("export_snapshot")
    if snapshot and snapshot["id"] == incident["id"]:
        st.text_area("Copy-ready case summary", snapshot["text"], height=300, disabled=True)
        st.download_button("Download case summary (.txt)", snapshot["text"], file_name=f"{incident['id']}-summary.txt", mime="text/plain")
    with st.expander(f"Audit trail ({len(incident['audit'])} actions)"):
        st.caption("Append-only within this local demo; not tamper-evident or production-grade.")
        for event in reversed(incident["audit"]):
            st.write(f"**{event['timestamp']} · {event['actor']} · {event['action']}**")
            st.json({"before": event["before"], "after": event["after"]}, expanded=False)
        st.download_button(
            "Download audit (.csv)", audit_csv(incident),
            file_name=f"{incident['id']}-audit.csv", mime="text/csv",
        )


def lens_panel(incident: Incident, config: Config) -> None:
    """Contrast the existing agents' scope with privacy evidence, without running them."""
    with st.expander("Privacy lens vs. engineering lens", expanded=True):
        engineering, privacy = st.columns(2)
        with engineering:
            st.markdown("**Engineering lens — existing platform agents**")
            engineering_owned = incident["purview"]["status"] == config["purview"]["out_of_scope_label"]
            if engineering_owned:
                st.info(
                    "Relevant lens: engineering security-process review. The receiving team should assess "
                    "diagnostic/access logs and access controls; error rates, SLOs, and deployment context "
                    "are engineering checks to assess as relevant, not evidence of privacy impact."
                )
            check_status = (
                "engineering-owned check — not run here; receiving team assesses relevance."
                if engineering_owned
                else "not applicable / not run by this privacy prototype."
            )
            for check in ("Logs", "Error rates", "SLOs", "Deployments"):
                st.write(f"**{check}:** {check_status}")
            st.caption(
                "Troubleshooting and SRE agents remain in the incident platform. "
                "Not run does not mean healthy or resolved; engineering may still need to investigate."
            )
        with privacy:
            st.markdown("**Privacy lens — response-plan evidence**")
            for key in ("data_types", "customers", "regions", "contained", "deletion_attested"):
                fact = incident["facts"][key]
                value = "UNKNOWN" if fact["label"] == "UNKNOWN" else fact_text(fact["value"])
                st.write(f"**{config['facts'][key]}:** {value} [{fact['label']}]")
            st.write(f"**Purview:** {incident['purview']['status']} [suggestion]")
            assessment = next(clock for clock in calculate_clocks(incident, config) if clock["id"] == "notification_assessment")
            st.write(f"**Notification-assessment clock:** {assessment['status']} · {assessment['deadline'] or 'No explicit review request'}")
            st.caption(assessment["rationale"])
            st.caption("Actual notification requirements remain UNKNOWN here; accountable privacy/legal owners establish them.")


def actions_done_panel(incident: Incident, config: Config) -> None:
    """Show recorded actions, never recommendations disguised as completed response."""
    st.subheader("What has been done")
    st.write(f"**Recorded workflow status:** {incident['status']}")
    st.caption("A status label is not confirmation of containment, delivery, ownership acceptance, or engineering remediation.")
    pm_actions = [event for event in incident["audit"] if event["actor"] == "PM"]
    if not pm_actions:
        st.info("No PM actions recorded yet. System extraction and suggestions are not completed response actions.")
    else:
        latest = pm_actions[-1]
        st.write(f"**Latest:** {latest['timestamp']} · {latest['action']}")
        with st.expander("Recent PM actions"):
            for event in pm_actions[-8:]:
                st.write(f"**{event['timestamp']}** · {event['action']}")
    if incident["events"]:
        with st.expander("Recorded action milestones"):
            for name, timestamp in incident["events"].items():
                st.write(f"{name}: {timestamp}")
    st.caption(plan_rationale(config, "approval", "Draft approval records readiness for manual delivery only; nothing is sent. Full before/after evidence is in the audit trail."))


def incident_view(incident: Incident, config: Config) -> None:
    """Rehearse the privacy plan in the existing platform's three summary slots."""
    st.header(incident["id"])
    st.caption(
        f"IcM: {incident['linked_icm_id'] or 'not linked'} · "
        f"Case: {incident['linked_case_id'] or 'not linked'} · "
        f"Reported: {incident['reported_at']} · {incident['reporter_team']} · {incident['channel']}"
    )
    st.caption(
        "Privacy-specific response-plan rehearsal, not a second AI summary or engineering investigation. "
        f"Plan: {config['response_plan']['path']} ({config['response_plan']['version']}) · {config['clock_policy_label']}."
    )
    purview_column, severity_column, clock_column = st.columns(3)
    with purview_column, st.container(border=True):
        st.caption("Purview · " + ("PM decision" if "purview" in incident["decisions"] else "suggestion"))
        status_badge(effective_purview(incident), config)
    with severity_column, st.container(border=True):
        st.caption("Privacy severity / lane · " + ("PM decision" if {"severity", "routing"} <= incident["decisions"].keys() else "provisional"))
        st.markdown(f"**{effective_severity(incident)} · {lane_label(incident, config)}**")
        if incident["purview"]["status"] == config["purview"]["out_of_scope_label"]:
            st.caption("Privacy reference only, not engineering severity.")
    with clock_column, st.container(border=True):
        clock = next_clock(incident, config)
        st.caption(f"Next response clock · {config['clock_policy_label']}")
        status_badge(clock["status"] if clock else "No active clock", config)
        if clock:
            st.caption(f"{clock['label']} · {clock['deadline']}")
    with st.expander("Original synthetic report"):
        st.write(incident["raw_description"])
    fact_editor(incident, config)
    lens_panel(incident, config)
    st.divider()
    actions_done_panel(incident, config)
    st.divider()
    suggestions_panel(incident, config)
    with st.form(f"status_form_{incident['id']}_{incident['revision']}"):
        status = st.selectbox("PM workflow status", config["statuses"], index=config["statuses"].index(incident["status"]))
        if st.form_submit_button("Record status change"):
            commit_change(incident["id"], lambda item: change_status(item, status, config), config)
    st.divider()
    clocks_panel(incident, config)
    st.divider()
    drafts_panel(incident, config)
    st.divider()
    exports_panel(incident, config)


def dashboard(incidents: list[Incident], config: Config) -> None:
    """Summarize actual workflow outcomes and repeat prevention patterns."""
    st.header("Triage and prevention dashboard")
    all_clocks = [(incident, clock) for incident in incidents for clock in calculate_clocks(incident, config)]
    triaged = [clock for _, clock in all_clocks if clock["id"] == "initial_triage" and clock["completed_at"]]
    met = sum(clock["met"] is True for clock in triaged)
    at_risk = [(incident, clock) for incident, clock in all_clocks if clock["status"] in ("At risk", "Breached")]
    first, second, third = st.columns(3)
    first.metric("Incidents", len(incidents))
    second.metric("Triaged within clock", f"{100 * met / len(triaged):.0f}%" if triaged else "N/A")
    third.metric("At-risk / breached clocks", len(at_risk))
    st.caption(f"Triage KPI denominator: {len(triaged)} incidents with a PM-recorded first triage; {met} on time. Untriaged cases are excluded, not counted as successes.")
    status_column, lane_column = st.columns(2)
    with status_column:
        st.markdown("**Counts by status**")
        counts = Counter(item["status"] for item in incidents)
        st.bar_chart(pd.DataFrame({"Count": [counts[status] for status in config["statuses"]]}, index=config["statuses"]))
    with lane_column:
        st.markdown("**Counts by lane (provisional until accepted)**")
        lanes = Counter(lane_label(item, config) for item in incidents)
        st.bar_chart(pd.DataFrame.from_dict(lanes, orient="index", columns=["Count"]))
    st.markdown("**Open incident age**")
    cutoffs = config["dashboard"]["aging_hours"]
    labels = [f"<{cutoffs[0]}h"] + [f"{low}–<{high}h" for low, high in zip(cutoffs, cutoffs[1:])] + [f"≥{cutoffs[-1]}h"]
    ages = Counter()
    for incident in incidents:
        if incident["status"] == config["workflow"]["closed_status"]:
            continue
        age = (parse_time(config["demo_now"]) - parse_time(incident["reported_at"])).total_seconds() / 3600
        ages[labels[sum(age >= cutoff for cutoff in cutoffs)]] += 1
    st.bar_chart(pd.DataFrame({"Count": [ages[label] for label in labels]}, index=labels))
    st.markdown("**At risk and breached**")
    rows = [
        {"ID": incident["id"], "Clock": clock["label"], "Due (UTC)": clock["deadline"], "Clock status": clock["status"]}
        for incident, clock in sorted(at_risk, key=lambda pair: pair[1]["deadline"] or "")
    ]
    deadline_table(rows, config)
    reporter_column, cause_column = st.columns(2)
    for column, field, title in (
        (reporter_column, "reporter_team", "Repeat reporter teams"),
        (cause_column, "root_cause_category", "Repeat root causes"),
    ):
        with column:
            st.markdown(f"**{title}**")
            counts = Counter(str(incident[field]) for incident in incidents)
            st.bar_chart(pd.DataFrame.from_dict(dict(counts.most_common(5)), orient="index", columns=["Count"]))
    st.caption("Patterns suggest where prevention work could reduce volume; reporter counts are not a performance judgment.")


def main() -> None:
    """Load local configuration and state, failing visibly without overwriting data."""
    st.html("""
        <style>
        .stMainBlockContainer { padding-top: 4rem; padding-bottom: 2rem; }
        [data-testid="stVerticalBlock"] { gap: 0.75rem; }
        h1 { font-size: 2rem !important; }
        h2 { font-size: 1.45rem !important; }
        h3 { font-size: 1.15rem !important; }
        [data-testid="stTable"] table { width: 100%; }
        [data-testid="stTable"] th, [data-testid="stTable"] td {
            white-space: normal; overflow-wrap: anywhere;
            padding: 0.5rem 0.6rem; font-size: 0.875rem; vertical-align: top;
        }
        </style>
    """)
    try:
        config = load_config(ROOT / "config.yaml")
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
        st.error(f"Cannot load config.yaml: {error}")
        st.stop()
    st.warning(config["banner"])
    st.sidebar.title("TriageGuard")
    st.sidebar.caption(f"Deterministic demo time (UTC)\n\n{config['demo_now']}")
    try:
        if "active_config" in st.session_state and st.session_state["active_config"] != config:
            raise ValueError("Configuration changed. Reset demo data to apply the new rules.")
        if "incidents" not in st.session_state:
            incidents = load_state(SEED_PATH, STATE_PATH, config)
            persist_state(incidents, STATE_PATH, config)
            st.session_state["incidents"] = incidents
            st.session_state["active_config"] = deepcopy(config)
    except (OSError, ValueError, KeyError, TypeError) as error:
        st.error(f"Local state could not be loaded: {error}")
        st.write("No saved data was overwritten. Preserve data/state.json before resetting if you need the edits.")
        confirmed_reset = st.checkbox("Discard saved state and restore synthetic seeds.")
        if st.button("Reset demo data", disabled=not confirmed_reset):
            reset_demo(config)
        st.stop()
    incidents = st.session_state["incidents"]
    selected_id = st.sidebar.selectbox(
        "Open incident", [incident["id"] for incident in order_incidents(incidents, config)], key="selected_incident",
    )
    st.sidebar.caption("Choose an ID, then open the Incident tab. All data is fictional; nothing is delivered.")
    overview_tab, queue_tab, incident_tab, dashboard_tab = st.tabs(["Overview", "Queue", "Incident", "Dashboard"])
    with overview_tab:
        overview(config)
    with queue_tab:
        queue(incidents, config)
    with incident_tab:
        incident_view(next(item for item in incidents if item["id"] == selected_id), config)
    with dashboard_tab:
        dashboard(incidents, config)


if __name__ == "__main__":
    main()
