"""Conservative, evidence-backed privacy purview suggestions."""

import re

from engine.extract import confirmed, keyword_matches
from engine.models import Config, Decision, Fact, Purview
from engine.plan import plan_rationale


def suggest_purview(text: str, facts: dict[str, Fact], config: Config) -> Purview:
    """Exclude engineering-only concerns only when every required fact is explicit."""
    rules = config["purview"]
    types = confirmed(facts, "data_types")
    privacy_types = set(rules["privacy_data_types"])
    declared_privacy = confirmed(facts, "privacy_data_involved")
    process_only = confirmed(facts, "security_process_only")
    private_fact = isinstance(types, list) and bool(set(types).intersection(privacy_types))
    private_report = any(
        re.search(pattern, text, re.IGNORECASE)
        for name in privacy_types for pattern in config["extraction"]["data_types"][name]
    )
    protected_indicator = any(keyword_matches(text, key, config) for key in rules["blocking_keywords"])
    exclusion_claim = declared_privacy is False or process_only is True
    evidence_conflict = any("conflict" in fact["evidence"].lower() for fact in facts.values())
    if evidence_conflict or (exclusion_claim and (
        declared_privacy is True or private_fact or private_report or protected_indicator
    )):
        return {
            "status": rules["review_label"], "receiving_team": None,
            "rationale": [plan_rationale(config, "purview_review", rules["conflict_reason"])],
        }
    if declared_privacy is True or private_fact:
        return {
            "status": rules["in_scope_label"], "receiving_team": None,
            "rationale": [plan_rationale(config, "purview_in", rules["in_scope_reason"])],
        }
    environment = confirmed(facts, "environment")
    receiving_team = rules["receiving_teams"].get(environment) if isinstance(environment, str) else None
    excluded = (
        declared_privacy is False and process_only is True
        and receiving_team is not None
        and isinstance(types, list) and bool(types)
        and set(types).issubset(rules["exclusion_data_types"])
        and confirmed(facts, "record_count") == rules["exclusion_record_count"]
        and not private_report and not protected_indicator
    )
    if excluded:
        return {
            "status": rules["out_of_scope_label"], "receiving_team": receiving_team,
            "rationale": [
                plan_rationale(config, "purview_out", rules["out_of_scope_reason"]),
                plan_rationale(config, "routing_handoff", f"Suggested receiving team: {receiving_team}; PM must coordinate acceptance."),
            ],
        }
    return {
        "status": rules["review_label"], "receiving_team": None,
        "rationale": [plan_rationale(config, "purview_review", rules["review_reason"])],
    }


def handoff_team(incident_purview: Purview, decisions: dict[str, Decision], config: Config) -> str:
    """Require evidence-backed exclusion and honor a PM's receiving-team decision."""
    purview_decision = decisions.get("purview")
    status = purview_decision["value"] if purview_decision else incident_purview["status"]
    if incident_purview["status"] != config["purview"]["out_of_scope_label"] or status != config["purview"]["out_of_scope_label"]:
        raise ValueError("A handoff requires confirmed out-of-scope evidence and no conflicting PM purview decision.")
    team_decision = decisions.get("receiving_team")
    team = team_decision["value"] if team_decision else incident_purview["receiving_team"]
    if not isinstance(team, str) or team not in config["purview"]["receiving_teams"].values():
        raise ValueError("A configured receiving team is required for a handoff.")
    return team
