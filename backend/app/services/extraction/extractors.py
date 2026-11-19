"""Extractors: turn notice text into an ExtractedNotice, or fail safely (DESIGN §4.3, §4.6).

Interview notes:
- One small interface (`Extractor`), several implementations chosen by LLM_PROVIDER:
  `none` → ManualExtractor (no AI; the admin types the drive), `openai_compatible` →
  HttpJsonExtractor. Tests use a FakeExtractor. The pipeline never knows which one runs.
- Provider-independent (D10): one plain httpx POST to `{LLM_BASE_URL}/chat/completions`,
  the request shape most hosted APIs and local servers (e.g. Ollama) accept. No vendor
  SDK, no LLM framework. A new provider is one more adapter class.
- Never raises for provider problems: timeouts, network errors, HTTP errors (incl. 429)
  become status "error"; the admin just gets an empty form (manual fallback).
- Invalid output gets exactly ONE retry, with the validation error sent back to the
  model. If the second answer is still broken: status "invalid". Bounded cost/latency.
- If the second answer is a JSON object with a few wrongly-typed fields, those fields are
  dropped (and flagged later) and the rest is kept: a bad field never wastes a good draft.
- Nothing from the notice or the model's answer is logged; only status, model, timings.
"""

import json
import time
from collections.abc import Callable
from datetime import date, datetime
from typing import Any, Protocol

import httpx
import structlog
from pydantic import ValidationError

from app.core.config import LlmSettings
from app.schemas.drive import IST
from app.services.extraction.prompt import build_messages, retry_message
from app.services.extraction.schema import ExtractedNotice, ExtractionResult

log = structlog.get_logger(__name__)


class Extractor(Protocol):
    async def extract(self, raw_text: str) -> ExtractionResult: ...


class ManualExtractor:
    """LLM_PROVIDER=none: no AI, an empty draft. The app stays fully usable."""

    async def extract(self, raw_text: str) -> ExtractionResult:
        return ExtractionResult(status="disabled")


# ---------------------------------------------------------------- parsing the answer


class NotAJsonObjectError(ValueError):
    pass


def _strip_code_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()


def parse_notice(content: str) -> tuple[ExtractedNotice, list[str]]:
    """Parse the model's answer. Returns (notice, fields dropped for having a bad type).

    Raises NotAJsonObjectError if the answer isn't a JSON object at all.
    """
    try:
        data = json.loads(_strip_code_fence(content))
    except json.JSONDecodeError as exc:
        raise NotAJsonObjectError(f"not valid JSON ({exc.msg})") from None
    if not isinstance(data, dict):
        raise NotAJsonObjectError("expected a JSON object")
    try:
        return ExtractedNotice.model_validate(data), []
    except ValidationError as exc:
        bad = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]})
    cleaned = {key: value for key, value in data.items() if key not in bad}
    return ExtractedNotice.model_validate(cleaned), bad


# ---------------------------------------------------------------- HTTP extractor


class _CallError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class HttpJsonExtractor:
    """Any OpenAI-compatible chat-completions endpoint, via one shared httpx client."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        json_mode: str,
        timeout_seconds: float,
        today: Callable[[], date] | None = None,
    ) -> None:
        self._client = client
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._json_mode = json_mode
        self._timeout = timeout_seconds
        self._today = today or (lambda: datetime.now(IST).date())

    async def extract(self, raw_text: str) -> ExtractionResult:
        usage = _Usage()
        messages = build_messages(raw_text, self._today())
        for attempt in (1, 2):
            try:
                content = await self._call(messages, usage)
            except _CallError as exc:
                log.warning("extraction_call_failed", error=exc.code, attempt=attempt)
                return self._result("error", usage, error=exc.code)
            try:
                notice, rejected = parse_notice(content)
            except NotAJsonObjectError as exc:
                problem = str(exc)
            else:
                if not rejected or attempt == 2:
                    return self._result("ok", usage, notice=notice, rejected_fields=rejected)
                problem = f"wrong value types for: {', '.join(rejected)}"
            if attempt == 1:
                messages = [
                    *messages,
                    {"role": "assistant", "content": content},
                    retry_message(problem),
                ]
        return self._result("invalid", usage, error="invalid_output")

    def _result(self, status: str, usage: "_Usage", **fields: Any) -> ExtractionResult:
        return ExtractionResult.model_validate(
            {
                "status": status,
                "model": self._model,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                **fields,
            }
        )

    def _response_format(self) -> dict[str, Any]:
        if self._json_mode == "object":
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "extracted_notice",
                "schema": ExtractedNotice.model_json_schema(),
            },
        }

    async def _call(self, messages: list[dict[str, str]], usage: "_Usage") -> str:
        body = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,
            "response_format": self._response_format(),
        }
        started = time.perf_counter()
        try:
            response = await self._client.post(
                self._url, json=body, headers=self._headers, timeout=self._timeout
            )
        except httpx.TimeoutException:
            raise _CallError("timeout") from None
        except httpx.HTTPError:
            raise _CallError("network") from None
        log.info(
            "extraction_call",
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        if response.status_code >= 400:
            raise _CallError(f"http_{response.status_code}")
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise _CallError("bad_response") from None
        if not isinstance(content, str):
            raise _CallError("bad_response")
        usage.add(payload.get("usage"))
        return content


class _Usage:
    """Token counts summed over both attempts; None if the provider never reports them."""

    def __init__(self) -> None:
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None

    def add(self, reported: object) -> None:
        if not isinstance(reported, dict):
            return
        prompt, completion = reported.get("prompt_tokens"), reported.get("completion_tokens")
        if isinstance(prompt, int):
            self.input_tokens = (self.input_tokens or 0) + prompt
        if isinstance(completion, int):
            self.output_tokens = (self.output_tokens or 0) + completion


def build_extractor(
    settings: LlmSettings, client: httpx.AsyncClient, today: Callable[[], date] | None = None
) -> Extractor:
    if settings.llm_provider == "none":
        return ManualExtractor()
    # The config validator guarantees base URL + model are set for this provider.
    assert settings.llm_base_url is not None  # noqa: S101
    assert settings.llm_model is not None  # noqa: S101
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
    return HttpJsonExtractor(
        client,
        base_url=str(settings.llm_base_url),
        model=settings.llm_model,
        api_key=api_key,
        json_mode=settings.llm_json_mode,
        timeout_seconds=settings.llm_timeout_seconds,
        today=today,
    )
