"""Conservative routine eligibility and explainable stakeholder suggestions."""

from engine.extract import confirmed, keyword_matches
from engine.models import Config, Fact, Routing, Stakeholder
from engine.plan import plan_rationale


def suggest_routing(
    text: str, facts: dict[str, Fact], severity: str, config: Config,
    purview_status: str | None = None,
) -> Routing:
    """Keep ambiguous, sensitive, or escalated cases with FTEs."""
    rules = config["routing"]
    if purview_status == config["purview"]["out_of_scope_label"]:
        return {
            "lane": rules["handoff_lane"],
            "rationale": [plan_rationale(config, "routing_handoff", "Out-of-scope purview: coordinate a PM-approved engineering handoff, not routine privacy processing.")],
        }
    reasons = [
        plan_rationale(config, "routing_escalation", reason) for keyword, reason in rules["fte_keywords"].items()
        if keyword_matches(text, keyword, config)
    ]
    if severity in rules["high_severities"]:
        reasons.append(plan_rationale(config, "routing_escalation", f"Severity {severity} meets the configured FTE escalation rule."))
    types = confirmed(facts, "data_types")
    if isinstance(types, list) and set(types).intersection(config["severity"]["sensitive_data_types"]):
        reasons.append(plan_rationale(config, "routing_escalation", "Explicit sensitive data type is not eligible for the routine queue."))
    if purview_status == config["purview"]["review_label"]:
        reasons.append(plan_rationale(config, "purview_review", "Purview needs review; retain accountable FTE ownership."))
    unknowns = sum(facts[key]["label"] == "UNKNOWN" for key in rules["core_fact_fields"])
    if unknowns > rules["max_routine_unknowns"]:
        reasons.append(plan_rationale(config, "routing_routine", f"{unknowns} UNKNOWN core facts exceed the routine threshold of {rules['max_routine_unknowns']}."))
    count = confirmed(facts, "record_count")
    routine = (
        keyword_matches(text, "routine", config)
        and confirmed(facts, "contained") is True
        and isinstance(types, list)
        and bool(types)
        and isinstance(count, int)
        and count <= rules["max_routine_records"]
        and unknowns <= rules["max_routine_unknowns"]
    )
    if not reasons and routine:
        return {"lane": rules["routine_lane"], "rationale": [plan_rationale(config, "routing_routine", rules["routine_reason"])]}
    return {"lane": rules["fte_lane"], "rationale": reasons or [plan_rationale(config, "routing_routine", rules["fallback_reason"])]}


def suggest_stakeholders(text: str, facts: dict[str, Fact], config: Config) -> list[Stakeholder]:
    """Explain why each configured stakeholder is suggested."""
    types = confirmed(facts, "data_types")
    sensitive = isinstance(types, list) and bool(
        set(types).intersection(config["severity"]["sensitive_data_types"])
    )
    result: list[Stakeholder] = []
    for rule in config["stakeholders"]:
        applicable = (
            rule.get("always", False)
            or any(keyword_matches(text, key, config) for key in rule.get("keywords", []))
            or (rule.get("sensitive", False) and sensitive)
            or (rule.get("customer_known", False) and confirmed(facts, "customers") is not None)
        )
        if applicable:
            result.append({"name": rule["name"], "reason": plan_rationale(config, "stakeholders", rule["reason"])})
    return result
