"""Any OpenAI-compatible chat-completions server: OpenAI, Azure OpenAI, and LOCAL models such as Qwen
(Qwen3-VL 8B) served by Ollama, vLLM, LM Studio or NVIDIA NIM on the site GPU. Base URL decides which.
"""
import base64
import time
from typing import List

import openai

from .base import VERDICT_SCHEMA, ProviderError, VerdictResult, parse_verdict

OLLAMA_BASE_URL = "http://localhost:11434/v1"


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(self, api_key: str, model: str, timeout_s: float = 20.0, base_url: str = ""):
        if not model:
            raise ProviderError("model name is required (e.g. qwen3-vl:8b for Ollama)")
        self.model = model
        # Local servers ignore the key, but the SDK requires a non-empty one.
        self._client = openai.OpenAI(
            api_key=api_key or "not-needed", base_url=base_url or None, timeout=timeout_s, max_retries=1,
        )

    def verify(self, images: List[bytes], system: str, prompt: str) -> VerdictResult:
        content = [{"type": "text", "text": prompt}] + [
            {"type": "image_url",
             "image_url": {"url": "data:image/jpeg;base64," + base64.standard_b64encode(img).decode("ascii")}}
            for img in images
        ]
        messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        strict = {"type": "json_schema", "json_schema": {"name": "verdict", "schema": VERDICT_SCHEMA, "strict": True}}
        t0 = time.time()
        try:
            try:
                response = self._client.chat.completions.create(
                    model=self.model, messages=messages, response_format=strict, max_tokens=1024,
                )
            except openai.BadRequestError:
                # Older local servers don't know json_schema: fall back to plain JSON mode.
                response = self._client.chat.completions.create(
                    model=self.model, messages=messages, response_format={"type": "json_object"}, max_tokens=1024,
                )
        except openai.AuthenticationError as exc:
            raise ProviderError("API key rejected (401)") from exc
        except openai.NotFoundError as exc:
            raise ProviderError(f"model {self.model!r} not found on the server (404)") from exc
        except openai.RateLimitError as exc:
            raise ProviderError("rate limited (429)") from exc
        except openai.BadRequestError as exc:
            raise ProviderError(f"request rejected (400): {str(exc)[:300]}") from exc
        except openai.APIStatusError as exc:
            raise ProviderError(f"server error {exc.status_code}") from exc
        except openai.APITimeoutError as exc:
            raise ProviderError("timed out") from exc
        except openai.APIConnectionError as exc:
            raise ProviderError("can't reach the model server (is it running? check the base URL)") from exc
        latency_ms = int((time.time() - t0) * 1000)
        choice = response.choices[0] if response.choices else None
        if choice is None or not choice.message or not choice.message.content:
            raise ProviderError("empty answer from the model")
        return parse_verdict(choice.message.content, response.model or self.model, latency_ms)
