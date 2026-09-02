"""Persistence and aggregation for the observability layer.

`install()` wires the in-memory tracer (`api.observability`) to Postgres. Query
helpers below power the /observability endpoints: trace list, trace detail with
the span waterfall, and rolled-up health metrics (latency percentiles by layer,
error rate, token burn, cost).
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from api import observability as obs
from api.database import SessionLocal
from api.models import SpanModel, TraceModel

logger = logging.getLogger("telemetry")


def _persist_trace(trace: obs.Trace) -> None:
    """Sink callback — writes a finished trace and all of its spans."""
    session: Session = SessionLocal()
    try:
        spans = trace.serialise_spans()
        session.add(
            TraceModel(
                id=trace.id,
                name=trace.name,
                status=trace.status,
                duration_ms=round(trace.duration_ms, 3),
                total_tokens=trace.total_tokens,
                total_cost_usd=trace.total_cost_usd,
                llm_calls=trace.llm_calls,
                span_count=len(spans),
                error_message=trace.error_message,
                trace_metadata=trace.metadata,
                started_at=dt.datetime.fromtimestamp(trace.started_wall),
            )
        )
        for s in spans:
            session.add(
                SpanModel(
                    id=s["id"],
                    trace_id=trace.id,
                    parent_id=s["parent_id"],
                    name=s["name"],
                    kind=s["kind"],
                    status=s["status"],
                    depth=s["depth"],
                    duration_ms=s["duration_ms"],
                    started_at_offset_ms=s["started_at_offset_ms"],
                    model=s["model"],
                    prompt_tokens=s["prompt_tokens"],
                    completion_tokens=s["completion_tokens"],
                    cost_usd=s["cost_usd"],
                    error_type=s["error_type"],
                    error_message=s["error_message"],
                    input_preview=s["input_preview"],
                    output_preview=s["output_preview"],
                    attributes=s["attributes"],
                )
            )
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Could not persist trace %s", trace.id)
    finally:
        session.close()


def install() -> None:
    obs.set_sink(_persist_trace)


# ── Queries ─────────────────────────────────────────────────────────────────
def _trace_row(t: TraceModel) -> Dict[str, Any]:
    return {
        "id": t.id,
        "name": t.name,
        "status": t.status,
        "duration_ms": t.duration_ms,
        "total_tokens": t.total_tokens,
        "total_cost_usd": t.total_cost_usd,
        "llm_calls": t.llm_calls,
        "span_count": t.span_count,
        "error_message": t.error_message,
        "metadata": t.trace_metadata or {},
        "started_at": t.started_at,
    }


def list_traces(
    db: Session,
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    q = db.query(TraceModel)
    if status:
        q = q.filter(TraceModel.status == status)
    if name:
        q = q.filter(TraceModel.name.ilike(f"%{name}%"))
    rows = q.order_by(TraceModel.started_at.desc()).offset(offset).limit(limit).all()
    return [_trace_row(t) for t in rows]


def get_trace(db: Session, trace_id: str) -> Optional[Dict[str, Any]]:
    t = db.query(TraceModel).filter(TraceModel.id == trace_id).first()
    if not t:
        return None
    spans = (
        db.query(SpanModel)
        .filter(SpanModel.trace_id == trace_id)
        .order_by(SpanModel.started_at_offset_ms.asc())
        .all()
    )
    payload = _trace_row(t)
    payload["spans"] = [
        {
            "id": s.id,
            "parent_id": s.parent_id,
            "name": s.name,
            "kind": s.kind,
            "status": s.status,
            "depth": s.depth,
            "duration_ms": s.duration_ms,
            "started_at_offset_ms": s.started_at_offset_ms,
            "model": s.model,
            "prompt_tokens": s.prompt_tokens,
            "completion_tokens": s.completion_tokens,
            "cost_usd": s.cost_usd,
            "error_type": s.error_type,
            "error_message": s.error_message,
            "input_preview": s.input_preview,
            "output_preview": s.output_preview,
            "attributes": s.attributes or {},
        }
        for s in spans
    ]
    return payload


def _percentile(values: List[float], p: float) -> float:
    """Nearest-rank percentile; returns 0.0 for an empty sample."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round(p / 100.0 * len(ordered) + 0.5)) - 1))
    return round(ordered[idx], 2)


def get_metrics(db: Session, window_hours: int = 24) -> Dict[str, Any]:
    """Roll up traces/spans in the recent window into dashboard-ready metrics."""
    since = dt.datetime.now() - dt.timedelta(hours=window_hours)

    traces = db.query(TraceModel).filter(TraceModel.started_at >= since).all()
    if not traces:
        traces = db.query(TraceModel).order_by(TraceModel.started_at.desc()).limit(200).all()

    trace_ids = [t.id for t in traces]
    durations = [t.duration_ms for t in traces]
    errors = [t for t in traces if t.status == obs.STATUS_ERROR]

    spans: List[SpanModel] = []
    if trace_ids:
        spans = db.query(SpanModel).filter(SpanModel.trace_id.in_(trace_ids)).all()

    # Latency + error rate broken down by pipeline layer.
    by_kind: Dict[str, Dict[str, Any]] = {}
    for s in spans:
        bucket = by_kind.setdefault(
            s.kind, {"kind": s.kind, "count": 0, "errors": 0, "durations": [], "cost_usd": 0.0, "tokens": 0}
        )
        bucket["count"] += 1
        bucket["durations"].append(s.duration_ms)
        bucket["cost_usd"] += s.cost_usd or 0.0
        bucket["tokens"] += (s.prompt_tokens or 0) + (s.completion_tokens or 0)
        if s.status == obs.STATUS_ERROR:
            bucket["errors"] += 1

    kinds = []
    for bucket in by_kind.values():
        d = bucket.pop("durations")
        bucket["p50_ms"] = _percentile(d, 50)
        bucket["p95_ms"] = _percentile(d, 95)
        bucket["avg_ms"] = round(sum(d) / len(d), 2) if d else 0.0
        bucket["total_ms"] = round(sum(d), 2)
        bucket["cost_usd"] = round(bucket["cost_usd"], 6)
        kinds.append(bucket)
    kinds.sort(key=lambda k: k["total_ms"], reverse=True)

    # Same breakdown, but by operation name — useful to spot a slow endpoint.
    by_op: Dict[str, Dict[str, Any]] = {}
    for t in traces:
        bucket = by_op.setdefault(t.name, {"name": t.name, "count": 0, "errors": 0, "durations": [], "cost_usd": 0.0})
        bucket["count"] += 1
        bucket["durations"].append(t.duration_ms)
        bucket["cost_usd"] += t.total_cost_usd or 0.0
        if t.status == obs.STATUS_ERROR:
            bucket["errors"] += 1
    operations = []
    for bucket in by_op.values():
        d = bucket.pop("durations")
        bucket["p50_ms"] = _percentile(d, 50)
        bucket["p95_ms"] = _percentile(d, 95)
        bucket["cost_usd"] = round(bucket["cost_usd"], 6)
        bucket["error_rate"] = round(bucket["errors"] / bucket["count"], 4) if bucket["count"] else 0.0
        operations.append(bucket)
    operations.sort(key=lambda o: o["count"], reverse=True)

    # Hourly throughput/error timeseries for the sparkline.
    series: Dict[str, Dict[str, Any]] = {}
    for t in traces:
        key = t.started_at.replace(minute=0, second=0, microsecond=0).isoformat()
        b = series.setdefault(key, {"bucket": key, "count": 0, "errors": 0, "cost_usd": 0.0, "durations": []})
        b["count"] += 1
        b["cost_usd"] += t.total_cost_usd or 0.0
        b["durations"].append(t.duration_ms)
        if t.status == obs.STATUS_ERROR:
            b["errors"] += 1
    timeseries = []
    for b in sorted(series.values(), key=lambda x: x["bucket"]):
        d = b.pop("durations")
        b["p95_ms"] = _percentile(d, 95)
        b["cost_usd"] = round(b["cost_usd"], 6)
        timeseries.append(b)

    llm_spans = [s for s in spans if s.kind == obs.KIND_LLM]
    models: Dict[str, Dict[str, Any]] = {}
    for s in llm_spans:
        key = s.model or "desconhecido"
        m = models.setdefault(key, {"model": key, "calls": 0, "errors": 0, "tokens": 0, "cost_usd": 0.0, "durations": []})
        m["calls"] += 1
        m["tokens"] += (s.prompt_tokens or 0) + (s.completion_tokens or 0)
        m["cost_usd"] += s.cost_usd or 0.0
        m["durations"].append(s.duration_ms)
        if s.status == obs.STATUS_ERROR:
            m["errors"] += 1
    model_rows = []
    for m in models.values():
        d = m.pop("durations")
        m["p95_ms"] = _percentile(d, 95)
        m["avg_ms"] = round(sum(d) / len(d), 2) if d else 0.0
        m["cost_usd"] = round(m["cost_usd"], 6)
        model_rows.append(m)
    model_rows.sort(key=lambda m: m["calls"], reverse=True)

    recent_errors = [
        {
            "trace_id": s.trace_id,
            "span": s.name,
            "kind": s.kind,
            "error_type": s.error_type,
            "error_message": s.error_message,
        }
        for s in sorted(
            [s for s in spans if s.status == obs.STATUS_ERROR],
            key=lambda s: s.started_at_offset_ms,
        )[:20]
    ]

    return {
        "window_hours": window_hours,
        "totals": {
            "traces": len(traces),
            "spans": len(spans),
            "errors": len(errors),
            "error_rate": round(len(errors) / len(traces), 4) if traces else 0.0,
            "llm_calls": len(llm_spans),
            "tokens": sum((s.prompt_tokens or 0) + (s.completion_tokens or 0) for s in spans),
            "cost_usd": round(sum(t.total_cost_usd or 0.0 for t in traces), 6),
            "p50_ms": _percentile(durations, 50),
            "p95_ms": _percentile(durations, 95),
            "p99_ms": _percentile(durations, 99),
            "avg_ms": round(sum(durations) / len(durations), 2) if durations else 0.0,
        },
        "by_kind": kinds,
        "by_operation": operations,
        "by_model": model_rows,
        "timeseries": timeseries,
        "recent_errors": recent_errors,
    }


def purge_traces(db: Session, keep_last: int = 500) -> int:
    """Trim the trace table, keeping only the most recent `keep_last` rows."""
    total = db.query(func.count(TraceModel.id)).scalar() or 0
    if total <= keep_last:
        return 0
    cutoff = (
        db.query(TraceModel.started_at)
        .order_by(TraceModel.started_at.desc())
        .offset(keep_last)
        .limit(1)
        .scalar()
    )
    deleted = db.query(TraceModel).filter(TraceModel.started_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return deleted
