"""Claude (Anthropic Messages API) as the verifier. Default model: Claude Sonnet 5.5 (chosen 2026-11-08)."""
import base64
import time
from typing import List

import anthropic

from .base import VERDICT_SCHEMA, ProviderError, VerdictResult, parse_verdict

DEFAULT_MODEL = "claude-sonnet-5-5"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str = "", timeout_s: float = 20.0, base_url: str = ""):
        self.model = model or DEFAULT_MODEL
        # The SDK appends /v1/messages itself: "http://localhost:20128/v1" (a local router such as
        # 9router) would become /v1/v1/messages.
        base_url = (base_url or "").rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        # Server-side refusal fallback is a feature of Anthropic's own API; a router may reject it.
        self._direct = not base_url or "api.anthropic.com" in base_url
        # max_retries=1: one SDK retry (with backoff) on connection errors, 408/409/429/5xx.
        self._client = anthropic.Anthropic(
            api_key=api_key, timeout=timeout_s, max_retries=1, base_url=base_url or None,
        )

    def verify(self, images: List[bytes], system: str, prompt: str) -> VerdictResult:
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.standard_b64encode(img).decode("ascii")}}
            for img in images
        ]
        content.append({"type": "text", "text": prompt})
        # Server-side refusal fallback (Claude API only): re-runs a declined request on the model
        # Anthropic recommends for that refusal category, inside the same call.
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"} if self._direct else {}
        t0 = time.time()
        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": content}],
                # Low effort: a short visual yes/no judgement, and gate mode waits on it.
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": VERDICT_SCHEMA}},
                **extra,
            )
        except anthropic.AuthenticationError as exc:
            raise ProviderError("API key rejected (401)") from exc
        except anthropic.PermissionDeniedError as exc:
            raise ProviderError("API key lacks permission for this model (403)") from exc
        except anthropic.NotFoundError as exc:
            raise ProviderError(f"model {self.model!r} not found (404)") from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError("rate limited by Anthropic (429)") from exc
        except anthropic.BadRequestError as exc:
            raise ProviderError(f"request rejected (400): {exc.message[:300]}") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"Anthropic API error {exc.status_code}") from exc
        except anthropic.APITimeoutError as exc:
            raise ProviderError("timed out") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("can't reach api.anthropic.com") from exc
        latency_ms = int((time.time() - t0) * 1000)
        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None) if response.stop_details else None
            raise ProviderError(f"model declined the request (refusal, category {category})")
        if response.stop_reason == "max_tokens":
            raise ProviderError("answer cut off (max_tokens)")
        text = next((b.text for b in response.content if b.type == "text"), "")
        return parse_verdict(text, response.model or self.model, latency_ms)
