"""The single LLM entry point: retries, cost accounting and schema handling."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from api import observability as obs
from api.llm import (
    FALLBACK_PRICING,
    LLMClient,
    LLMError,
    LLMNotConfigured,
    LLMResponse,
    _estimate_cost,
    _strict_json_schema,
)


class Sample(BaseModel):
    name: str
    years: float = Field(description="anos")
    tags: list[str]


def _http_response(status: int = 200, body: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body or {}
    response.text = json.dumps(body or {})
    return response


def _ok_body(content: str = '{"ok": true}', cost: float | None = 0.0004) -> dict:
    usage = {"prompt_tokens": 120, "completion_tokens": 40}
    if cost is not None:
        usage["cost"] = cost
    return {
        "id": "gen-1",
        "model": "deepseek/deepseek-v4-flash",
        "provider": "Fireworks",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": usage,
    }


@pytest.fixture
def client() -> LLMClient:
    return LLMClient(api_key="test-key", model="deepseek/deepseek-v4-flash")


# ── Configuration ───────────────────────────────────────────────────────────
def test_an_unconfigured_client_refuses_to_call():
    with pytest.raises(LLMNotConfigured):
        LLMClient(api_key="").complete([{"role": "user", "content": "oi"}])


# ── Happy path ──────────────────────────────────────────────────────────────
def test_complete_returns_usage_and_provider_cost(client):
    with patch("httpx.Client") as http:
        http.return_value.__enter__.return_value.post.return_value = _http_response(200, _ok_body())
        result = client.complete([{"role": "user", "content": "oi"}])

    assert result.prompt_tokens == 120
    assert result.completion_tokens == 40
    assert result.total_tokens == 160
    assert result.cost_usd == 0.0004
    assert result.attempts == 1


def test_cost_is_estimated_when_the_provider_omits_it(client):
    with patch("httpx.Client") as http:
        http.return_value.__enter__.return_value.post.return_value = _http_response(
            200, _ok_body(cost=None)
        )
        result = client.complete([{"role": "user", "content": "oi"}])

    expected = _estimate_cost("deepseek/deepseek-v4-flash", 120, 40)
    assert result.cost_usd == pytest.approx(expected)
    assert result.cost_usd > 0


def test_usage_lands_on_the_trace(client):
    captured = []
    obs.set_sink(captured.append)
    try:
        with patch("httpx.Client") as http:
            http.return_value.__enter__.return_value.post.return_value = _http_response(200, _ok_body())
            with obs.trace("teste"):
                client.complete([{"role": "user", "content": "oi"}])
    finally:
        obs.set_sink(None)

    trace = captured[0]
    assert trace.llm_calls == 1
    assert trace.total_tokens == 160
    assert trace.total_cost_usd == pytest.approx(0.0004)


# ── Failure handling ────────────────────────────────────────────────────────
def test_a_transient_failure_is_retried(client):
    with patch("httpx.Client") as http, patch("time.sleep"):
        http.return_value.__enter__.return_value.post.side_effect = [
            _http_response(503, {"error": "overloaded"}),
            _http_response(200, _ok_body()),
        ]
        result = client.complete([{"role": "user", "content": "oi"}], max_retries=3)

    assert result.attempts == 2


def test_persistent_failure_raises_after_the_retry_budget(client):
    with patch("httpx.Client") as http, patch("time.sleep"):
        http.return_value.__enter__.return_value.post.return_value = _http_response(500, {"e": 1})
        with pytest.raises(LLMError, match="Falha após 2 tentativas"):
            client.complete([{"role": "user", "content": "oi"}], max_retries=2)


def test_an_error_payload_with_status_200_is_still_an_error(client):
    with patch("httpx.Client") as http, patch("time.sleep"):
        http.return_value.__enter__.return_value.post.return_value = _http_response(
            200, {"error": {"message": "sem créditos"}}
        )
        with pytest.raises(LLMError):
            client.complete([{"role": "user", "content": "oi"}], max_retries=1)


def test_an_empty_choices_array_is_an_error(client):
    with patch("httpx.Client") as http, patch("time.sleep"):
        http.return_value.__enter__.return_value.post.return_value = _http_response(
            200, {"choices": []}
        )
        with pytest.raises(LLMError):
            client.complete([{"role": "user", "content": "oi"}], max_retries=1)


def test_a_failed_call_marks_the_span_as_errored(client):
    captured = []
    obs.set_sink(captured.append)
    try:
        with patch("httpx.Client") as http, patch("time.sleep"):
            http.return_value.__enter__.return_value.post.return_value = _http_response(500, {})
            with pytest.raises(LLMError):
                with obs.trace("teste"):
                    client.complete([{"role": "user", "content": "oi"}], max_retries=1)
    finally:
        obs.set_sink(None)

    assert captured[0].status == obs.STATUS_ERROR
    assert captured[0].spans[0].status == obs.STATUS_ERROR


# ── JSON handling ───────────────────────────────────────────────────────────
def test_json_parses_a_fenced_response():
    response = LLMResponse(content='```json\n{"a": 1}\n```', model="m")
    assert response.json() == {"a": 1}


def test_json_recovers_from_surrounding_prose():
    response = LLMResponse(content='Claro! Aqui está: {"a": 1} Espero ter ajudado.', model="m")
    assert response.json() == {"a": 1}


def test_json_raises_on_unparseable_content():
    with pytest.raises(json.JSONDecodeError):
        LLMResponse(content="isso não é json", model="m").json()


# ── Schema flattening ───────────────────────────────────────────────────────
def test_strict_schema_forbids_extra_properties_and_requires_every_field():
    schema = _strict_json_schema(Sample)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"name", "years", "tags"}


def test_strict_schema_inlines_nested_definitions():
    class Inner(BaseModel):
        value: int

    class Outer(BaseModel):
        inner: Inner

    schema = _strict_json_schema(Outer)
    assert "$defs" not in schema
    assert "$ref" not in json.dumps(schema)
    assert schema["properties"]["inner"]["properties"]["value"]["type"] == "integer"


def test_structured_repairs_a_schema_violation(client):
    """A model that answers off-schema gets one explicit repair turn."""
    good = '{"name": "Ana", "years": 8.0, "tags": ["Kafka"]}'
    with patch("httpx.Client") as http:
        http.return_value.__enter__.return_value.post.side_effect = [
            _http_response(200, _ok_body('{"nome": "Ana"}')),  # wrong keys
            _http_response(200, _ok_body(good)),
        ]
        result = client.structured([{"role": "user", "content": "extraia"}], Sample)

    assert result.name == "Ana"
    assert result.years == 8.0


# ── Pricing table ───────────────────────────────────────────────────────────
def test_pricing_falls_back_to_the_model_family():
    exact = _estimate_cost("deepseek/deepseek-v4-flash", 1_000_000, 0)
    family = _estimate_cost("deepseek/deepseek-v4-flash-0731", 1_000_000, 0)
    assert exact == pytest.approx(FALLBACK_PRICING["deepseek/deepseek-v4-flash"][0])
    assert family == exact


def test_pricing_returns_zero_for_an_unknown_model():
    assert _estimate_cost("alguem/modelo-desconhecido", 1000, 1000) == 0.0


# ── Provider routing ────────────────────────────────────────────────────────
def test_provider_preferences_are_sent(client, monkeypatch):
    """OpenRouter's slowest endpoint for this model runs ~20x below the fastest."""
    from api.config import settings

    monkeypatch.setattr(settings, "OPENROUTER_PROVIDER_SORT", "throughput")
    monkeypatch.setattr(settings, "OPENROUTER_IGNORE_PROVIDERS", "SlowCorp, Outra")

    with patch("httpx.Client") as http:
        post = http.return_value.__enter__.return_value.post
        post.return_value = _http_response(200, _ok_body())
        client.complete([{"role": "user", "content": "oi"}])

    sent = post.call_args.kwargs["json"]
    assert sent["provider"] == {"sort": "throughput", "ignore": ["SlowCorp", "Outra"]}


def test_provider_key_is_omitted_when_unconfigured(client, monkeypatch):
    from api.config import settings

    monkeypatch.setattr(settings, "OPENROUTER_PROVIDER_SORT", "")
    monkeypatch.setattr(settings, "OPENROUTER_IGNORE_PROVIDERS", "")

    with patch("httpx.Client") as http:
        post = http.return_value.__enter__.return_value.post
        post.return_value = _http_response(200, _ok_body())
        client.complete([{"role": "user", "content": "oi"}])

    assert "provider" not in post.call_args.kwargs["json"]


def test_throughput_is_recorded_on_the_span(client):
    """A slow provider must be visible in the trace, not look like a slow model."""
    captured = []
    obs.set_sink(captured.append)
    try:
        with patch("httpx.Client") as http:
            http.return_value.__enter__.return_value.post.return_value = _http_response(200, _ok_body())
            with obs.trace("teste"):
                client.complete([{"role": "user", "content": "oi"}])
    finally:
        obs.set_sink(None)

    span = captured[0].spans[0]
    assert span.attributes["provider_sort"] == "throughput"
    assert span.attributes["output_tokens_per_second"] > 0
