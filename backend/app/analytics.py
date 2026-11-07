"""Aggregation queries for the Analytics Dashboard. Aggregates in Python
rather than SQL GROUP BY -- event volume here is small and this avoids
cross-dialect SQL quirks (see crud.py's `== True` note for context)."""
import datetime
from collections import defaultdict
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models


def breaches_by_day(db: Session, days: int = 30) -> List[dict]:
    since = datetime.datetime.now() - datetime.timedelta(days=days)
    rows = db.scalars(
        select(models.Event).where(models.Event.timestamp >= since)
    )
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        day = row.timestamp.date().isoformat()
        counts[day] += 1

    # zero-fill every day in the window so the chart has a continuous x-axis
    result = []
    for i in range(days, -1, -1):
        day = (datetime.datetime.now() - datetime.timedelta(days=i)).date().isoformat()
        result.append({"date": day, "count": counts.get(day, 0)})
    return result


def risk_by_policy(db: Session) -> List[dict]:
    rows = db.scalars(select(models.Event))
    sums: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        sums[row.policy_type] += row.risk_score
        counts[row.policy_type] += 1

    result = [
        {
            "policy_type": policy,
            "avg_risk": round(sums[policy] / counts[policy], 2),
            "count": counts[policy],
        }
        for policy in counts
    ]
    result.sort(key=lambda r: r["avg_risk"], reverse=True)
    return result


def camera_leaderboard(db: Session) -> List[dict]:
    cameras = {c.id: c.name for c in db.scalars(select(models.Camera))}
    rows = db.scalars(select(models.Event))

    sums: dict[int, int] = defaultdict(int)
    counts: dict[int, int] = defaultdict(int)
    for row in rows:
        if row.camera_id is None:
            continue
        sums[row.camera_id] += row.risk_score
        counts[row.camera_id] += 1

    result = [
        {
            "camera_id": cam_id,
            "camera_name": cameras.get(cam_id, f"Camera {cam_id}"),
            "total_events": counts[cam_id],
            "avg_risk": round(sums[cam_id] / counts[cam_id], 2),
        }
        for cam_id in counts
    ]
    result.sort(key=lambda r: r["total_events"], reverse=True)
    return result
