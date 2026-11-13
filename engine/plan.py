"""Trace local rule output to the illustrative response plan."""

from engine.models import Config


def plan_rationale(config: Config, rule: str, message: str) -> str:
    """Prefix a rule explanation with its configured response-plan section."""
    section = config["response_plan"]["rules"][rule]
    return f"Rule fired: Plan §{section} — {message}"
