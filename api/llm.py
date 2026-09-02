"""Single entry point for every LLM call in the platform.

Everything — extraction, explanation, the recruiting copilot — goes through
`LLMClient.complete()`, which gives us one place to handle retries, structured
outputs, tool calling, token/cost accounting and tracing.

Cost is taken from OpenRouter's own `usage.cost` (requested via
`usage: {include: true}`) and falls back to a local price table when the
provider omits it.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, TypeVar

import httpx
from pydantic import BaseModel

from api import observability as obs
from api.config import settings

logger = logging.getLogger("llm")

T = TypeVar("T", bound=BaseModel)

# USD per 1M tokens. Only used when the provider does not report a cost.
FALLBACK_PRICING: Dict[str, tuple] = {
    "deepseek/deepseek-v4-flash": (0.0886, 0.1772),
    "deepseek/deepseek-v4-pro": (1.042, 2.085),
    "anthropic/claude-haiku-4.5": (1.0, 5.0),
    "google/gemini-2.5-flash": (0.30, 2.50),
    "google/gemini-2.5-pro": (1.25, 10.0),
    "openai/gpt-4o-mini": (0.15, 0.60),
}


class LLMNotConfigured(RuntimeError):
    """Raised when no OpenRouter key is available."""


class LLMError(RuntimeError):
    """Raised when the provider could not be reached or returned garbage."""


@dataclass
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    finish_reason: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)
    attempts: int = 1

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def json(self) -> Any:
        """Parse `content` as JSON, tolerating models that wrap it in fences."""
        text = (self.content or "").strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.lstrip().lower().startswith("json"):
                text = text.lstrip()[4:]
            text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start != -1 and end > start:
                return json.loads(text[start : end + 1])
            raise


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    price = FALLBACK_PRICING.get(model)
    if not price:
        # Match on the family (e.g. "deepseek/deepseek-v4-flash-0731").
        for key, value in FALLBACK_PRICING.items():
            if model.startswith(key):
                price = value
                break
    if not price:
        return 0.0
    return (prompt_tokens / 1_000_000) * price[0] + (completion_tokens / 1_000_000) * price[1]


class LLMClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key if api_key is not None else settings.OPENROUTER_API_KEY
        self.model = model or settings.OPENROUTER_MODEL
        self.base_url = settings.OPENROUTER_BASE_URL

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/luccapinto/resume_ranker",
            "X-Title": "Resume Ranker ATS",
        }

    def complete(
        self,
        messages: List[Dict[str, Any]],
        *,
        span_name: str = "llm.chat",
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        response_schema: Optional[Dict[str, Any]] = None,
        schema_name: str = "Response",
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        max_retries: Optional[int] = None,
    ) -> LLMResponse:
        """Run one chat completion, recording a fully-attributed `llm` span."""
        if not self.is_configured:
            raise LLMNotConfigured(
                "OPENROUTER_API_KEY não configurada. Defina a variável em api/.env."
            )

        model = model or self.model
        retries = max_retries if max_retries is not None else settings.LLM_MAX_RETRIES

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "usage": {"include": True},
        }

        # OpenRouter serves the same model from a dozen providers, and their
        # throughput differs by ~20×. Measured on this workload: the slowest
        # endpoint delivered 5.7 tokens/s against 114 tokens/s for the fastest,
        # and 12% of the calls landed there and burned 52% of the total LLM time.
        # Sorting by throughput is the single biggest latency win available here.
        provider_prefs: Dict[str, Any] = {}
        if settings.OPENROUTER_PROVIDER_SORT:
            provider_prefs["sort"] = settings.OPENROUTER_PROVIDER_SORT
        ignored = [p.strip() for p in settings.OPENROUTER_IGNORE_PROVIDERS.split(",") if p.strip()]
        if ignored:
            provider_prefs["ignore"] = ignored
        if provider_prefs:
            payload["provider"] = provider_prefs
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if response_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": response_schema, "strict": True},
            }
        if tools:
            payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice

        with obs.span(span_name, kind=obs.KIND_LLM, provider="openrouter") as sp:
            sp.model = model
            sp.record_input(messages)
            sp.set(
                temperature=temperature,
                structured_output=bool(response_schema),
                provider_sort=provider_prefs.get("sort"),
                tools=[t["function"]["name"] for t in tools] if tools else [],
            )

            last_error: Optional[Exception] = None
            for attempt in range(1, retries + 1):
                try:
                    with httpx.Client(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                        http_response = client.post(
                            f"{self.base_url}/chat/completions",
                            headers=self._headers(),
                            json=payload,
                        )

                    if http_response.status_code != 200:
                        raise LLMError(
                            f"OpenRouter retornou {http_response.status_code}: "
                            f"{http_response.text[:500]}"
                        )

                    body = http_response.json()
                    if body.get("error"):
                        raise LLMError(f"OpenRouter error: {body['error']}")
                    choices = body.get("choices") or []
                    if not choices:
                        raise LLMError(f"Resposta sem choices: {json.dumps(body)[:500]}")

                    message = choices[0].get("message", {}) or {}
                    usage = body.get("usage", {}) or {}
                    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
                    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
                    cost = usage.get("cost")
                    cost_usd = (
                        float(cost)
                        if cost is not None
                        else _estimate_cost(model, prompt_tokens, completion_tokens)
                    )

                    result = LLMResponse(
                        content=message.get("content") or "",
                        model=body.get("model", model),
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        cost_usd=cost_usd,
                        finish_reason=choices[0].get("finish_reason"),
                        tool_calls=message.get("tool_calls") or [],
                        raw=body,
                        attempts=attempt,
                    )

                    sp.record_usage(
                        model=result.model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        cost_usd=cost_usd,
                    )
                    sp.record_output(result.content or result.tool_calls)
                    elapsed = max(sp.duration_ms / 1000.0, 1e-6)
                    sp.set(
                        attempts=attempt,
                        finish_reason=result.finish_reason,
                        provider_name=body.get("provider"),
                        generation_id=body.get("id"),
                        tool_calls_returned=len(result.tool_calls),
                        # Surfaced so a slow provider is visible in the trace
                        # rather than looking like a slow model.
                        output_tokens_per_second=round(completion_tokens / elapsed, 1),
                    )
                    return result

                except Exception as exc:  # noqa: BLE001 — retried below
                    last_error = exc
                    logger.warning("LLM attempt %s/%s failed: %s", attempt, retries, exc)
                    sp.set(**{f"attempt_{attempt}_error": str(exc)[:300]})
                    if attempt < retries:
                        time.sleep(min(2.0 * attempt, 6.0))

            raise LLMError(
                f"Falha após {retries} tentativas ao chamar {model}. Último erro: {last_error}"
            )

    def structured(
        self,
        messages: List[Dict[str, Any]],
        schema_class: Type[T],
        *,
        span_name: str = "llm.structured",
        **kwargs: Any,
    ) -> T:
        """Chat completion validated against a Pydantic model.

        Some providers ignore `additionalProperties: false` on nested objects, so
        a parse/validation failure is retried once with an explicit repair turn.
        """
        schema = _strict_json_schema(schema_class)
        response = self.complete(
            messages,
            span_name=span_name,
            response_schema=schema,
            schema_name=schema_class.__name__,
            **kwargs,
        )
        try:
            return schema_class.model_validate(response.json())
        except Exception as first_error:  # noqa: BLE001
            obs.annotate(schema_repair=True, schema_first_error=str(first_error)[:300])
            repair_messages = messages + [
                {"role": "assistant", "content": response.content},
                {
                    "role": "user",
                    "content": (
                        "Sua resposta anterior não obedeceu ao schema. Erro de validação:\n"
                        f"{str(first_error)[:1200]}\n\n"
                        "Responda novamente APENAS com o JSON válido, sem texto extra."
                    ),
                },
            ]
            retry = self.complete(
                repair_messages,
                span_name=f"{span_name}.repair",
                response_schema=schema,
                schema_name=schema_class.__name__,
                **kwargs,
            )
            return schema_class.model_validate(retry.json())


def _strict_json_schema(schema_class: Type[BaseModel]) -> Dict[str, Any]:
    """Inline $defs and force `additionalProperties: false` everywhere.

    OpenRouter's strict structured-output mode rejects `$ref`/`$defs` on several
    providers, so we flatten the Pydantic schema before sending it.
    """
    schema = schema_class.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref_name = node["$ref"].split("/")[-1]
                target = defs.get(ref_name, {})
                merged = {k: v for k, v in node.items() if k != "$ref"}
                return resolve({**target, **merged})
            out = {k: resolve(v) for k, v in node.items()}
            if out.get("type") == "object":
                out.setdefault("additionalProperties", False)
                if "properties" in out:
                    out["required"] = list(out["properties"].keys())
            return out
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)


_default_client: Optional[LLMClient] = None


def get_llm() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client
