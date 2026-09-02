"""Read API for the observability layer."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api import telemetry
from api.database import get_db

router = APIRouter(prefix="/observability", tags=["observabilidade"])


@router.get("/traces")
def list_traces(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None, description="'ok' ou 'error'"),
    name: Optional[str] = Query(None, description="Filtro por nome da operação"),
    db: Session = Depends(get_db),
):
    return telemetry.list_traces(db, limit=limit, offset=offset, status=status, name=name)


@router.get("/traces/{trace_id}")
def get_trace(trace_id: str, db: Session = Depends(get_db)):
    """A single trace with its full span waterfall."""
    trace = telemetry.get_trace(db, trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace não encontrado.")
    return trace


@router.get("/metrics")
def metrics(window_hours: int = Query(24, ge=1, le=720), db: Session = Depends(get_db)):
    """Latency percentiles, error rate, token burn and cost, sliced by layer."""
    return telemetry.get_metrics(db, window_hours=window_hours)


@router.delete("/traces")
def purge(keep_last: int = Query(500, ge=0), db: Session = Depends(get_db)):
    return {"deleted": telemetry.purge_traces(db, keep_last=keep_last)}
