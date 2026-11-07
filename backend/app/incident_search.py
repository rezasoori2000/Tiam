"""Phase 1 of Incident Search: turns a free-text question (e.g. "Camera 2,
speeding last week") into structured filters over the existing Event table --
keyword + date-phrase + number parsing against the app's fixed, small
vocabulary (4 rule types, the real camera list). No LLM, no embeddings, no
vector DB -- see CHANGELOG.md for why that's enough for this scope.
"""
import datetime
import re
from dataclasses import dataclass
from typing import Optional

from dateparser.search import search_dates

from . import models

# policy_type always starts with one of these fixed labels (risk.score_event
# puts the label first, e.g. "Speed Limit Exceeded (34 km/h)") -- matching
# the prefix is enough to identify the rule type that fired.
RULE_TYPE_PREFIXES: dict[str, tuple[str, list[str]]] = {
    "exclusion": ("Exclusion Zone Breach", [
        "exclusion", "restricted zone", "restricted area", "trespass", "entered the zone",
    ]),
    "speeding": ("Speed Limit Exceeded", [
        "speeding", "speed", "too fast", "overspeed", "over the limit",
    ]),
    "failed_to_stop": ("Failed to Stop", [
        "stop sign", "failed to stop", "didn't stop", "did not stop", "no stop", "rolling stop",
    ]),
}

_SPEED_OVER_RE = re.compile(r"(?:over|above|more than|faster than)\s*(\d+(?:\.\d+)?)\s*km/?h", re.I)
_LAST_N_RE = re.compile(r"last\s+(\d+)\s*(day|week|month)s?", re.I)


@dataclass
class ParsedFilters:
    policy_prefix: Optional[str] = None
    camera_id: Optional[int] = None
    date_from: Optional[datetime.datetime] = None
    date_to: Optional[datetime.datetime] = None
    min_speed_kmh: Optional[float] = None


def _match_rule_type(q: str) -> Optional[str]:
    ql = q.lower()
    for prefix, keywords in RULE_TYPE_PREFIXES.values():
        if any(kw in ql for kw in keywords):
            return prefix
    return None


def _match_camera(q: str, cameras: list[models.Camera]) -> Optional[int]:
    """Longest matching camera name wins, so e.g. "Bulk Ext Ano West" beats a
    shorter but also-matching name. Word-boundary match avoids a
    single-character/number camera name (cameras can be named plain "4")
    matching on an unrelated digit elsewhere in the question."""
    ql = q.lower()
    best: Optional[tuple[int, int]] = None  # (name length, camera id)
    for cam in cameras:
        name = (cam.name or "").strip()
        if not name:
            continue
        if re.search(r"\b" + re.escape(name.lower()) + r"\b", ql):
            if best is None or len(name) > best[0]:
                best = (len(name), cam.id)
    return best[1] if best else None


def _day_bounds(day: datetime.date) -> tuple[datetime.datetime, datetime.datetime]:
    return (
        datetime.datetime.combine(day, datetime.time.min),
        datetime.datetime.combine(day, datetime.time.max),
    )


def _relative_range(q: str) -> Optional[tuple[datetime.datetime, datetime.datetime]]:
    """Well-defined ranges handled directly, since they're both unambiguous
    and -- for "this/last week" -- not something `dateparser` resolves to a
    range on its own (it picks a single point in time, not a week span)."""
    ql = q.lower()
    today = datetime.datetime.now().date()

    if "today" in ql:
        return _day_bounds(today)
    if "yesterday" in ql:
        return _day_bounds(today - datetime.timedelta(days=1))
    if "this week" in ql:
        return (
            datetime.datetime.combine(today - datetime.timedelta(days=today.weekday()), datetime.time.min),
            datetime.datetime.combine(today, datetime.time.max),
        )
    if "last week" in ql:
        monday = today - datetime.timedelta(days=today.weekday())
        return (
            datetime.datetime.combine(monday - datetime.timedelta(days=7), datetime.time.min),
            datetime.datetime.combine(monday - datetime.timedelta(days=1), datetime.time.max),
        )

    m = _LAST_N_RE.search(ql)
    if m:
        amount, unit = int(m.group(1)), m.group(2)
        days = amount * {"day": 1, "week": 7, "month": 30}[unit]
        return (
            datetime.datetime.combine(today - datetime.timedelta(days=days), datetime.time.min),
            datetime.datetime.combine(today, datetime.time.max),
        )
    return None


def _match_dates(
    q: str, speed_match: Optional[re.Match]
) -> tuple[Optional[datetime.datetime], Optional[datetime.datetime]]:
    """Relative phrases first (see `_relative_range`); otherwise falls back to
    `dateparser` for explicit dates, run over the query with the numeric
    speed phrase stripped out -- without that, fragments like "1m
    on" have been observed to get misread by dateparser as a date (e.g. day=1,
    month=1), a false positive this app's queries hit often since speed
    thresholds are common in the same sentence as no date at all."""
    relative = _relative_range(q)
    if relative is not None:
        return relative

    cleaned = q
    if speed_match is not None:
        cleaned = cleaned.replace(speed_match.group(0), " ")
    # dateparser's search_dates fails to find either side of "X and Y" (but
    # does find them with a comma instead) -- rewritten purely for date
    # detection, the original `q` is still used for every other match above.
    cleaned = cleaned.replace(" and ", ", ")

    found = search_dates(
        cleaned,
        # Restricted to English: left at its multi-language default, common
        # English words (even just "on") have been observed to match as a
        # date in another language's format, a false positive this app can't
        # afford on short free-text queries.
        languages=["en"],
        settings={"PREFER_DATES_FROM": "past", "RELATIVE_BASE": datetime.datetime.now()},
    )
    if not found:
        return None, None
    dates = sorted(dt for _, dt in found)
    start = datetime.datetime.combine(dates[0].date(), datetime.time.min)
    end = datetime.datetime.combine(dates[-1].date(), datetime.time.max)
    return start, end


def parse_query(q: str, cameras: list[models.Camera]) -> ParsedFilters:
    speed_match = _SPEED_OVER_RE.search(q)
    date_from, date_to = _match_dates(q, speed_match)
    return ParsedFilters(
        policy_prefix=_match_rule_type(q),
        camera_id=_match_camera(q, cameras),
        date_from=date_from,
        date_to=date_to,
        min_speed_kmh=float(speed_match.group(1)) if speed_match else None,
    )
