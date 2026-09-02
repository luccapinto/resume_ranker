"""ATS endpoints: jobs, candidates, applications, funnel and AI ranking."""

from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from api import ats as ats_service
from api import observability as obs
from api.database import get_db
from api.explain import generate_match_explanation
from api.models import (
    STAGE_LABELS,
    STAGES,
    ActivityModel,
    ApplicationModel,
    CandidateModel,
    JobModel,
    ProfileModel,
)
from api.schemas import NoteCreate, RankRequest, StageUpdate
from api.services import get_ingestion

router = APIRouter(prefix="/ats", tags=["ats"])


def _json_meta(raw: Optional[str]) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Campo 'meta' não é um JSON válido: {e}") from e


# ─────────────────────────────────────────────────────────────────────────────
# Overview
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    """Dashboard headline numbers plus the most recent AI activity."""
    stats = ats_service.pipeline_overview(db)
    recent = (
        db.query(ActivityModel)
        .order_by(ActivityModel.created_at.desc())
        .limit(12)
        .all()
    )
    stats["recent_activity"] = [
        {
            "id": a.id,
            "application_id": a.application_id,
            "type": a.type,
            "actor": a.actor,
            "content": a.content,
            "payload": a.payload,
            "created_at": a.created_at,
            "candidate": a.application.candidate.display_name if a.application and a.application.candidate else None,
            "job": a.application.job.title if a.application and a.application.job else None,
        }
        for a in recent
    ]
    stats["stages"] = [{"key": s, "label": STAGE_LABELS[s]} for s in STAGES]
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Jobs
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/jobs")
def list_jobs(status: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(JobModel)
    if status:
        q = q.filter(JobModel.status == status)
    return [ats_service.serialize_job(j, db) for j in q.order_by(JobModel.created_at.desc()).all()]


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(JobModel).filter(JobModel.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Vaga não encontrada.")
    payload = ats_service.serialize_job(job, db)
    payload["profile"] = ats_service.serialize_profile(job.profile) if job.profile else None
    return payload


@router.post("/jobs")
def create_job(
    file: Optional[UploadFile] = File(None),
    text_content: Optional[str] = Form(None),
    meta: Optional[str] = Form(None, description="JSON com title, department, location, work_model…"),
    db: Session = Depends(get_db),
):
    """Publish a job: ingest the description, then create the ATS record."""
    metadata = _json_meta(meta)
    if not file and not text_content:
        raise HTTPException(status_code=400, detail="Informe a descrição da vaga (arquivo ou texto).")

    file_bytes = file.file.read() if file else None
    file_name = file.filename if file else None
    ingestion = get_ingestion()

    with obs.trace("ats.create_job", file_name=file_name):
        raw_text = ingestion.read_source(file_bytes, file_name, text_content)
        if not raw_text.strip():
            raise HTTPException(status_code=400, detail="Nenhum texto legível encontrado.")
        profile = ingestion.build_profile(db, raw_text, "job", file_name=file_name, file_bytes=file_bytes)

        extracted = profile.extracted_profile or {}
        job = JobModel(
            profile_id=profile.id,
            title=metadata.get("title") or extracted.get("role_title") or "Vaga sem título",
            department=metadata.get("department"),
            location=metadata.get("location"),
            work_model=metadata.get("work_model"),
            employment_type=metadata.get("employment_type"),
            seniority=metadata.get("seniority") or extracted.get("seniority"),
            salary_min=metadata.get("salary_min"),
            salary_max=metadata.get("salary_max"),
            headcount=metadata.get("headcount") or 1,
            owner=metadata.get("owner"),
            status=metadata.get("status") or "open",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return ats_service.serialize_job(job, db)


@router.patch("/jobs/{job_id}/status")
def update_job_status(job_id: int, status: str = Query(...), db: Session = Depends(get_db)):
    if status not in ("open", "paused", "closed"):
        raise HTTPException(status_code=400, detail="Status deve ser 'open', 'paused' ou 'closed'.")
    job = db.query(JobModel).filter(JobModel.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Vaga não encontrada.")
    job.status = status
    db.commit()
    db.refresh(job)
    return ats_service.serialize_job(job, db)


@router.delete("/jobs/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(JobModel).filter(JobModel.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Vaga não encontrada.")
    db.delete(job)
    db.commit()
    return {"deleted": job_id}


# ─────────────────────────────────────────────────────────────────────────────
# Candidates
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/candidates")
def list_candidates(
    q: Optional[str] = Query(None, description="Filtro por nome ou headline"),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(CandidateModel)
    if q:
        like = f"%{q}%"
        query = query.filter(
            CandidateModel.display_name.ilike(like) | CandidateModel.headline.ilike(like)
        )
    rows = query.order_by(CandidateModel.created_at.desc()).limit(limit).all()
    return [ats_service.serialize_candidate(c) for c in rows]


@router.get("/candidates/{candidate_id}")
def get_candidate(candidate_id: int, db: Session = Depends(get_db)):
    candidate = db.query(CandidateModel).filter(CandidateModel.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidato não encontrado.")
    payload = ats_service.serialize_candidate(candidate, include_profile=True)
    payload["applications"] = [
        {
            **ats_service.serialize_application(a, include_candidate=False),
            "job": ats_service.serialize_job(a.job) if a.job else None,
        }
        for a in candidate.applications
    ]
    return payload


@router.post("/candidates")
def create_candidate(
    file: Optional[UploadFile] = File(None),
    text_content: Optional[str] = Form(None),
    meta: Optional[str] = Form(None, description="JSON com display_name, source, job_id…"),
    db: Session = Depends(get_db),
):
    """Add someone to the talent pool, optionally applying them to a job."""
    metadata = _json_meta(meta)
    if not file and not text_content:
        raise HTTPException(status_code=400, detail="Envie o currículo (arquivo PDF ou texto).")

    file_bytes = file.file.read() if file else None
    file_name = file.filename if file else None
    ingestion = get_ingestion()

    with obs.trace("ats.create_candidate", file_name=file_name):
        raw_text = ingestion.read_source(file_bytes, file_name, text_content)
        if not raw_text.strip():
            raise HTTPException(status_code=400, detail="Nenhum texto legível encontrado.")
        profile = ingestion.build_profile(
            db, raw_text, "candidate", file_name=file_name, file_bytes=file_bytes
        )

        identity = ats_service.derive_identity(profile)
        extracted = profile.extracted_profile or {}
        candidate = CandidateModel(
            profile_id=profile.id,
            display_name=metadata.get("display_name") or identity["display_name"],
            headline=metadata.get("headline") or extracted.get("headline") or extracted.get("current_title"),
            location=metadata.get("location") or identity["location"],
            email=metadata.get("email") or identity["email"],
            phone=metadata.get("phone") or identity["phone"],
            source=metadata.get("source") or "Upload manual",
        )
        db.add(candidate)
        db.commit()
        db.refresh(candidate)

        payload = ats_service.serialize_candidate(candidate)
        if metadata.get("job_id"):
            application = ats_service.ensure_application(db, candidate.id, int(metadata["job_id"]))
            payload["application"] = ats_service.serialize_application(application, include_candidate=False)
        return payload


@router.delete("/candidates/{candidate_id}")
def delete_candidate(candidate_id: int, db: Session = Depends(get_db)):
    candidate = db.query(CandidateModel).filter(CandidateModel.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidato não encontrado.")
    db.delete(candidate)
    db.commit()
    return {"deleted": candidate_id}


# ─────────────────────────────────────────────────────────────────────────────
# Ranking & applications
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/jobs/{job_id}/rank")
def rank_job(job_id: int, body: Optional[RankRequest] = None, db: Session = Depends(get_db)):
    """Re-rank the whole talent pool against a job and refresh the funnel."""
    body = body or RankRequest(job_id=job_id)
    with obs.trace("ats.rank", job_id=job_id, top_n=body.top_n, explain_top=body.explain_top):
        try:
            return ats_service.rank_job(
                db,
                job_id=job_id,
                top_n=body.top_n,
                rerank=body.rerank,
                weights=body.weights,
                min_experience_years=body.min_experience_years,
                seniorities=body.seniorities,
                required_certifications=body.required_certifications,
                explain_top=body.explain_top,
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/jobs/{job_id}/applications")
def list_applications(job_id: int, db: Session = Depends(get_db)):
    """The kanban payload: every application on a job, grouped by stage."""
    job = db.query(JobModel).filter(JobModel.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Vaga não encontrada.")

    apps = (
        db.query(ApplicationModel)
        .filter(ApplicationModel.job_id == job_id)
        .order_by(ApplicationModel.ai_score.desc().nullslast(), ApplicationModel.created_at.desc())
        .all()
    )
    serialized = [ats_service.serialize_application(a) for a in apps]
    return {
        "job": ats_service.serialize_job(job, db),
        "stages": [
            {
                "key": stage,
                "label": STAGE_LABELS[stage],
                "applications": [a for a in serialized if a["stage"] == stage],
            }
            for stage in STAGES
        ],
        "total": len(serialized),
    }


@router.get("/applications/{application_id}")
def get_application(application_id: int, db: Session = Depends(get_db)):
    app = db.query(ApplicationModel).filter(ApplicationModel.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Candidatura não encontrada.")
    payload = ats_service.serialize_application(app)
    payload["job"] = ats_service.serialize_job(app.job) if app.job else None
    payload["timeline"] = [
        {
            "id": a.id,
            "type": a.type,
            "actor": a.actor,
            "content": a.content,
            "payload": a.payload,
            "created_at": a.created_at,
        }
        for a in sorted(app.activities, key=lambda x: x.created_at, reverse=True)
    ]
    return payload


@router.patch("/applications/{application_id}/stage")
def update_stage(application_id: int, body: StageUpdate, db: Session = Depends(get_db)):
    try:
        app = ats_service.move_application(db, application_id, body.stage, body.actor, body.note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ats_service.serialize_application(app)


@router.post("/applications/{application_id}/notes")
def add_note(application_id: int, body: NoteCreate, db: Session = Depends(get_db)):
    app = db.query(ApplicationModel).filter(ApplicationModel.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Candidatura não encontrada.")
    activity = ats_service.log_activity(db, app.id, "note", body.content, actor=body.actor)
    db.commit()
    db.refresh(activity)
    return {
        "id": activity.id,
        "type": activity.type,
        "actor": activity.actor,
        "content": activity.content,
        "created_at": activity.created_at,
    }


@router.post("/applications/{application_id}/explain")
def explain_application(application_id: int, db: Session = Depends(get_db)):
    """Generate (and store) the AI analysis for one application."""
    app = db.query(ApplicationModel).filter(ApplicationModel.id == application_id).first()
    if not app or not app.candidate or not app.job:
        raise HTTPException(status_code=404, detail="Candidatura não encontrada.")

    candidate_profile = app.candidate.profile
    job_profile = app.job.profile
    if not candidate_profile or not job_profile:
        raise HTTPException(status_code=422, detail="Perfis extraídos indisponíveis para esta candidatura.")

    with obs.trace("ats.explain_application", application_id=application_id) as trace:
        explanation = generate_match_explanation(
            candidate_raw_text=candidate_profile.raw_text,
            candidate_redacted_text=candidate_profile.redacted_text,
            job_raw_text=job_profile.raw_text,
            candidate_extracted=candidate_profile.extracted_profile,
            job_extracted=job_profile.extracted_profile,
        )
        app.ai_summary = explanation["summary"]
        app.ai_fit = explanation["fit"]
        app.trace_id = trace.id
        ats_service.log_activity(
            db, app.id, "ai_explain", explanation["summary"], actor="IA",
            payload={"fit": explanation["fit"], "trace_id": trace.id},
        )
        db.commit()
        explanation["trace_id"] = trace.id
        explanation["application_id"] = app.id
        return explanation
