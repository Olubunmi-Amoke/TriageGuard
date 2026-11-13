"""Conservative extraction: absence of evidence stays UNKNOWN."""

import re

from engine.models import Config, Fact, FactValue, Seed
from engine.plan import plan_rationale


def keyword_matches(text: str, keyword: str, config: Config) -> bool:
    """Match only explicitly configured indicators, not inferred facts."""
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in config["keywords"][keyword])


def confirmed(facts: dict[str, Fact], key: str) -> FactValue:
    """Return a value only when its fact has been explicitly confirmed."""
    fact = facts[key]
    return fact["value"] if fact["label"] != "UNKNOWN" else None


def validate_fact(key: str, value: FactValue, config: Config) -> None:
    """Validate PM and seed values without coercing unknowns to false."""
    if key not in config["facts"]:
        raise ValueError(f"Unknown fact field: {key}")
    if key in ("contained", "deletion_attested", "privacy_data_involved", "security_process_only"):
        valid = isinstance(value, bool)
    elif key == "record_count":
        valid = isinstance(value, int) and not isinstance(value, bool) and value >= 0
    elif key in ("data_types", "customers", "regions"):
        valid = isinstance(value, list) and bool(value) and all(
            isinstance(item, str) and bool(item.strip()) for item in value
        )
    else:
        valid = isinstance(value, str) and bool(value.strip())
    if not valid:
        raise ValueError(f"A valid, explicit value is required for {config['facts'][key]}.")
    if key == "environment" and value not in config["purview"]["environments"]:
        raise ValueError("Choose a configured environment: " + ", ".join(config["purview"]["environments"]))
    if key == "data_types" and isinstance(value, list):
        unknown = set(value).difference(config["extraction"]["data_types"])
        if unknown:
            raise ValueError(
                "Choose configured data types: " + ", ".join(config["extraction"]["data_types"])
            )
    strings = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    if any(re.fullmatch(config["extraction"]["unknown_value_pattern"], item.strip(), re.IGNORECASE) for item in strings):
        raise ValueError("An unknown placeholder is not a confirmed fact.")


def suggest_extract(seed: Seed, config: Config) -> dict[str, Fact]:
    """Extract explicit statements and preserve a citation for each fact."""
    text = seed["raw_description"]
    rules = config["extraction"]
    facts: dict[str, Fact] = {
        key: {"value": None, "label": "UNKNOWN", "evidence": plan_rationale(config, "extraction", "Not explicitly stated.")}
        for key in config["facts"]
    }

    def record(key: str, value: FactValue, evidence: str) -> None:
        facts[key] = {"value": value, "label": "CONFIRMED", "evidence": plan_rationale(config, "extraction", evidence)}

    clauses = [
        clause for clause in re.split(r"[.;\n]", text)
        if not re.search(rules["uncertain_clause_pattern"], clause, re.IGNORECASE)
    ]
    types = [
        name for name, patterns in rules["data_types"].items()
        if any(re.search(pattern, clause, re.IGNORECASE) for pattern in patterns for clause in clauses)
    ]
    if types:
        record("data_types", types, "Explicit data-type wording in report.")
    for key in ("customers", "regions", "record_count", "how_happened", "environment"):
        matches = list(re.finditer(rules[f"{key}_pattern"], text, re.IGNORECASE))
        if not matches:
            continue
        values: list[FactValue] = []
        for match in matches:
            raw = match.group(1).strip()
            if (
                re.fullmatch(rules["unknown_value_pattern"], raw, re.IGNORECASE)
                or (key == "how_happened" and re.search(rules["uncertain_clause_pattern"], raw, re.IGNORECASE))
            ):
                values.append(None)
                continue
            if key == "record_count":
                value: FactValue = int(raw.replace(",", ""))
            elif key in ("customers", "regions"):
                value = [item.strip() for item in raw.split(",") if item.strip()]
            elif key == "environment":
                value = raw.lower()
                if value not in config["purview"]["environments"]:
                    values.append(None)
                    continue
            else:
                value = raw
            validate_fact(key, value, config)
            values.append(value)
        if any(value != values[0] for value in values):
            facts[key]["evidence"] = plan_rationale(config, "extraction", "Conflicting explicit statements; ask reporter.")
        elif values[0] is not None:
            record(key, values[0], matches[0].group(0))
    for key in ("contained", "deletion_attested", "privacy_data_involved", "security_process_only"):
        yes = any(re.search(p, text, re.IGNORECASE) for p in rules[key]["yes"])
        no = any(re.search(p, text, re.IGNORECASE) for p in rules[key]["no"])
        if yes != no:
            record(key, yes, f"Explicit {key} statement in report.")
        elif yes and no:
            facts[key]["evidence"] = plan_rationale(config, "extraction", "Conflicting explicit statements; ask reporter.")
    for key, value in seed.get("known_fields", {}).items():
        if value is not None:
            validate_fact(key, value, config)
            # Conflicting seed/report evidence must not silently overwrite a fact.
            if "conflict" in facts[key]["evidence"].lower() or (
                facts[key]["label"] != "UNKNOWN" and facts[key]["value"] != value
            ):
                facts[key] = {
                    "value": None, "label": "UNKNOWN",
                    "evidence": plan_rationale(config, "extraction", "Structured field conflicts with report; ask reporter."),
                }
            else:
                record(key, value, "Explicit structured reporter field.")
    return facts
