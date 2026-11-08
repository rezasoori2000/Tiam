"""Prompts for AI verification (spec 6.3). The system text is fixed; the per-event-type template is
editable by an admin (stored in vlm_event_type_settings.prompt_template, null = DEFAULT_TEMPLATES).

Templates are plain text with {placeholders}: {site_type} {camera} {zone} {local_time} {event_type}
{reason}. Unknown placeholders are left as written.
"""
import string

SYSTEM = """You review security-camera key frames from a car park to cut false alarms. An automatic \
detector raised an incident; decide from the images whether what it describes is really happening.

Rules:
- Judge only observable actions and positions (what people and vehicles are doing). Never infer or \
mention emotions, intent, health, age, gender, ethnicity or identity.
- The frames are in time order. Boxes with "#id" labels mark tracked objects; the incident concerns \
the red ones.
- "confirmed": the images clearly show the described situation. "rejected": they clearly show an \
ordinary explanation (see the list in the request) or nothing of the kind. "uncertain": the images \
can't settle it (too small, blurry, dark, occluded).
- confidence is 0.0-1.0 for your verdict. severity_suggestion is 1-10 (10 = act now).
- person_description_for_talkdown: clothing and colours only (e.g. "dark hoodie, grey pants"), or null.
- reason: one or two factual sentences about what is visible."""

# event type -> (what the detector claims, common false-alarm explanations)
DEFAULT_TEMPLATES = {
    "car_prowling": (
        "Site: {site_type} car park. Camera: {camera}. Zone: {zone}. Local time: {local_time}.\n"
        "Detector: possible car prowling - {reason}.\n"
        "Is a person moving between parked cars and inspecting or tampering with them (trying door "
        "handles, looking in windows, crouching at doors or under a car)?\n"
        "Common false alarms: owner walking to or loading their own car, looking for their car "
        "(often with a key fob), parking attendant, cleaner, valet, child walking with a group, "
        "someone reading a bay number or sign."
    ),
    "fight": (
        "Site: {site_type} car park. Camera: {camera}. Zone: {zone}. Local time: {local_time}.\n"
        "Detector: possible fight or assault - {reason}.\n"
        "Are the marked people physically fighting or is one attacking the other (punching, kicking, "
        "shoving, grappling, pushing someone to the ground)?\n"
        "Common false alarms: hug or greeting, people helping someone walk or get up, carrying or "
        "loading things together, play-fighting children, waving or pointing while talking, "
        "two people passing close, a person tying a shoe or picking something up."
    ),
    "exclusion": (
        "Site: {site_type} car park. Camera: {camera}. Zone: {zone} (no entry). Local time: {local_time}.\n"
        "Detector: {reason}.\n"
        "Is the marked object really inside the no-entry area?\n"
        "Common false alarms: object just outside the area line, reflection or shadow, staff or "
        "contractor with an obvious work reason (hi-vis, tools, vehicle markings), a person boxed "
        "behind a fence or glass."
    ),
    "failed_to_stop": (
        "Site: {site_type} car park. Camera: {camera}. Zone: {zone} (stop required). Local time: {local_time}.\n"
        "Detector: {reason}.\n"
        "Did the marked vehicle drive through the stop area without coming to a stop?\n"
        "Common false alarms: vehicle stopped just outside the area, slow traffic queue, the "
        "vehicle is parked or reversing, two vehicles confused."
    ),
    "speeding": (
        "Site: {site_type} car park. Camera: {camera}. Zone: {zone}. Local time: {local_time}.\n"
        "Detector: {reason}.\n"
        "Is the marked vehicle visibly moving fast for a car park (large position change between frames)?\n"
        "Common false alarms: box jumping between vehicles, vehicle at a normal crawl."
    ),
}

GENERIC_TEMPLATE = (
    "Site: {site_type} car park. Camera: {camera}. Zone: {zone}. Local time: {local_time}.\n"
    "Detector: {event_type} - {reason}.\n"
    "Is this really happening in the images?"
)


class _Keep(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render(template: str, **values) -> str:
    return string.Formatter().vformat(template, (), _Keep(**values))


def default_template(event_type: str) -> str:
    return DEFAULT_TEMPLATES.get(event_type, GENERIC_TEMPLATE)


def detector_reason(ev: dict) -> str:
    """One factual line about why the detector fired, from the event dict."""
    etype = ev.get("type")
    tid = ev.get("track_id")
    if etype == "car_prowling":
        visits = ", ".join(f"car #{v['vehicle_track_id']} for {v['seconds']:.0f}s"
                           + (" crouched" if v.get("crouch_seconds", 0) >= 2 else "")
                           for v in ev.get("visits", []))
        return f"person #{tid} stopped beside {ev.get('vehicles_visited', 0)} parked cars ({visits})"
    if etype == "fight":
        a, b = (ev.get("person_ids") or [tid, None])[:2]
        what = {"charge": f"one rushed at the other ({ev.get('closing_speed_mps', 0)} m/s)",
                "fall": f"person #{ev.get('fallen_track_id')} went to the ground during the encounter"
                }.get(ev.get("subtype"), f"fast arm/leg movement for {ev.get('agitated_seconds', 0)}s")
        return f"persons #{a} and #{b} {ev.get('distance_m', 0)} m apart, {what}"
    if etype == "exclusion":
        return f"{ev.get('class_name', 'object')} #{tid} inside the zone"
    if etype == "speeding":
        return f"{ev.get('class_name', 'vehicle')} #{tid} measured at {ev.get('speed_kmh', 0):.0f} km/h, limit {ev.get('limit_kmh')} km/h"
    if etype == "failed_to_stop":
        return f"{ev.get('class_name', 'vehicle')} #{tid} left the stop area without stopping"
    return f"track #{tid}"
