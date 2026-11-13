"""Append-only action history and portable CSV export."""

import csv
import io
import json
from copy import deepcopy
from typing import Any, Literal

from engine.models import Incident


def append_event(
    incident: Incident, timestamp: str, actor: Literal["PM", "System suggestion"],
    action: str, before: Any, after: Any,
) -> None:
    """Snapshot before/after values so later edits cannot rewrite history."""
    incident["audit"].append({
        "timestamp": timestamp, "actor": actor, "action": action,
        "before": deepcopy(before), "after": deepcopy(after),
    })


def audit_csv(incident: Incident) -> str:
    """Export chronological audit rows; neutralize spreadsheet formula cells."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["timestamp", "actor", "action", "before", "after"])
    for event in incident["audit"]:
        cells = [
            event["timestamp"], event["actor"], event["action"],
            json.dumps(event["before"], ensure_ascii=False),
            json.dumps(event["after"], ensure_ascii=False),
        ]
        writer.writerow(["'" + cell if cell.startswith(("=", "+", "-", "@")) else cell for cell in cells])
    return output.getvalue()
