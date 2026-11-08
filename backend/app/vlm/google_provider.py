"""Google Gemini (google-genai SDK) as the verifier."""
import time
from typing import List

from .base import VERDICT_SCHEMA, ProviderError, VerdictResult, parse_verdict


class GoogleProvider:
    name = "google"

    def __init__(self, api_key: str, model: str, timeout_s: float = 20.0, base_url: str = ""):
        from google import genai
        from google.genai import types

        if not model:
            raise ProviderError("model name is required for Gemini")
        if not api_key:
            raise ProviderError("an API key is required for Gemini")
        self.model = model
        self._types = types
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
        )

    def verify(self, images: List[bytes], system: str, prompt: str) -> VerdictResult:
        types = self._types
        parts = [types.Part.from_bytes(data=img, mime_type="image/jpeg") for img in images] + [prompt]
        # Gemini's schema dialect has no "additionalProperties" / type lists.
        schema = {k: v for k, v in VERDICT_SCHEMA.items() if k != "additionalProperties"}
        schema["properties"] = dict(schema["properties"], person_description_for_talkdown={"type": "string", "nullable": True})
        t0 = time.time()
        try:
            response = self._client.models.generate_content(
                model=self.model, contents=parts,
                config=types.GenerateContentConfig(
                    system_instruction=system, response_mime_type="application/json", response_schema=schema,
                ),
            )
        except Exception as exc:  # google-genai raises its own error tree; never include the key
            raise ProviderError(f"Gemini request failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
        latency_ms = int((time.time() - t0) * 1000)
        if not getattr(response, "text", None):
            raise ProviderError("empty answer from Gemini (blocked or no candidates)")
        return parse_verdict(response.text, self.model, latency_ms)
