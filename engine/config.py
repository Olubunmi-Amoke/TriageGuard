"""Read the demo's explicit, local policy configuration."""

from pathlib import Path
import re

import yaml

from engine.clocks import parse_time
from engine.models import Config
from engine.plan import response_plan_path


def load_config(path: Path) -> Config:
    """Load YAML and reject ambiguous clock or severity settings."""
    with path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError("config.yaml must contain a mapping.")
    parse_time(config["demo_now"])
    plan_path = path.parent / response_plan_path(config)
    plan_text = plan_path.read_text(encoding="utf-8")
    sections = set(re.findall(r"^### (\d+\.\d+)\b", plan_text, re.MULTILINE))
    for rule, section in config["response_plan"]["rules"].items():
        if section not in sections:
            raise ValueError(f"Rule {rule} references missing response-plan section {section}.")
    levels = config["severity"]["levels"]
    if len(set(levels)) != len(levels) or not levels:
        raise ValueError("Severity levels must be unique, highest first.")
    if not 0 < config["clocks"]["at_risk_fraction"] < 1:
        raise ValueError("At-risk fraction must be between zero and one.")
    clock_ids: set[str] = set()
    for rule in config["clocks"]["rules"]:
        if rule["id"] in clock_ids:
            raise ValueError("Clock IDs must be unique.")
        clock_ids.add(rule["id"])
        durations = [key for key in ("hours", "business_days") if key in rule]
        if len(durations) != 1 or rule[durations[0]] <= 0:
            raise ValueError("Each clock needs one positive duration.")
        if "business_days" in rule and not isinstance(rule["business_days"], int):
            raise ValueError("Business-day durations must be whole days.")
    return config
