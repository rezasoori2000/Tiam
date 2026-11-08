"""Shared pieces of AI (VLM) verification: verdict schema, result, provider interface (ADR 0001)."""
import json
import re
from dataclasses import dataclass, field
from typing import List, Optional, Protocol

VERDICTS = ("confirmed", "rejected", "uncertain")

# Same JSON for every provider (spec 6.3). Kept to features every provider's structured-output mode
# accepts (no min/max on numbers): ranges are enforced in parse_verdict.
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "confidence": {"type": "number"},
        "observed_actions": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
        "severity_suggestion": {"type": "integer"},
        "person_description_for_talkdown": {"type": ["string", "null"]},
    },
    "required": ["verdict", "confidence", "observed_actions", "reason", "severity_suggestion",
                 "person_description_for_talkdown"],
    "additionalProperties": False,
}


class ProviderError(Exception):
    """Any failure talking to a provider (network, auth, refusal, unparseable answer). The message is
    stored on the event as vlm_error, so it must never contain the API key."""


@dataclass
class VerdictResult:
    verdict: str
    confidence: float
    observed_actions: List[str] = field(default_factory=list)
    reason: str = ""
    severity_suggestion: Optional[int] = None
    person_description: Optional[str] = None
    model: str = ""
    latency_ms: int = 0


class VLMProvider(Protocol):
    name: str
    model: str

    def verify(self, images: List[bytes], system: str, prompt: str) -> VerdictResult:
        """images: JPEG bytes (key frames). Raises ProviderError."""
        ...


def parse_verdict(text: str, model: str, latency_ms: int) -> VerdictResult:
    """Validates a provider's JSON answer. Tolerates a JSON object wrapped in prose or code fences
    (local models without strict JSON mode do that)."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        m = re.search(r"\{.*\}", text or "", re.S)
        if not m:
            raise ProviderError(f"model did not return JSON: {str(text)[:200]!r}")
        try:
            data = json.loads(m.group(0))
        except ValueError as exc:
            raise ProviderError(f"model returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProviderError("model JSON is not an object")
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in VERDICTS:
        raise ProviderError(f"unknown verdict {verdict!r}")
    try:
        confidence = min(1.0, max(0.0, float(data.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    sev = data.get("severity_suggestion")
    try:
        sev = None if sev is None else min(10, max(1, int(sev)))
    except (TypeError, ValueError):
        sev = None
    actions = data.get("observed_actions") or []
    desc = data.get("person_description_for_talkdown")
    return VerdictResult(
        verdict=verdict, confidence=confidence,
        observed_actions=[str(a)[:200] for a in actions][:10] if isinstance(actions, list) else [],
        reason=str(data.get("reason", ""))[:1000], severity_suggestion=sev,
        person_description=str(desc)[:200] if desc else None, model=model, latency_ms=latency_ms,
    )
