"""Explainable provisional severity, never a legal determination."""

from engine.extract import confirmed, keyword_matches
from engine.models import Config, Fact, Severity
from engine.plan import plan_rationale


def suggest_severity(text: str, facts: dict[str, Fact], config: Config) -> Severity:
    """Apply configured severity rules; high-risk indicators cannot be reduced."""
    rules = config["severity"]
    levels: list[str] = rules["levels"]
    rank = levels.index(rules["default"])
    reasons: list[str] = []
    indicator_rank: int | None = None
    for rule in rules["indicator_rules"]:
        if keyword_matches(text, rule["keyword"], config):
            hit = levels.index(rule["severity"])
            indicator_rank = hit if indicator_rank is None else min(indicator_rank, hit)
            rank = min(rank, hit)
            reasons.append(plan_rationale(config, "severity_indicator", rule["reason"]))
    types = confirmed(facts, "data_types")
    if isinstance(types, list) and set(types).intersection(rules["sensitive_data_types"]):
        rank = min(rank, levels.index(rules["elevated"]))
        reasons.append(plan_rationale(config, "severity_elevation", "Explicit sensitive data type meets the configured elevation rule."))
    count = confirmed(facts, "record_count")
    if isinstance(count, int) and count >= rules["large_record_count"]:
        rank = min(rank, levels.index(rules["elevated"]))
        reasons.append(plan_rationale(config, "severity_elevation", f"Record count meets the {rules['large_record_count']:,}-record threshold."))
    if confirmed(facts, "contained") is True and confirmed(facts, "deletion_attested") is True:
        rank = min(len(levels) - 1, rank + rules["containment_reduction"])
        if indicator_rank is not None:
            rank = min(rank, indicator_rank)
        reasons.append(plan_rationale(config, "severity_containment", rules["containment_reason"]))
        if indicator_rank is not None:
            reasons.append(plan_rationale(config, "severity_indicator", "Attack/insider severity floor is retained despite containment."))
    closure = keyword_matches(text, "not_incident", config)
    if closure:
        reasons.append(plan_rationale(config, "severity_closure", rules["closure_reason"]))
    if not reasons:
        reasons.append(plan_rationale(config, "severity_baseline", f"Configured baseline {rules['default']}; no elevation rule fired."))
    return {"severity": levels[rank], "rationale": reasons, "closure_suggested": closure}
