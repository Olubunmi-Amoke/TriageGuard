"""Presentation-only demo pins; unpinned cases retain deadline ordering."""

from engine.clocks import next_clock
from engine.models import Config, Incident


def order_incidents(incidents: list[Incident], config: Config) -> list[Incident]:
    """Pin configured walkthroughs in order, then sort remaining cases by deadline."""
    pinned = {incident_id: rank for rank, incident_id in enumerate(config["demo"]["pinned_incident_ids"])}
    return sorted(
        incidents,
        key=lambda incident: (
            pinned.get(incident["id"], len(pinned)),
            (next_clock(incident, config) or {}).get("deadline") or "9999",
            incident["id"],
        ),
    )
