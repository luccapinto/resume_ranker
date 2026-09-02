"""Lightweight, dependency-free AI observability layer.

Every meaningful unit of work in the platform runs inside a *span*, and spans are
grouped into a *trace* (one end-to-end operation such as "ingest a resume" or
"rank candidates for a job"). Spans nest automatically through a `contextvars`
stack, so the recorded tree mirrors the real call graph without any plumbing at
the call sites.

What we capture, per span:

* wall-clock latency (ms) and where it sits inside the parent
* a `kind` (llm / embedding / vector / rerank / pii / db / logic / tool) so the
  dashboard can break latency down by layer
* model name, token usage and USD cost for LLM calls
* truncated input/output previews for debugging prompts
* exceptions, with type and message, marking the span (and its trace) failed —
  except deliberate 4xx responses, which are recorded but not counted as
  failures, so the error rate keeps meaning "something broke"

Traces are flushed to Postgres on completion using a dedicated session, so a
request that blows up still leaves a full record behind.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger("observability")

# ── Span taxonomy ───────────────────────────────────────────────────────────
KIND_LLM = "llm"
KIND_EMBEDDING = "embedding"
KIND_VECTOR = "vector"
KIND_RERANK = "rerank"
KIND_PII = "pii"
KIND_DB = "db"
KIND_LOGIC = "logic"
KIND_TOOL = "tool"
KIND_PARSE = "parse"

STATUS_OK = "ok"
STATUS_ERROR = "error"


def _is_client_error(exc: BaseException) -> bool:
    """True for a 4xx raised deliberately by a handler.

    A request for a job that does not exist is a correct 404, not a system
    failure. Counting it as an error inflates the error-rate metric and buries
    the failures that actually need attention. We duck-type on `status_code`
    rather than importing Starlette, so this module stays dependency-free.
    """
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and 400 <= status < 500


_MAX_PREVIEW = 4000


def _preview(value: Any, limit: int = _MAX_PREVIEW) -> Optional[str]:
    """Render any value as a bounded string safe to persist."""
    if value is None:
        return None
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            value = str(value)
    if len(value) > limit:
        return value[:limit] + f"\n… [truncado, {len(value)} chars no total]"
    return value


@dataclass
class Span:
    id: str
    trace_id: str
    parent_id: Optional[str]
    name: str
    kind: str
    started_at: float
    depth: int = 0
    ended_at: Optional[float] = None
    status: str = STATUS_OK
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    model: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    input_preview: Optional[str] = None
    output_preview: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.perf_counter()
        return (end - self.started_at) * 1000.0

    def set(self, **attrs: Any) -> None:
        """Attach arbitrary key/values to this span (shown in the trace viewer)."""
        self.attributes.update(attrs)

    def record_input(self, value: Any) -> None:
        self.input_preview = _preview(value)

    def record_output(self, value: Any) -> None:
        self.output_preview = _preview(value)

    def record_usage(
        self,
        model: Optional[str] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        if model:
            self.model = model
        self.prompt_tokens += int(prompt_tokens or 0)
        self.completion_tokens += int(completion_tokens or 0)
        self.cost_usd += float(cost_usd or 0.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "kind": self.kind,
            "depth": self.depth,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 3),
            "started_at_offset_ms": 0.0,  # filled in by the Trace when serialising
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": self.cost_usd,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "input_preview": self.input_preview,
            "output_preview": self.output_preview,
            "attributes": self.attributes,
        }


@dataclass
class Trace:
    id: str
    name: str
    started_at: float
    started_wall: float
    status: str = STATUS_OK
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    spans: List[Span] = field(default_factory=list)
    ended_at: Optional[float] = None

    @property
    def duration_ms(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.perf_counter()
        return (end - self.started_at) * 1000.0

    @property
    def total_cost_usd(self) -> float:
        return sum(s.cost_usd for s in self.spans)

    @property
    def total_tokens(self) -> int:
        return sum(s.prompt_tokens + s.completion_tokens for s in self.spans)

    @property
    def llm_calls(self) -> int:
        return sum(1 for s in self.spans if s.kind == KIND_LLM)

    def set(self, **attrs: Any) -> None:
        self.metadata.update(attrs)

    def serialise_spans(self) -> List[Dict[str, Any]]:
        out = []
        for s in self.spans:
            d = s.to_dict()
            d["started_at_offset_ms"] = round((s.started_at - self.started_at) * 1000.0, 3)
            out.append(d)
        out.sort(key=lambda d: d["started_at_offset_ms"])
        return out


# ── Ambient context ─────────────────────────────────────────────────────────
_current_trace: ContextVar[Optional[Trace]] = ContextVar("current_trace", default=None)
_current_span: ContextVar[Optional[Span]] = ContextVar("current_span", default=None)

# Sink installed by the app at startup; kept as a plain callable so the module
# has no import-time dependency on SQLAlchemy or the rest of the app.
_sink = None


def set_sink(fn) -> None:
    """Register the callable that persists finished traces."""
    global _sink
    _sink = fn


def current_trace() -> Optional[Trace]:
    return _current_trace.get()


def current_span() -> Optional[Span]:
    return _current_span.get()


@contextmanager
def trace(name: str, **metadata: Any) -> Iterator[Trace]:
    """Open a root trace. Nested calls reuse the outer trace as a plain span."""
    existing = _current_trace.get()
    if existing is not None:
        with span(name, kind=KIND_LOGIC, **metadata):
            yield existing
        return

    t = Trace(
        id=str(uuid.uuid4()),
        name=name,
        started_at=time.perf_counter(),
        started_wall=time.time(),
        metadata=dict(metadata),
    )
    token = _current_trace.set(t)
    span_token = _current_span.set(None)
    try:
        yield t
    except Exception as exc:  # noqa: BLE001 — we re-raise after recording
        if _is_client_error(exc):
            # Recorded so it is still visible in the trace, but not counted as
            # a system failure.
            t.set(client_error=getattr(exc, "status_code", None), outcome=str(exc)[:200])
        else:
            t.status = STATUS_ERROR
            t.error_message = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        t.ended_at = time.perf_counter()
        _current_span.reset(span_token)
        _current_trace.reset(token)
        _flush(t)


@contextmanager
def span(name: str, kind: str = KIND_LOGIC, **attributes: Any) -> Iterator[Span]:
    """Open a child span under the active trace.

    If no trace is active the span is still yielded (so instrumented code works
    in tests and scripts) but nothing is persisted.
    """
    t = _current_trace.get()
    parent = _current_span.get()

    s = Span(
        id=str(uuid.uuid4()),
        trace_id=t.id if t else "orphan",
        parent_id=parent.id if parent else None,
        name=name,
        kind=kind,
        started_at=time.perf_counter(),
        depth=(parent.depth + 1) if parent else 0,
        attributes=dict(attributes),
    )
    if t:
        t.spans.append(s)

    token = _current_span.set(s)
    try:
        yield s
    except Exception as exc:  # noqa: BLE001
        if _is_client_error(exc):
            s.set(client_error=getattr(exc, "status_code", None), outcome=str(exc)[:200])
        else:
            s.status = STATUS_ERROR
            s.error_type = type(exc).__name__
            s.error_message = str(exc)[:2000]
            s.set(stacktrace=traceback.format_exc()[-2000:])
        raise
    finally:
        s.ended_at = time.perf_counter()
        _current_span.reset(token)


def annotate(**attrs: Any) -> None:
    """Attach attributes to the innermost active span, if any."""
    s = _current_span.get()
    if s is not None:
        s.set(**attrs)


def record_llm_usage(**kwargs: Any) -> None:
    s = _current_span.get()
    if s is not None:
        s.record_usage(**kwargs)


def _flush(t: Trace) -> None:
    if _sink is None:
        return
    try:
        _sink(t)
    except Exception:  # observability must never break the request
        logger.exception("Failed to persist trace %s", t.id)
