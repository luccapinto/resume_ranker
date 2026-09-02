"""Raw matching endpoints — the retrieval engine without the ATS wrapper."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api import ats
from api import observability as obs
from api.database import get_db, get_qdrant
from api.embeddings import get_embedding_provider
from api.explain import generate_match_explanation
from api.fairness import AXES, run_counterfactual_bias_audit
from api.models import AuditLogModel, ProfileModel
from api.search import build_profile_texts, build_qdrant_filter, hybrid_search_and_rerank
from api.services import get_extractor, get_normalizer, get_redactor

router = APIRouter(tags=["matching"])


def _parse_weights(weights: Optional[str]) -> Optional[List[float]]:
    if not weights:
        return None
    try:
        return [float(w) for w in weights.split(",")]
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail="O parâmetro weights deve ser uma lista de floats separada por vírgula."
        ) from e


def _run_match(
    db: Session,
    source_id: int,
    source_type: str,
    target_collection: str,
    min_experience_years: Optional[float],
    required_certifications: Optional[List[str]],
    seniorities: Optional[List[str]],
    top_k: int,
    top_n: int,
    rerank: bool,
    weights: Optional[str],
):
    parsed_weights = _parse_weights(weights)

    source = (
        db.query(ProfileModel)
        .filter(ProfileModel.id == source_id, ProfileModel.type == source_type)
        .first()
    )
    if not source:
        label = "Vaga" if source_type == "job" else "Candidato"
        raise HTTPException(status_code=404, detail=f"{label} não encontrado.")

    texts = build_profile_texts(source.extracted_profile or {})

    with obs.trace(
        f"match.{target_collection}", source_id=source_id, source_type=source_type
    ) as trace:
        try:
            results = hybrid_search_and_rerank(
                client=get_qdrant(),
                collection=target_collection,
                query_text=texts["narrative_text"],
                skills_text=texts["skills_text"],
                provider=get_embedding_provider(),
                qdrant_filter=build_qdrant_filter(
                    min_experience_years=min_experience_years,
                    required_certifications=required_certifications,
                    seniorities=seniorities,
                ),
                top_k_hybrid=top_k,
                top_n_final=top_n,
                rerank=rerank,
                weights=parsed_weights,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Busca híbrida falhou: {e}") from e

        ids = [r["id"] for r in results]
        profiles = {
            p.id: p for p in db.query(ProfileModel).filter(ProfileModel.id.in_(ids)).all()
        }

        response = []
        for r in results:
            profile = profiles.get(r["id"])
            if not profile:
                continue
            response.append(
                {
                    "id": r["id"],
                    "rank": r["rank"],
                    "score": r["score"],
                    "score_normalized": r["score_normalized"],
                    "rrf_score": r["rrf_score"],
                    "rrf_rank": r["rrf_rank"],
                    "reranked": r["reranked"],
                    "strategy_ranks": r["strategy_ranks"],
                    "strategy_scores": r["strategy_scores"],
                    "trace_id": trace.id,
                    "profile": ats.serialize_profile(profile),
                }
            )
        return response


@router.post("/matching/candidates", response_model=List[dict])
def match_candidates_for_job(
    job_id: int,
    min_experience_years: Optional[float] = Query(None, description="Anos mínimos de experiência profissional"),
    required_certifications: Optional[List[str]] = Query(None, description="Certificações obrigatórias"),
    seniorities: Optional[List[str]] = Query(None, description="Níveis de senioridade aceitos"),
    top_k: int = Query(20, description="Top-K para RRF e Cross-Encoder"),
    top_n: int = Query(10, description="Top-N final a retornar"),
    rerank: bool = Query(True, description="Habilitar reranking com Cross-Encoder"),
    weights: Optional[str] = Query(None, description="Pesos RRF [skills, narrative, lexical], ex: '1,1,0.5'"),
    db: Session = Depends(get_db),
):
    """Find the candidates that best match a job."""
    return _run_match(
        db, job_id, "job", "candidates", min_experience_years, required_certifications,
        seniorities, top_k, top_n, rerank, weights,
    )


@router.post("/matching/jobs", response_model=List[dict])
def match_jobs_for_candidate(
    candidate_id: int,
    min_experience_years: Optional[float] = Query(None),
    required_certifications: Optional[List[str]] = Query(None),
    seniorities: Optional[List[str]] = Query(None),
    top_k: int = Query(20),
    top_n: int = Query(10),
    rerank: bool = Query(True),
    weights: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Find the jobs that best match a candidate (the reverse direction)."""
    return _run_match(
        db, candidate_id, "candidate", "jobs", min_experience_years, required_certifications,
        seniorities, top_k, top_n, rerank, weights,
    )


@router.post("/matching/explain")
def explain_match(candidate_id: int, job_id: int, db: Session = Depends(get_db)):
    """Explain one candidate↔job pair, with every quote verified against the résumé."""
    candidate = (
        db.query(ProfileModel)
        .filter(ProfileModel.id == candidate_id, ProfileModel.type == "candidate")
        .first()
    )
    job = db.query(ProfileModel).filter(ProfileModel.id == job_id, ProfileModel.type == "job").first()
    if not candidate or not job:
        raise HTTPException(status_code=404, detail="Perfil de candidato ou vaga não encontrado.")

    with obs.trace("explain.pair", candidate_id=candidate_id, job_id=job_id) as trace:
        try:
            explanation = generate_match_explanation(
                candidate_raw_text=candidate.raw_text,
                candidate_redacted_text=candidate.redacted_text,
                job_raw_text=job.raw_text,
                candidate_extracted=candidate.extracted_profile,
                job_extracted=job.extracted_profile,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Falha ao gerar explicação: {e}") from e
        explanation["trace_id"] = trace.id
        return explanation


@router.post("/matching/audit-bias")
def audit_bias(
    candidate_id: int,
    job_id: int,
    axes: Optional[List[str]] = Query(None, description=f"Eixos a auditar: {', '.join(AXES)}"),
    deep: bool = Query(False, description="Reexecuta a extração por LLM na variante contrafactual"),
    db: Session = Depends(get_db),
):
    """Counterfactual fairness audit across the configured bias axes."""
    with obs.trace("fairness.audit", candidate_id=candidate_id, job_id=job_id, deep=deep):
        try:
            return run_counterfactual_bias_audit(
                db=db,
                qdrant_client=get_qdrant(),
                candidate_id=candidate_id,
                job_id=job_id,
                provider=get_embedding_provider(),
                extractor=get_extractor(),
                normalizer=get_normalizer(),
                redactor=get_redactor(),
                axes=axes,
                deep=deep,
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Auditoria contrafactual falhou: {e}") from e


@router.get("/audit/logs", response_model=List[dict])
def list_audit_logs(limit: int = Query(50, le=200), db: Session = Depends(get_db)):
    """History of every fairness audit executed."""
    logs = (
        db.query(AuditLogModel)
        .order_by(AuditLogModel.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": log.id,
            "query_type": log.query_type,
            "query_id": log.query_id,
            "embedding_model": log.embedding_model,
            "reranker_model": log.reranker_model,
            "execution_time_ms": log.execution_time_ms,
            "bias_audit_passed": bool(log.bias_audit_passed),
            "bias_audit_results": log.bias_audit_results,
            "trace_id": log.trace_id,
            "created_at": log.created_at,
        }
        for log in logs
    ]
