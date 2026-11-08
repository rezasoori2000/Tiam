"""Converts a raw vision_engine event dict into a human-readable policy_type
string and a 1-10 risk_score, for persistence and the /ws/alerts broadcast.
"""
from typing import Tuple

EVENT_TYPE = dict  # alias for readability at call sites


def score_event(event: dict) -> Tuple[str, int]:
    etype = event["type"]

    if etype == "exclusion":
        return "Exclusion Zone Breach", 7

    if etype == "speeding":
        speed, limit = event["speed_kmh"], event["limit_kmh"]
        overage_ratio = (speed - limit) / limit if limit else 0
        score = min(10, max(1, round(5 + overage_ratio * 5)))
        return f"Speed Limit Exceeded ({speed:.0f} km/h)", score

    if etype == "failed_to_stop":
        return "Failed to Stop (Stop-Required Zone)", 6

    if etype == "car_prowling":
        return f"Car Prowling ({event.get('vehicles_visited', 0)} vehicles checked)", 8

    if etype == "fight":
        what = {"charge": "rush", "fall": "person fell"}.get(event.get("subtype"), "strikes")
        return f"Fight / Assault ({what})", 9

    return etype.replace("_", " ").title(), 5
