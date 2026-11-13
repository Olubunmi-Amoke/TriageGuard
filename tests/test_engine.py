"""Focused policy, workflow, persistence, no-delivery, and UI regressions."""

import ast
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from engine.audit import audit_csv
from engine.clocks import add_business_days, calculate_clocks, next_clock, parse_time
from engine.config import load_config
from engine.drafts import suggest_draft
from engine.export import export_summary
from engine.extract import suggest_extract
from engine.purview import suggest_purview
from engine.queue import order_incidents
from engine.state import (
    change_status,
    edit_fact,
    generate_draft,
    initialize_incident,
    load_seed,
    load_state,
    persist_state,
    record_completion,
    record_decision,
    record_question,
    save_draft,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config():
    return load_config(ROOT / "config.yaml")


@pytest.fixture
def seeds():
    return json.loads((ROOT / "data" / "incidents.json").read_text(encoding="utf-8"))


@pytest.fixture
def routine(config, seeds):
    return initialize_incident(seeds[0], config)


def clock_by_id(incident, config, clock_id):
    return next(clock for clock in calculate_clocks(incident, config) if clock["id"] == clock_id)


def test_seed_mix_and_deadline_diversity(config, seeds):
    assert len(seeds) == 20
    incidents = load_seed(ROOT / "data" / "incidents.json", config)
    assert {next_clock(item, config)["status"] for item in incidents} == {"OK", "At risk", "Breached"}
    assert sum(item["severity"]["closure_suggested"] for item in incidents) == 3
    assert sum("misdirected" in seed["raw_description"] for seed in seeds[:6]) == 6
    for seed in seeds:
        age = parse_time(config["demo_now"]) - parse_time(seed["reported_at"])
        assert 0 <= age.total_seconds() <= 5 * 24 * 3600
        assert 2 <= seed["raw_description"].count(".") <= 4


def test_explicit_extraction_including_false_and_zero(config, seeds):
    facts = suggest_extract(seeds[1], config)
    assert facts["customers"]["value"] == ["Pebblekite Kitchens"]
    assert facts["regions"]["value"] == ["Europe"]
    assert facts["deletion_attested"]["value"] is False
    assert facts["deletion_attested"]["label"] == "CONFIRMED"
    assert suggest_extract(seeds[-1], config)["record_count"]["value"] == 0


def test_missing_facts_remain_unknown(config, seeds):
    facts = suggest_extract(seeds[2], config)
    assert facts["data_types"]["label"] == "UNKNOWN"
    assert facts["contained"]["value"] is None
    assert facts["record_count"]["label"] == "UNKNOWN"


def test_unknown_placeholders_and_uncertain_mechanism_not_confirmed(config, seeds):
    seed = {
        **seeds[0],
        "raw_description": "Affected region: unknown. Mechanism: possibly exported from a portal.",
    }
    facts = suggest_extract(seed, config)
    assert facts["regions"]["label"] == facts["how_happened"]["label"] == "UNKNOWN"


@pytest.mark.parametrize("description", [
    "No health data was involved.",
    "Possibly credentials were included.",
    "It is unknown whether contact details were exposed.",
])
def test_negated_or_speculative_types_not_confirmed(config, seeds, description):
    seed = {**seeds[0], "raw_description": description}
    assert suggest_extract(seed, config)["data_types"]["label"] == "UNKNOWN"


def test_conflicting_explicit_evidence_stays_unknown(config, seeds):
    seed = {**seeds[0], "known_fields": {"contained": False}}
    assert suggest_extract(seed, config)["contained"]["label"] == "UNKNOWN"
    seed = {**seeds[0], "raw_description": "Containment: confirmed. Containment: not confirmed."}
    assert suggest_extract(seed, config)["contained"]["label"] == "UNKNOWN"


@pytest.mark.parametrize("index", [8, 9, 10, 11])
def test_attack_and_insider_keep_highest_severity(index, config, seeds):
    incident = initialize_incident(seeds[index], config)
    assert incident["severity"]["severity"] == "P1"
    assert incident["routing"]["lane"] == "FTE-owned"
    assert incident["severity"]["rationale"]


def test_sensitive_and_large_count_elevate(config, seeds):
    sensitive = initialize_incident(seeds[3], config)
    large = initialize_incident(seeds[6], config)
    assert sensitive["severity"]["severity"] == large["severity"]["severity"] == "P2"
    assert any("sensitive" in reason for reason in sensitive["severity"]["rationale"])
    assert any("threshold" in reason for reason in large["severity"]["rationale"])


def test_containment_reduction_never_makes_sensitive_routine(config, seeds):
    seed = deepcopy(seeds[3])
    seed["raw_description"] = seed["raw_description"].replace("deletion attested: no", "deletion attested: yes")
    incident = initialize_incident(seed, config)
    assert incident["severity"]["severity"] == "P3"
    assert incident["routing"]["lane"] == "FTE-owned"
    assert any("sensitive" in reason for reason in incident["routing"]["rationale"])


def test_nonincident_is_suggestion_not_automatic_closure(config, seeds):
    incident = initialize_incident(seeds[15], config)
    assert incident["severity"]["closure_suggested"] is True
    assert incident["status"] == "New"
    assert incident["decisions"] == {}
    record_decision(incident, "closure", config["severity"]["closure_label"], False, "", config)
    assert incident["status"] == "New"


def test_routine_requires_explicit_eligibility(routine, config, seeds):
    assert routine["routing"]["lane"] == "Vendor-supported routine queue"
    incomplete = initialize_incident(seeds[2], config)
    assert incomplete["routing"]["lane"] == "FTE-owned"
    assert any("UNKNOWN" in reason for reason in incomplete["routing"]["rationale"])


@pytest.mark.parametrize("index", [12, 13, 14])
def test_vendor_and_restricted_cases_stay_fte(index, seeds, config):
    assert initialize_incident(seeds[index], config)["routing"]["lane"] == "FTE-owned"


def test_config_changes_control_thresholds(routine, seeds, config):
    config["routing"]["max_routine_records"] = 10
    incident = initialize_incident(seeds[0], config)
    assert incident["routing"]["lane"] == "FTE-owned"
    config["severity"]["large_record_count"] = 12
    config["severity"]["containment_reduction"] = 0
    assert initialize_incident(seeds[0], config)["severity"]["severity"] == "P2"


def test_purview_explicit_privacy_data_is_in_scope(routine, config):
    assert routine["purview"]["status"] == config["purview"]["in_scope_label"]
    assert routine["purview"]["receiving_team"] is None
    assert routine["purview"]["rationale"][0].startswith("Rule fired: Plan §1.1")


@pytest.mark.parametrize(("index", "team"), [
    (18, "Demo Sandbox Engineering"), (19, "Demo Developer Tools Engineering"),
])
def test_engineering_process_seed_excluded_with_receiving_team(seeds, config, index, team):
    incident = initialize_incident(seeds[index], config)
    assert incident["purview"]["status"] == config["purview"]["out_of_scope_label"]
    assert incident["purview"]["receiving_team"] == team
    assert incident["routing"]["lane"] == config["routing"]["handoff_lane"]
    assert incident["facts"]["data_types"]["value"] == ["internal identifier"]
    assert incident["facts"]["privacy_data_involved"]["value"] is False
    assert incident["status"] == "New" and incident["decisions"] == {}


@pytest.mark.parametrize("key", [
    "privacy_data_involved", "security_process_only", "environment", "data_types", "record_count",
])
def test_exclusion_requires_every_confirmed_fact(seeds, config, key):
    incident = initialize_incident(seeds[18], config)
    incident["facts"][key] = {"value": None, "label": "UNKNOWN", "evidence": "Not stated."}
    result = suggest_purview(incident["raw_description"], incident["facts"], config)
    assert result["status"] == config["purview"]["review_label"]
    assert result["receiving_team"] is None


@pytest.mark.parametrize(("key", "value"), [
    ("privacy_data_involved", True), ("environment", "production"),
    ("security_process_only", False), ("record_count", 1),
    ("data_types", ["internal identifier", "contact details"]),
])
def test_exclusion_rejects_contradictory_or_ineligible_values(seeds, config, key, value):
    incident = initialize_incident(seeds[18], config)
    incident["facts"][key]["value"] = value
    result = suggest_purview(incident["raw_description"], incident["facts"], config)
    assert result["status"] != config["purview"]["out_of_scope_label"]
    assert result["receiving_team"] is None


@pytest.mark.parametrize("indicator", [
    "External attack reported.", "Suspected insider misuse reported.",
    "Government customer involved.", "Vendor-handled data reported.",
    "Notification assessment requested.", "Contact details included.",
])
def test_protected_indicators_prevent_engineering_exclusion(seeds, config, indicator):
    seed = {**seeds[18], "raw_description": seeds[18]["raw_description"] + " " + indicator}
    incident = initialize_incident(seed, config)
    assert incident["purview"]["status"] == config["purview"]["review_label"]
    assert incident["purview"]["receiving_team"] is None
    assert incident["routing"]["lane"] == config["routing"]["fte_lane"]


def test_insufficient_information_needs_review(seeds, config):
    incident = initialize_incident(seeds[2], config)
    assert incident["purview"]["status"] == config["purview"]["review_label"]


@pytest.mark.parametrize("extra", [
    "Environment: production.", "Approximately 10 records.",
    "Customer or personal data involved: yes.",
])
def test_conflicting_report_claims_cannot_produce_handoff(seeds, config, extra):
    seed = {**seeds[18], "raw_description": seeds[18]["raw_description"] + " " + extra}
    incident = initialize_incident(seed, config)
    assert incident["purview"]["status"] == config["purview"]["review_label"]
    with pytest.raises(ValueError, match="out-of-scope evidence"):
        generate_draft(incident, "handoff", config)


def test_handoff_draft_states_confirmed_exclusion_unknowns_and_further_asks(seeds, config):
    incident = initialize_incident(seeds[18], config)
    generate_draft(incident, "handoff", config)
    text = incident["drafts"]["handoff"]["text"]
    assert "Demo Sandbox Engineering" in text
    assert "Customer or personal data involved: No [CONFIRMED]" in text
    assert "Regions affected: UNKNOWN" in text
    assert "Rule fired: Plan §1.2" in text
    assert "Direct further engineering/security-process asks" in text
    assert "does not transfer ownership or close" in text
    assert incident["drafts"]["handoff"]["approved_at"] is None
    assert incident["events"] == {}


def approve_handoff(incident, config):
    """Make the two explicit PM decisions required to approve a handoff."""
    record_decision(incident, "purview", config["purview"]["out_of_scope_label"], False, "", config)
    record_decision(incident, "receiving_team", incident["purview"]["receiving_team"], False, "", config)
    generate_draft(incident, "handoff", config)
    save_draft(incident, "handoff", incident["drafts"]["handoff"]["text"], True, config)


def test_handoff_approval_requires_purview_and_team_decisions(seeds, config):
    incident = initialize_incident(seeds[18], config)
    generate_draft(incident, "handoff", config)
    with pytest.raises(ValueError, match="purview and receiving-team"):
        save_draft(incident, "handoff", incident["drafts"]["handoff"]["text"], True, config)
    approve_handoff(incident, config)
    assert incident["drafts"]["handoff"]["status"] == config["drafts"]["approved_label"]
    assert incident["status"] == "New"
    assert incident["events"] == {}
    assert any(event["action"] == "handoff draft approval" for event in incident["audit"])
    assert "Engineering handoff" in export_summary(incident, config)


def test_receiving_team_override_is_used_in_handoff(seeds, config):
    incident = initialize_incident(seeds[18], config)
    record_decision(incident, "purview", config["purview"]["out_of_scope_label"], False, "", config)
    record_decision(incident, "receiving_team", "Demo Developer Tools Engineering", True, "Confirmed receiving owner for this demo.", config)
    assert "Demo Developer Tools Engineering" in suggest_draft("handoff", incident, config)


def test_approved_handoff_persists_without_delivery_or_closure(tmp_path, seeds, config):
    incident = initialize_incident(seeds[19], config)
    approve_handoff(incident, config)
    path = tmp_path / "state.json"
    persist_state([incident], path, config)
    restored = load_state(ROOT / "data" / "incidents.json", path, config)[0]
    assert restored["drafts"]["handoff"]["status"] == config["drafts"]["approved_label"]
    assert restored["decisions"]["receiving_team"]["value"] == "Demo Developer Tools Engineering"
    assert restored["events"] == {}
    assert restored["status"] == "New"
    assert not any("sent" in event["action"] or "transfer completed" in event["action"] for event in restored["audit"])


def test_speculative_handoff_edit_cannot_be_approved(seeds, config):
    incident = initialize_incident(seeds[18], config)
    approve_handoff(incident, config)
    with pytest.raises(ValueError, match="speculative"):
        save_draft(incident, "handoff", "Notification is required.", True, config)


def test_in_scope_incident_cannot_generate_handoff_even_with_override(routine, config):
    with pytest.raises(ValueError, match="out-of-scope evidence"):
        generate_draft(routine, "handoff", config)
    record_decision(routine, "purview", config["purview"]["out_of_scope_label"], True, "Requested manual scope exception.", config)
    with pytest.raises(ValueError, match="out-of-scope evidence"):
        generate_draft(routine, "handoff", config)
    assert routine["routing"]["lane"] == config["routing"]["fte_lane"]


def test_changed_purview_fact_revokes_handoff_and_decisions(seeds, config):
    incident = initialize_incident(seeds[18], config)
    approve_handoff(incident, config)
    edit_fact(incident, "privacy_data_involved", True, "Reporter corrected data involvement.", config)
    assert incident["purview"]["status"] == config["purview"]["review_label"]
    assert incident["decisions"] == {}
    assert incident["drafts"]["handoff"]["status"] == "Needs regeneration"
    assert incident["drafts"]["handoff"]["approved_at"] is None
    assert incident["routing"]["lane"] == config["routing"]["fte_lane"]
    assert "PRIVACY PURVIEW HANDOFF / CLOSURE NOTE" not in export_summary(incident, config)


def test_purview_override_blocks_existing_handoff(seeds, config):
    incident = initialize_incident(seeds[18], config)
    approve_handoff(incident, config)
    record_decision(incident, "purview", config["purview"]["review_label"], True, "New evidence requires review.", config)
    assert "receiving_team" not in incident["decisions"]
    assert incident["drafts"]["handoff"]["status"] == "Needs regeneration"
    with pytest.raises(ValueError, match="conflicting PM purview"):
        generate_draft(incident, "handoff", config)


def test_all_rule_rationales_reference_existing_plan_sections(seeds, config):
    sections = set(config["response_plan"]["rules"].values())
    for seed in seeds:
        incident = initialize_incident(seed, config)
        reasons = [
            *incident["purview"]["rationale"], *incident["severity"]["rationale"],
            *incident["routing"]["rationale"],
            *(item["reason"] for item in incident["stakeholders"]),
            *(clock["rationale"] for clock in calculate_clocks(incident, config)),
            *(fact["evidence"] for fact in incident["facts"].values()),
        ]
        for reason in reasons:
            assert reason.startswith("Rule fired: Plan §")
            assert reason.split("§")[1].split()[0] in sections
        # All seeded cases can produce a facts-only update with the expanded facts.
        assert suggest_draft("status", incident, config)


def test_missing_plan_section_rejected(tmp_path, config):
    import yaml
    config["response_plan"]["path"] = str(ROOT / "docs" / "privacy-response-plan.md")
    config["response_plan"]["rules"]["purview_in"] = "99.1"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="missing response-plan section"):
        load_config(path)


def test_notification_assessment_clock_is_explicit_review_not_automatic_obligation(seeds, config):
    ordinary = initialize_incident(seeds[0], config)
    clock = clock_by_id(ordinary, config, "notification_assessment")
    assert clock["status"] == "Not applicable (no assessment requested)"
    assert clock["deadline"] is None
    with pytest.raises(ValueError, match="not applicable"):
        record_completion(ordinary, "notification_assessment_recorded_at", config)
    restricted = initialize_incident(seeds[14], config)
    clock = clock_by_id(restricted, config, "notification_assessment")
    assert clock["deadline"] == "2026-11-08T18:00:00Z"
    assert clock["status"] == "Breached"
    assert clock["rationale"].startswith("Rule fired: Plan §6.5")
    record_completion(restricted, "notification_assessment_recorded_at", config)
    assert clock_by_id(restricted, config, "notification_assessment")["status"] == "Completed"
    assert clock_by_id(restricted, config, "notification_assessment")["met"] is False


def test_stakeholders_explain_why(config, seeds):
    incident = initialize_incident(seeds[8], config)
    names = {item["name"] for item in incident["stakeholders"]}
    assert {"Privacy", "Legal", "Security", "Engineering owner", "Account/customer-facing team"} <= names
    assert all(item["reason"] for item in incident["stakeholders"])


@pytest.mark.parametrize(("start", "days", "expected"), [
    ("2026-11-06T14:00:00Z", 1, "2026-11-09T14:00:00Z"),
    ("2026-11-06T14:00:00Z", 3, "2026-11-11T14:00:00Z"),
    ("2026-11-07T14:00:00Z", 1, "2026-11-09T14:00:00Z"),
    ("2026-11-08T14:00:00Z", 1, "2026-11-09T14:00:00Z"),
    ("2026-11-09T14:00:00Z", 0, "2026-11-09T14:00:00Z"),
])
def test_business_day_math(start, days, expected):
    assert add_business_days(parse_time(start), days) == parse_time(expected)


@pytest.mark.parametrize(("elapsed", "expected"), [
    (2, "OK"), (3, "OK"), (3.01, "At risk"), (4, "Breached"), (5, "Breached"),
])
def test_exact_clock_risk_boundaries(routine, config, elapsed, expected):
    from datetime import timedelta
    from engine.clocks import iso_time
    config["demo_now"] = iso_time(parse_time(routine["reported_at"]) + timedelta(hours=elapsed))
    clock = clock_by_id(routine, config, "initial_triage")
    assert clock["status"] == expected


def test_timezone_required_and_normalized():
    assert parse_time("2026-11-12T10:00:00-06:00") == datetime(2026, 11, 12, 16, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="timezone"):
        parse_time("2026-11-12T16:00:00")


def test_triage_completion_is_first_recorded_time(routine, config):
    change_status(routine, "Triaged", config)
    first = routine["events"]["triaged_at"]
    assert clock_by_id(routine, config, "initial_triage")["met"] is True
    config["demo_now"] = "2026-11-13T16:00:00Z"
    change_status(routine, "Contained", config)
    assert routine["events"]["triaged_at"] == first
    assert clock_by_id(routine, config, "follow_up")["deadline"] == "2026-11-17T16:00:00Z"


def test_closed_stops_outstanding_clocks_without_inventing_completion(routine, config):
    change_status(routine, "Closed", config)
    assert next_clock(routine, config) is None
    assert clock_by_id(routine, config, "initial_triage")["status"] == "Stopped (closed)"
    assert "triaged_at" not in routine["events"]


def test_deletion_clock_starts_only_after_approval(routine, config):
    assert clock_by_id(routine, config, "deletion_attestation")["status"] == "Not started"
    generate_draft(routine, "deletion", config)
    assert clock_by_id(routine, config, "deletion_attestation")["status"] == "Not started"
    save_draft(routine, "deletion", routine["drafts"]["deletion"]["text"], True, config)
    assert clock_by_id(routine, config, "deletion_attestation")["deadline"] == "2026-11-13T16:00:00Z"
    assert "stakeholder_update_recorded_at" not in routine["events"]


def test_approval_is_not_manual_update_completion(routine, config):
    generate_draft(routine, "status", config)
    save_draft(routine, "status", routine["drafts"]["status"]["text"], True, config)
    assert clock_by_id(routine, config, "stakeholder_update")["status"] == "OK"
    record_completion(routine, "stakeholder_update_recorded_at", config)
    assert clock_by_id(routine, config, "stakeholder_update")["status"] == "Completed"
    with pytest.raises(ValueError, match="not started"):
        record_completion(routine, "follow_up_recorded_at", config)


def test_deletion_approval_invalidates_status_context(routine, config):
    generate_draft(routine, "status", config)
    save_draft(routine, "status", routine["drafts"]["status"]["text"], True, config)
    generate_draft(routine, "deletion", config)
    save_draft(routine, "deletion", routine["drafts"]["deletion"]["text"], True, config)
    assert routine["drafts"]["status"]["status"] == "Needs regeneration"
    assert routine["drafts"]["deletion"]["status"] == config["drafts"]["approved_label"]


def test_reporter_checklist_is_audited_but_not_a_fact_confirmation(config, seeds):
    incident = initialize_incident(seeds[2], config)
    record_question(incident, "record_count", True, config)
    assert incident["questions_asked"]["record_count"] is True
    assert incident["facts"]["record_count"]["label"] == "UNKNOWN"
    assert incident["audit"][-1]["after"] is True


def test_override_requires_reason_and_is_audited(routine, config):
    with pytest.raises(ValueError, match="reason"):
        record_decision(routine, "severity", "P1", True, "", config)
    record_decision(routine, "severity", "P1", True, "Escalating for accountable owner review.", config)
    assert routine["routing"]["lane"] == "FTE-owned"
    event = next(event for event in routine["audit"] if event["action"] == "severity override")
    assert event["after"]["reason"] == "Escalating for accountable owner review."
    assert event["actor"] == "PM"
    assert event["before"] is None


def test_accept_does_not_allow_different_value(routine, config):
    with pytest.raises(ValueError, match="Accept"):
        record_decision(routine, "severity", "P1", False, "", config)


def test_fact_edits_revoke_stale_approval_and_decisions(routine, config):
    config["severity"]["containment_reduction"] = 0
    record_decision(routine, "severity", "P3", False, "", config)
    generate_draft(routine, "status", config)
    save_draft(routine, "status", routine["drafts"]["status"]["text"], True, config)
    edit_fact(routine, "record_count", 2000, "Reporter verified source export.", config)
    assert routine["facts"]["record_count"]["label"] == "CONFIRMED (by PM)"
    assert routine["decisions"] == {}
    assert routine["drafts"]["status"]["status"] == "Needs regeneration"
    assert routine["drafts"]["status"]["approved_at"] is None
    with pytest.raises(ValueError, match="Regenerate"):
        save_draft(routine, "status", routine["drafts"]["status"]["text"], True, config)
    assert routine["severity"]["severity"] == "P2"


@pytest.mark.parametrize(("key", "value"), [
    ("record_count", -1), ("record_count", True), ("contained", "yes"),
    ("customers", []), ("how_happened", ""),
])
def test_invalid_manual_facts_rejected(routine, config, key, value):
    with pytest.raises(ValueError):
        edit_fact(routine, key, value, "Reporter evidence.", config)


def test_status_draft_uses_facts_not_raw_indicators(config, seeds):
    incident = initialize_incident(seeds[8], config)
    text = suggest_draft("status", incident, config)
    assert "suspected insider misuse" not in text
    assert "CONFIRMED FACTS" in text
    assert "UNKNOWNS / QUESTIONS" in text
    assert "Containment confirmed: UNKNOWN" in text


@pytest.mark.parametrize("text", [
    "The customer might be affected.",
    "Notification is required.",
    "No notification is required.",
    "This is legally notifiable under GDPR.",
])
def test_speculative_and_legal_status_edits_blocked(routine, config, text):
    generate_draft(routine, "status", config)
    with pytest.raises(ValueError, match="speculative"):
        save_draft(routine, "status", text, True, config)


def test_draft_edit_clears_approval(routine, config):
    generate_draft(routine, "deletion", config)
    text = routine["drafts"]["deletion"]["text"]
    save_draft(routine, "deletion", text, True, config)
    save_draft(routine, "deletion", text + "\nPM reviewed recipient identity.", False, config)
    assert routine["drafts"]["deletion"]["approved_at"] is None
    assert routine["drafts"]["deletion"]["status"] == "Draft"


def test_status_change_preserves_independent_deletion_but_invalidates_status_draft(routine, config):
    generate_draft(routine, "deletion", config)
    save_draft(routine, "deletion", routine["drafts"]["deletion"]["text"], True, config)
    generate_draft(routine, "status", config)
    save_draft(routine, "status", routine["drafts"]["status"]["text"], True, config)
    deletion = deepcopy(routine["drafts"]["deletion"])
    change_status(routine, "Contained", config)
    assert routine["drafts"]["deletion"] == deletion
    assert routine["drafts"]["status"]["status"] == "Needs regeneration"
    assert routine["drafts"]["status"]["approved_at"] is None


def test_status_dependent_deletion_template_still_loses_approval(routine, config):
    config["drafts"]["deletion"]["template"] += "\nWorkflow context:\n{actions}"
    generate_draft(routine, "deletion", config)
    save_draft(routine, "deletion", routine["drafts"]["deletion"]["text"], True, config)
    change_status(routine, "Contained", config)
    assert routine["drafts"]["deletion"]["status"] == "Needs regeneration"
    assert routine["drafts"]["deletion"]["approved_at"] is None


def test_export_contains_approved_drafts_only_and_case_links(routine, config):
    generate_draft(routine, "deletion", config)
    text = routine["drafts"]["deletion"]["text"]
    summary = export_summary(routine, config)
    section = summary.split("APPROVED DRAFTS")[1].split("AUDIT SUMMARY")[0]
    assert text not in section
    assert text not in summary
    save_draft(routine, "deletion", text, True, config)
    summary = export_summary(routine, config)
    assert text in summary.split("APPROVED DRAFTS")[1]
    assert "ICM-DEMO-1001" in summary and "CASE-DEMO-2001" in summary
    assert "Pending PM review" in summary


def test_audit_history_snapshots_and_csv(routine, config):
    before = deepcopy(routine["audit"][0]["after"])
    edit_fact(routine, "customers", ["New fictional customer"], "Reporter confirmation.", config)
    assert routine["audit"][0]["after"] == before
    output = audit_csv(routine)
    assert output.startswith("timestamp,actor,action,before,after")
    assert "fact edit: customers" in output


def test_state_roundtrip_and_config_change_not_silently_applied(tmp_path, routine, config):
    path = tmp_path / "state.json"
    persist_state([routine], path, config)
    assert load_state(ROOT / "data" / "incidents.json", path, config) == [routine]
    config["severity"]["large_record_count"] += 1
    with pytest.raises(ValueError, match="Configuration changed"):
        load_state(ROOT / "data" / "incidents.json", path, config)


def test_corrupt_state_not_silently_reset(tmp_path, config):
    path = tmp_path / "state.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError):
        load_state(ROOT / "data" / "incidents.json", path, config)
    assert path.read_text(encoding="utf-8") == "{"


def test_no_delivery_transport_or_function_in_application_code():
    forbidden_imports = {
        "requests", "httpx", "http", "urllib", "urllib3", "aiohttp", "socket",
        "smtplib", "imaplib", "poplib", "ftplib", "websocket", "websockets",
        "subprocess", "boto3", "grpc", "paramiko", "xmlrpc",
    }
    for path in [ROOT / "app.py", *(ROOT / "engine").glob("*.py")]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name not in {"send", "send_message", "send_email", "deliver"}
            if isinstance(node, ast.Import):
                assert not {alias.name.split(".")[0] for alias in node.names} & forbidden_imports
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_imports


@pytest.fixture
def ui_app(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    import engine.state as state
    original_load = state.load_state
    original_persist = state.persist_state
    local_path = tmp_path / "state.json"
    monkeypatch.setattr(state, "load_state", lambda seed, path, config: original_load(seed, local_path, config))
    monkeypatch.setattr(state, "persist_state", lambda incidents, path, config: original_persist(incidents, local_path, config))
    return AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)


def test_streamlit_four_tabs_and_incident_selection(ui_app):
    assert not ui_app.exception
    assert [tab.label for tab in ui_app.tabs] == ["Overview", "Queue", "Incident", "Dashboard"]
    assert "synthetic data only" in ui_app.warning[0].value
    ui_app.selectbox(key="selected_incident").select("TG-DEMO-002").run()
    assert not ui_app.exception
    assert ui_app.session_state["incidents"][8]["severity"]["severity"] == "P1"
    headings = [heading.value for heading in ui_app.subheader]
    assert headings.index("What we know") < headings.index("What has been done") < headings.index("Recommended next actions (suggestions – PM approves)")
    assert any(expander.label == "Privacy lens vs. engineering lens" for expander in ui_app.expander)
    assert any("not applicable / not run" in item.value for item in ui_app.markdown)


def test_streamlit_fact_confirmation_and_draft_approval(ui_app):
    ui_app.selectbox(key="selected_incident").select("TG-DEMO-019").run()
    next(widget for widget in ui_app.text_input if widget.label == "Confirmed value (comma-separated for lists)").set_value("contact details")
    next(widget for widget in ui_app.text_input if widget.label == "Source / confirmation note (required)").set_value("Synthetic reporter verified the file schema.")
    next(widget for widget in ui_app.checkbox if widget.label.startswith("I verified this answer")).check()
    next(button for button in ui_app.button if button.label == "Save confirmed fact").click().run()
    assert not ui_app.exception
    assert ui_app.session_state["incidents"][2]["facts"]["data_types"]["label"] == "CONFIRMED (by PM)"
    ui_app.button(key="generate_TG-DEMO-019_deletion").click().run()
    next(widget for widget in ui_app.checkbox if widget.label.startswith("I reviewed this text")).check()
    next(button for button in ui_app.button if button.label.startswith("Approve —")).click().run()
    assert not ui_app.exception
    assert ui_app.session_state["incidents"][2]["drafts"]["deletion"]["approved_at"]
    assert "deletion_request_approved_at" in ui_app.session_state["incidents"][2]["events"]


def test_streamlit_purview_decisions_handoff_approval_and_export(ui_app):
    ui_app.selectbox(key="selected_incident").select("TG-DEMO-003").run()
    assert not ui_app.exception
    for kind in ("purview", "receiving_team"):
        next(
            button for button in ui_app.button
            if f"decision_TG-DEMO-003_{kind}_" in str(button.key)
        ).click().run()
        assert not ui_app.exception
    ui_app.button(key="generate_TG-DEMO-003_handoff").click().run()
    next(widget for widget in ui_app.checkbox if widget.label.startswith("I reviewed this text")).check()
    next(button for button in ui_app.button if button.label.startswith("Approve —")).click().run()
    assert not ui_app.exception
    incident = ui_app.session_state["incidents"][18]
    assert incident["drafts"]["handoff"]["approved_at"]
    assert incident["status"] == "New" and incident["events"] == {}
    ui_app.button(key="export_TG-DEMO-003").click().run()
    assert not ui_app.exception
    text = ui_app.session_state["export_snapshot"]["text"]
    assert "Demo Sandbox Engineering" in text
    assert "PRIVACY PURVIEW HANDOFF / CLOSURE NOTE" in text
    assert "Rule fired: Plan §1.2" in text
    assert any("Relevant lens: engineering security-process review" in item.value for item in ui_app.info)
    assert any("engineering-owned check" in item.value for item in ui_app.markdown)


def test_three_demo_paths_are_pinned_before_deadline_order_even_when_contained(config):
    incidents = load_seed(ROOT / "data" / "incidents.json", config)
    routine = next(item for item in incidents if item["id"] == "TG-DEMO-001")
    change_status(routine, "Contained", config)
    ordered = order_incidents(incidents, config)
    assert [item["id"] for item in ordered[:3]] == ["TG-DEMO-001", "TG-DEMO-002", "TG-DEMO-003"]
    deadlines = [(next_clock(item, config) or {}).get("deadline") or "9999" for item in ordered[3:]]
    assert deadlines == sorted(deadlines)
    config["demo"]["pinned_incident_ids"] = ["TG-DEMO-003", "TG-DEMO-001"]
    assert [item["id"] for item in order_incidents(incidents, config)[:2]] == ["TG-DEMO-003", "TG-DEMO-001"]


def test_streamlit_demo_queue_and_selector_start_with_three_paths(ui_app):
    expected = ["TG-DEMO-001", "TG-DEMO-002", "TG-DEMO-003"]
    table = next(frame.value for frame in ui_app.table if "Next due (UTC)" in frame.value.columns)
    assert table["ID"].tolist()[:3] == expected
    assert ui_app.selectbox(key="selected_incident").options[:3] == expected


def test_tg_demo_002_is_in_scope_insider_escalation_with_unknowns(config):
    incident = next(item for item in load_seed(ROOT / "data" / "incidents.json", config) if item["id"] == "TG-DEMO-002")
    assert incident["purview"]["status"] == "In scope"
    assert incident["severity"]["severity"] == config["severity"]["highest"]
    assert any("Plan §3.2" in reason for reason in incident["severity"]["rationale"])
    assert incident["routing"]["lane"] == config["routing"]["fte_lane"]
    assert all(reason.startswith("Rule fired: Plan §") for reason in incident["routing"]["rationale"])
    stakeholders = {item["name"]: item["reason"] for item in incident["stakeholders"]}
    assert {"Privacy", "Legal", "Security"} <= stakeholders.keys()
    assert all(reason.startswith("Rule fired: Plan §5.1") for reason in stakeholders.values())
    assert any(clock["status"] in ("At risk", "Breached") for clock in calculate_clocks(incident, config))
    unknowns = [key for key, fact in incident["facts"].items() if fact["label"] == "UNKNOWN"]
    assert {"regions", "record_count", "contained", "deletion_attested"} <= set(unknowns)
    text = suggest_draft("status", incident, config)
    unknown_section = text.split("UNKNOWNS / QUESTIONS")[1].split("ACTIONS RECORDED")[0]
    assert all(f"{config['facts'][key]}: UNKNOWN" in unknown_section for key in unknowns)
    assert "suspected insider misuse" not in text.lower()


def test_streamlit_tg_demo_002_escalation_and_facts_only_status(ui_app):
    ui_app.selectbox(key="selected_incident").select("TG-DEMO-002").run()
    assert not ui_app.exception and not ui_app.error
    assert any(expander.label == "Why this was escalated" for expander in ui_app.expander)
    ui_app.button(key="generate_TG-DEMO-002_status").click().run()
    assert not ui_app.exception and not ui_app.error
    text = next(widget.value for widget in ui_app.text_area if widget.label == "Draft text")
    assert "Regions affected: UNKNOWN" in text
    assert "Approximate record count: UNKNOWN" in text
    assert "Containment confirmed: UNKNOWN" in text
    assert "Recipient confirmed deletion: UNKNOWN" in text
    assert "suspected insider misuse" not in text.lower()


def test_tg_demo_001_happy_path_preserves_approved_deletion_in_export(ui_app, tmp_path):
    """Rehearse the interview sequence through actual Streamlit form submissions."""
    assert ui_app.selectbox(key="selected_incident").value == "TG-DEMO-001"
    incident = ui_app.session_state["incidents"][0]
    assert incident["purview"]["status"] == "In scope"
    assert all(reason.startswith("Rule fired: Plan §") for reason in incident["purview"]["rationale"])
    facts_table = next(frame.value for frame in ui_app.table if "Evidence label" in frame.value.columns)
    assert {"CONFIRMED", "UNKNOWN"} <= set(facts_table["Evidence label"])
    assert incident["facts"]["privacy_data_involved"]["label"] == "UNKNOWN"

    ui_app.selectbox(key="fact_field_TG-DEMO-001").select("privacy_data_involved").run()
    next(widget for widget in ui_app.selectbox if widget.label == "Explicit answer").select("Yes")
    next(widget for widget in ui_app.text_input if widget.label == "Source / confirmation note (required)").set_value("Synthetic reporter confirmed customer contact details.")
    next(widget for widget in ui_app.checkbox if widget.label.startswith("I verified this answer")).check()
    next(button for button in ui_app.button if button.label == "Save confirmed fact").click().run()
    assert not ui_app.exception and not ui_app.error
    assert ui_app.session_state["incidents"][0]["facts"]["privacy_data_involved"]["label"] == "CONFIRMED (by PM)"

    for kind in ("severity", "routing"):
        incident = ui_app.session_state["incidents"][0]
        assert all(reason.startswith("Rule fired: Plan §") for reason in incident[kind]["rationale"])
        next(button for button in ui_app.button if f"decision_TG-DEMO-001_{kind}_" in str(button.key)).click().run()
        assert not ui_app.exception and not ui_app.error
    assert ui_app.session_state["incidents"][0]["decisions"]["routing"]["value"] == "Vendor-supported routine queue"
    assert any(expander.label == "Privacy lens vs. engineering lens" for expander in ui_app.expander)
    assert any("not applicable / not run" in item.value for item in ui_app.markdown)

    ui_app.button(key="generate_TG-DEMO-001_deletion").click().run()
    assert not ui_app.exception and not ui_app.error
    draft = next(widget for widget in ui_app.text_area if widget.label == "Draft text")
    edited = draft.value + "\nPlease reference TG-DEMO-001 in your response."
    draft.set_value(edited)
    next(widget for widget in ui_app.text_input if widget.label == "Reason for template edits (required if edited)").set_value("Add the synthetic incident reference for manual coordination.")
    next(button for button in ui_app.button if button.label == "Save edited draft").click().run()
    assert not ui_app.exception and not ui_app.error
    next(widget for widget in ui_app.checkbox if widget.label.startswith("I reviewed this text")).check()
    next(button for button in ui_app.button if button.label.startswith("Approve —")).click().run()
    assert not ui_app.exception and not ui_app.error
    assert ui_app.session_state["incidents"][0]["drafts"]["deletion"]["approved_at"]

    next(widget for widget in ui_app.selectbox if widget.label == "PM workflow status").select("Contained")
    next(button for button in ui_app.button if button.label == "Record status change").click().run()
    assert not ui_app.exception and not ui_app.error
    assert any("Recorded workflow status:" in item.value and "Contained" in item.value for item in ui_app.markdown)
    assert any("status change" in item.value for item in ui_app.markdown)

    ui_app.button(key="export_TG-DEMO-001").click().run()
    assert not ui_app.exception and not ui_app.error
    summary = ui_app.session_state["export_snapshot"]["text"]
    assert "Status (PM workflow): Contained" in summary
    assert edited in summary.split("APPROVED DRAFTS")[1].split("AUDIT SUMMARY")[0]
    assert "ICM-DEMO-1001" in summary and "CASE-DEMO-2001" in summary
    incident = ui_app.session_state["incidents"][0]
    actions = [event["action"] for event in incident["audit"]]
    expected = [
        "extraction", "purview suggestion", "severity suggestion", "routing suggestion",
        "fact edit: privacy_data_involved", "severity acceptance", "routing acceptance",
        "deletion draft generated", "deletion draft edit", "deletion template override reason",
        "deletion draft approval", "status change", "export summary prepared",
    ]
    positions = [actions.index(action) for action in expected]
    assert positions == sorted(positions)
    assert all(action in summary for action in expected)
    saved = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["incidents"][0]
    assert saved == incident
    assert saved["drafts"]["deletion"]["approved_at"]
    assert saved["drafts"]["deletion"]["text"] == edited


def test_streamlit_reset_restores_all_seeds_forms_and_persisted_state(ui_app, config, tmp_path):
    from streamlit.testing.v1 import AppTest

    incidents = deepcopy(ui_app.session_state["incidents"])
    routine = incidents[0]
    edit_fact(routine, "privacy_data_involved", True, "Synthetic reporter verified the customer data.", config)
    record_question(routine, "environment", True, config)
    record_decision(routine, "severity", routine["severity"]["severity"], False, "", config)
    generate_draft(routine, "deletion", config)
    save_draft(routine, "deletion", routine["drafts"]["deletion"]["text"], True, config)
    change_status(routine, "Contained", config)
    generate_draft(incidents[8], "status", config)
    persist_state(incidents, tmp_path / "state.json", config)
    ui_app.session_state["incidents"] = incidents
    ui_app.session_state["export_snapshot"] = {"id": routine["id"], "text": export_summary(routine, config)}
    ui_app.selectbox(key="selected_incident").select("TG-DEMO-003").run()
    next(widget for widget in ui_app.text_input if widget.label == "Source / confirmation note (required)").set_value("Unsaved source note").run()
    assert ui_app.button(key="reset_demo").disabled
    ui_app.checkbox(key="confirm_reset").check().run()
    ui_app.button(key="reset_demo").click().run()

    expected = load_seed(ROOT / "data" / "incidents.json", config)
    assert not ui_app.exception and not ui_app.error
    assert ui_app.session_state["incidents"] == expected
    assert "export_snapshot" not in ui_app.session_state
    assert ui_app.selectbox(key="selected_incident").value == "TG-DEMO-001"
    assert not ui_app.checkbox(key="confirm_reset").value
    assert next(widget for widget in ui_app.text_input if widget.label == "Source / confirmation note (required)").value == ""
    assert load_state(ROOT / "data" / "incidents.json", tmp_path / "state.json", config) == expected
    reloaded = AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)
    assert not reloaded.exception and not reloaded.error
    assert reloaded.session_state["incidents"] == expected


def test_streamlit_failed_reset_preserves_saved_and_session_state(ui_app, monkeypatch, tmp_path):
    original = deepcopy(ui_app.session_state["incidents"])
    before = (tmp_path / "state.json").read_bytes()
    ui_app.session_state["export_snapshot"] = {"id": "TG-DEMO-001", "text": "Preserve this snapshot"}
    ui_app.checkbox(key="confirm_reset").check().run()

    def fail_persist(*args):
        raise OSError("Synthetic disk-write failure")

    monkeypatch.setattr("engine.state.persist_state", fail_persist)
    ui_app.button(key="reset_demo").click().run()
    assert not ui_app.exception
    assert any("Reset failed: Synthetic disk-write failure" in error.value for error in ui_app.error)
    assert ui_app.session_state["incidents"] == original
    assert ui_app.session_state["export_snapshot"]["text"] == "Preserve this snapshot"
    assert (tmp_path / "state.json").read_bytes() == before


def test_streamlit_overview_opens_the_actual_privacy_plan(ui_app):
    plan = next(expander for expander in ui_app.expander if expander.label.startswith("Open privacy response plan"))
    assert r"docs\privacy-response-plan.md" in plan.label
    assert any(
        item.value.strip() == (ROOT / "docs" / "privacy-response-plan.md").read_text(encoding="utf-8").strip()
        for item in plan.markdown
    )


def test_synthetic_fixture_identifiers_and_narratives(seeds):
    for seed in seeds:
        assert re.fullmatch(r"TG-DEMO-\d{3}", seed["id"])
        for field, prefix in (("linked_icm_id", "ICM-DEMO"), ("linked_case_id", "CASE-DEMO")):
            assert seed[field] == "" or re.fullmatch(rf"{prefix}-\d{{4}}", seed[field])
        assert "fictional" in seed["raw_description"].lower()
        assert not re.search(r"https?://|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", json.dumps(seed))


def test_engine_workflows_run_with_outbound_network_denied(monkeypatch, tmp_path):
    import socket

    def blocked(*args, **kwargs):
        pytest.fail("A local-only workflow attempted a network connection or DNS lookup.")

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, blocked)
    for name in ("create_connection", "getaddrinfo", "gethostbyname"):
        monkeypatch.setattr(socket, name, blocked)
    config = load_config(ROOT / "config.yaml")
    incidents = load_seed(ROOT / "data" / "incidents.json", config)
    for incident in incidents:
        for kind in ("deletion", "status"):
            generate_draft(incident, kind, config)
            save_draft(incident, kind, incident["drafts"][kind]["text"], True, config)
        if incident["purview"]["status"] == config["purview"]["out_of_scope_label"]:
            approve_handoff(incident, config)
        change_status(incident, "Contained", config)
        assert export_summary(incident, config)
        assert audit_csv(incident)
    path = tmp_path / "offline-state.json"
    persist_state(incidents, path, config)
    assert load_state(ROOT / "data" / "incidents.json", path, config) == incidents


def test_streamlit_browsing_and_unsubmitted_forms_apply_nothing(ui_app, tmp_path):
    original = deepcopy(ui_app.session_state["incidents"])
    saved = (tmp_path / "state.json").read_bytes()
    assert all(
        incident["decisions"] == {} and incident["drafts"] == {}
        and incident["events"] == {} and incident["status"] == "New"
        for incident in original
    )
    for incident_id in ("TG-DEMO-002", "TG-DEMO-003", "TG-DEMO-001"):
        ui_app.selectbox(key="selected_incident").select(incident_id).run()
        assert not ui_app.exception and not ui_app.error
    next(widget for widget in ui_app.radio if widget.label == "PM decision").set_value("Override")
    next(widget for widget in ui_app.selectbox if widget.label == "Override value").select("Needs review")
    next(widget for widget in ui_app.selectbox if widget.label == "PM workflow status").select("Closed")
    next(widget for widget in ui_app.text_input if widget.label == "Source / confirmation note (required)").set_value("Unsubmitted synthetic note")
    ui_app.run()
    assert not ui_app.exception and not ui_app.error
    assert ui_app.session_state["incidents"] == original
    assert (tmp_path / "state.json").read_bytes() == saved


def test_streamlit_draft_requires_generation_and_approval_clicks(ui_app):
    assert ui_app.session_state["incidents"][0]["drafts"] == {}
    ui_app.button(key="generate_TG-DEMO-001_deletion").click().run()
    draft = deepcopy(ui_app.session_state["incidents"][0]["drafts"]["deletion"])
    assert draft["status"] == "Draft" and draft["approved_at"] is None
    next(button for button in ui_app.button if button.label.startswith("Approve —")).click().run()
    assert not ui_app.exception
    assert any("Review and confirm approval" in error.value for error in ui_app.error)
    assert ui_app.session_state["incidents"][0]["drafts"]["deletion"] == draft
    next(widget for widget in ui_app.checkbox if widget.label.startswith("I reviewed this text")).check().run()
    assert ui_app.session_state["incidents"][0]["drafts"]["deletion"] == draft
    assert ui_app.session_state["incidents"][0]["events"] == {}
    next(widget for widget in ui_app.checkbox if widget.label.startswith("I reviewed this text")).check()
    next(button for button in ui_app.button if button.label.startswith("Approve —")).click().run()
    assert not ui_app.exception and not ui_app.error
    assert ui_app.session_state["incidents"][0]["drafts"]["deletion"]["approved_at"]


def test_safety_banner_is_global_and_policy_labels_cover_each_tab(ui_app, config):
    root_warnings = [item.value for item in ui_app.main.children.values() if item.type == "warning"]
    assert config["banner"] in root_warnings
    for tab in ui_app.tabs:
        assert all(warning.value != config["banner"] for warning in tab.warning)
        assert any(config["clock_policy_label"] in item.value for item in tab.caption)


def test_plan_clocks_drafts_and_exports_carry_policy_disclaimer(routine, config):
    label = "illustrative – configure to policy"
    assert label in (ROOT / "docs" / "privacy-response-plan.md").read_text(encoding="utf-8")
    assert all(label in clock["rationale"] for clock in calculate_clocks(routine, config))
    assert label in next(line for line in suggest_draft("status", routine, config).splitlines() if line.startswith("Next update time:"))
    assert label in next(line for line in export_summary(routine, config).splitlines() if line.startswith("Response plan:"))
