"""Trace local rule output to the illustrative response plan."""

from engine.models import Config


def response_plan_path(config: Config) -> str:
    """Accept Windows or POSIX separators without changing the saved configuration."""
    return config["response_plan"]["path"].replace("\\", "/")


def plan_rationale(config: Config, rule: str, message: str) -> str:
    """Prefix a rule explanation with its configured response-plan section."""
    section = config["response_plan"]["rules"][rule]
    return f"Rule fired: Plan §{section} — {message}"
