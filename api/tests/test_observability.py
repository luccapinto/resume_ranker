"""The tracing layer: span nesting, error capture, persistence and roll-ups."""

from __future__ import annotations

import datetime as dt

import pytest

from api import observability as obs
from api import telemetry
from api.models import SpanModel, TraceModel


@pytest.fixture
def captured():
    """Collect finished traces in memory instead of writing to Postgres."""
    traces = []
    obs.set_sink(traces.append)
    yield traces
    obs.set_sink(None)


# ── Structure ───────────────────────────────────────────────────────────────
def test_spans_nest_according_to_the_call_graph(captured):
    with obs.trace("op"):
        with obs.span("outer", kind=obs.KIND_LOGIC):
            with obs.span("inner", kind=obs.KIND_LLM):
                pass
        with obs.span("sibling", kind=obs.KIND_VECTOR):
            pass

    trace = captured[0]
    by_name = {s.name: s for s in trace.spans}
    assert by_name["inner"].parent_id == by_name["outer"].id
    assert by_name["inner"].depth == 1
    assert by_name["outer"].parent_id is None
    assert by_name["sibling"].parent_id is None


def test_nested_trace_calls_collapse_into_a_span(captured):
    """A traced helper called inside another trace must not start a second trace."""
    with obs.trace("outer"):
        with obs.trace("inner"):
            pass
    assert len(captured) == 1
    assert "inner" in [s.name for s in captured[0].spans]


def test_span_without_a_trace_does_not_explode():
    with obs.span("solto", kind=obs.KIND_LOGIC) as span:
        span.set(x=1)
    assert span.trace_id == "orphan"


# ── Errors ──────────────────────────────────────────────────────────────────
def test_an_exception_marks_the_span_and_the_trace(captured):
    with pytest.raises(ValueError):
        with obs.trace("op"):
            with obs.span("falha", kind=obs.KIND_LLM):
                raise ValueError("boom")

    trace = captured[0]
    assert trace.status == obs.STATUS_ERROR
    assert "boom" in trace.error_message
    span = trace.spans[0]
    assert span.status == obs.STATUS_ERROR
    assert span.error_type == "ValueError"
    assert "stacktrace" in span.attributes


def test_a_trace_is_still_flushed_when_the_body_raises(captured):
    with pytest.raises(RuntimeError):
        with obs.trace("op"):
            raise RuntimeError("x")
    assert len(captured) == 1


# ── Usage accounting ────────────────────────────────────────────────────────
def test_usage_accumulates_onto_the_trace(captured):
    with obs.trace("op"):
        with obs.span("chamada", kind=obs.KIND_LLM) as span:
            span.record_usage(model="m", prompt_tokens=100, completion_tokens=50, cost_usd=0.001)
        with obs.span("outra", kind=obs.KIND_LLM) as span:
            span.record_usage(model="m", prompt_tokens=10, completion_tokens=5, cost_usd=0.0002)

    trace = captured[0]
    assert trace.total_tokens == 165
    assert trace.total_cost_usd == pytest.approx(0.0012)
    assert trace.llm_calls == 2


def test_previews_are_truncated(captured):
    with obs.trace("op"):
        with obs.span("grande", kind=obs.KIND_LLM) as span:
            span.record_input("x" * 20_000)
    preview = captured[0].spans[0].input_preview
    assert len(preview) < 20_000
    assert "truncado" in preview


def test_annotate_targets_the_innermost_span(captured):
    with obs.trace("op"):
        with obs.span("externo", kind=obs.KIND_LOGIC):
            with obs.span("interno", kind=obs.KIND_LOGIC):
                obs.annotate(marcador=True)

    by_name = {s.name: s for s in captured[0].spans}
    assert by_name["interno"].attributes["marcador"] is True
    assert "marcador" not in by_name["externo"].attributes


def test_serialised_spans_carry_an_offset_from_the_trace_start(captured):
    with obs.trace("op"):
        with obs.span("a", kind=obs.KIND_LOGIC):
            pass
        with obs.span("b", kind=obs.KIND_LOGIC):
            pass

    serialised = captured[0].serialise_spans()
    assert serialised[0]["started_at_offset_ms"] <= serialised[1]["started_at_offset_ms"]
    assert all("duration_ms" in s for s in serialised)


# ── Persistence and metrics ─────────────────────────────────────────────────
def test_traces_are_persisted_with_their_spans(db_session, monkeypatch):
    monkeypatch.setattr(telemetry, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    telemetry.install()

    with obs.trace("ingest.candidate", slug="ana"):
        with obs.span("pii.redact", kind=obs.KIND_PII):
            pass
        with obs.span("llm.extract", kind=obs.KIND_LLM) as span:
            span.record_usage(model="deepseek", prompt_tokens=10, completion_tokens=5, cost_usd=0.01)

    stored = db_session.query(TraceModel).one()
    assert stored.name == "ingest.candidate"
    assert stored.trace_metadata == {"slug": "ana"}
    assert stored.span_count == 2
    assert db_session.query(SpanModel).count() == 2


def test_metrics_roll_up_by_layer_and_model(db_session):
    now = dt.datetime.now()
    db_session.add(
        TraceModel(
            id="t1",
            name="ats.rank",
            status="ok",
            duration_ms=1000.0,
            total_tokens=150,
            total_cost_usd=0.01,
            llm_calls=1,
            span_count=2,
            trace_metadata={},
            started_at=now,
        )
    )
    db_session.add(
        TraceModel(
            id="t2",
            name="ats.rank",
            status="error",
            duration_ms=3000.0,
            total_tokens=0,
            total_cost_usd=0.0,
            llm_calls=0,
            span_count=1,
            error_message="falhou",
            trace_metadata={},
            started_at=now,
        )
    )
    db_session.add_all(
        [
            SpanModel(
                id="s1", trace_id="t1", name="llm.explain", kind="llm", status="ok",
                duration_ms=800.0, model="deepseek", prompt_tokens=100, completion_tokens=50,
                cost_usd=0.01, attributes={},
            ),
            SpanModel(
                id="s2", trace_id="t1", name="search.hybrid", kind="vector", status="ok",
                duration_ms=200.0, attributes={},
            ),
            SpanModel(
                id="s3", trace_id="t2", name="llm.explain", kind="llm", status="error",
                duration_ms=3000.0, error_type="TimeoutError", error_message="estourou",
                attributes={},
            ),
        ]
    )
    db_session.commit()

    metrics = telemetry.get_metrics(db_session, window_hours=24)

    assert metrics["totals"]["traces"] == 2
    assert metrics["totals"]["errors"] == 1
    assert metrics["totals"]["error_rate"] == 0.5
    assert metrics["totals"]["tokens"] == 150

    by_kind = {k["kind"]: k for k in metrics["by_kind"]}
    assert by_kind["llm"]["count"] == 2
    assert by_kind["llm"]["errors"] == 1
    assert by_kind["llm"]["total_ms"] == 3800.0

    assert metrics["by_model"][0]["model"] == "deepseek"
    assert metrics["by_operation"][0]["name"] == "ats.rank"
    assert metrics["recent_errors"][0]["error_type"] == "TimeoutError"


def test_percentiles_handle_an_empty_sample():
    assert telemetry._percentile([], 95) == 0.0
    assert telemetry._percentile([10.0], 95) == 10.0


def test_get_trace_returns_none_for_an_unknown_id(db_session):
    assert telemetry.get_trace(db_session, "inexistente") is None


# ── HTTP surface ────────────────────────────────────────────────────────────
def test_observability_endpoints_are_reachable(client):
    assert client.get("/observability/traces").status_code == 200
    assert client.get("/observability/metrics").status_code == 200
    assert client.get("/observability/traces/nao-existe").status_code == 404
