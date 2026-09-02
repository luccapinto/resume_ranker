"""ATS domain services: ingestion, ranking and the hiring funnel.

This is the layer the API routes and the copilot both call. It owns the rule
that matters most in this codebase: identity data (name, e-mail, phone) is
recovered from the redaction map for the recruiter's screen only — the ranking
path reads exclusively from the redacted text and the extracted profile.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from api import observability as obs
from api.config import settings
from api.database import get_qdrant
from api.embeddings import get_embedding_provider
from api.explain import compute_match_signals, generate_match_explanation
from api.models import (
    STAGE_LABELS,
    STAGES,
    ActivityModel,
    ApplicationModel,
    CandidateModel,
    JobModel,
    ProfileModel,
)
from api.normalizer import SkillNormalizer
from api.parser import extract_text_from_pdf
from api.redactor import PIIRedactor
from api.schemas import CandidateProfile, JobRequirements
from api.search import build_qdrant_filter, hybrid_search_and_rerank, ingest_profile

FIT_THRESHOLDS = ((75.0, "forte"), (50.0, "moderado"))


def fit_from_score(score_normalized: float) -> str:
    for threshold, label in FIT_THRESHOLDS:
        if score_normalized >= threshold:
            return label
    return "baixo"


# ─────────────────────────────────────────────────────────────────────────────
# Identity recovery
# ─────────────────────────────────────────────────────────────────────────────
# Two to six name-like words, no digits, no punctuation a name never contains.
_NAME_WORD = r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\'’\-]+"
_NAME_RE = re.compile(rf"^{_NAME_WORD}(?:\s+{_NAME_WORD}){{1,5}}$")
_NAME_PARTICLES = {"da", "de", "do", "das", "dos", "e", "di", "del", "van", "von"}


def _titleize(value: str) -> str:
    """Render ALL-CAPS résumé headers as a normal name."""
    words = value.split()
    if not any(w.isupper() and len(w) > 1 for w in words):
        return " ".join(words)
    return " ".join(
        w.lower() if w.lower() in _NAME_PARTICLES else w.capitalize() for w in words
    )


def looks_like_person_name(value: Optional[str]) -> bool:
    """Cheap sanity check so a stray NER hit never becomes someone's name.

    spaCy happily tags "Kimball", "Logstash" or "DAGs" as PERSON inside a
    résumé, and Presidio spans can run across a line break. Anything that does
    not read like a Brazilian full name is rejected here. Names are frequently
    written in caps at the top of a CV, so case is not part of the test.
    """
    if not value:
        return False
    candidate = " ".join(value.split())
    if not (5 <= len(candidate) <= 60):
        return False
    if any(ch.isdigit() for ch in candidate) or any(ch in candidate for ch in "@:|/\\"):
        return False
    if not _NAME_RE.match(candidate):
        return False
    # Last line of defence: if the ESCO taxonomy recognises the string as a
    # competency ("Retrieval-Augmented Generation", "Machine Learning"), it is a
    # skill the NER mislabelled, not a person.
    return not _is_known_skill(candidate)


def _is_known_skill(value: str) -> bool:
    try:
        from api.normalizer import normalize_string
        from api.services import get_normalizer

        taxonomy = get_normalizer().exact_match_map
        # Hyphens are meaningful in tech terms (CI/CD, C++) but ESCO stores some
        # of them spaced out, so probe both spellings.
        return any(
            normalize_string(variant) in taxonomy
            for variant in (value, value.replace("-", " "))
        )
    except Exception:  # noqa: BLE001 — the check is advisory, never fatal
        return False


def _redaction_entries(redaction_map: Dict[str, str], prefix: str) -> List[str]:
    """Original values for one entity type, ordered by their placeholder index.

    Redaction placeholders are written right-to-left, so plain dict order puts
    the *last* occurrence first — the opposite of what a display name wants.
    """
    matches = []
    for placeholder, original in (redaction_map or {}).items():
        if placeholder.startswith(f"[{prefix}_"):
            try:
                index = int(placeholder.rstrip("]").rsplit("_", 1)[1])
            except (IndexError, ValueError):
                index = 10_000
            matches.append((index, original))
    return [original for _, original in sorted(matches, key=lambda item: item[0])]


def _from_redaction_map(redaction_map: Dict[str, str], prefix: str) -> Optional[str]:
    entries = _redaction_entries(redaction_map, prefix)
    return entries[0] if entries else None


_PLACEHOLDER_RE = re.compile(r"\[[A-Z_]+_\d+\]")


def rehydrate(text: Optional[str], redaction_map: Dict[str, str]) -> Optional[str]:
    """Put the original values back into model-generated text, for display only.

    Everything the LLM writes is grounded in the anonymised document, so its
    output is peppered with tokens like `[ORGANIZACAO_REDACT_1]`. The recruiter
    should read the real words; the model still never saw them.
    """
    if not text or not redaction_map:
        return text
    return _PLACEHOLDER_RE.sub(lambda m: redaction_map.get(m.group(0), m.group(0)), text)


def clean_labels(values: Optional[List[str]], redaction_map: Dict[str, str]) -> List[str]:
    """Rehydrate a list of model-written labels and drop the ones that were pure PII.

    The extractor sometimes lists a redacted company or place as a "skill". Once
    rehydrated those read as noise, and a bare placeholder reads as a bug — so a
    label that is *only* a placeholder is dropped entirely.
    """
    cleaned = []
    for value in values or []:
        if not value:
            continue
        if _PLACEHOLDER_RE.fullmatch(value.strip()):
            continue
        restored = rehydrate(value, redaction_map)
        if restored and restored.strip():
            cleaned.append(restored.strip())
    return cleaned


def summarize(text: Optional[str], limit: int = 180) -> Optional[str]:
    """Trim a headline to one line, cutting on a word boundary."""
    if not text:
        return text
    single_line = " ".join(text.split())
    if len(single_line) <= limit:
        return single_line
    cut = single_line[:limit].rsplit(" ", 1)[0]
    return f"{cut}…"


def derive_identity(profile: ProfileModel) -> Dict[str, Optional[str]]:
    """Recover display identity from the redaction map — never from the LLM.

    Résumés almost always open with the person's full name, so the first line is
    the most reliable signal; the redaction map is the fallback.
    """
    rmap = profile.redaction_map or {}

    name = None
    for line in (profile.raw_text or "").splitlines()[:4]:
        stripped = line.strip()
        if looks_like_person_name(stripped):
            name = _titleize(stripped)
            break

    if not name:
        for candidate in _redaction_entries(rmap, "NOME_REDACT"):
            if looks_like_person_name(candidate):
                name = _titleize(candidate)
                break

    return {
        "display_name": name or f"Candidato #{profile.id}",
        "email": _from_redaction_map(rmap, "EMAIL_REDACT"),
        "phone": _from_redaction_map(rmap, "TELEFONE_REDACT"),
        "location": _from_redaction_map(rmap, "LOCALIZACAO_REDACT"),
    }


def mask_email(email: Optional[str]) -> Optional[str]:
    if not email or "@" not in email:
        return email
    user, domain = email.split("@", 1)
    visible = user[:2] if len(user) > 2 else user[:1]
    return f"{visible}{'*' * max(3, len(user) - len(visible))}@{domain}"


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion
# ─────────────────────────────────────────────────────────────────────────────
class IngestionService:
    def __init__(
        self,
        redactor: PIIRedactor,
        extractor,
        normalizer: SkillNormalizer,
    ):
        self.redactor = redactor
        self.extractor = extractor
        self.normalizer = normalizer

    def read_source(
        self, file_bytes: Optional[bytes], file_name: Optional[str], text_content: Optional[str]
    ) -> str:
        if file_bytes:
            with obs.span("parse.pdf", kind=obs.KIND_PARSE, file_name=file_name, bytes=len(file_bytes)) as sp:
                text = extract_text_from_pdf(file_bytes)
                sp.set(chars=len(text))
                return text
        return text_content or ""

    def build_profile(
        self,
        db: Session,
        raw_text: str,
        profile_type: str,
        file_name: Optional[str] = None,
        file_bytes: Optional[bytes] = None,
    ) -> ProfileModel:
        """Redact → extract → normalise → persist → index. The whole pipeline."""
        schema = CandidateProfile if profile_type == "candidate" else JobRequirements

        redacted_text, redaction_map = self.redactor.redact(raw_text)
        profile = self.extractor.extract(redacted_text, schema)

        profile_dict = profile.model_dump(mode="json")
        # The extractor occasionally lists a redaction placeholder as a skill;
        # it is PII noise, not a competency, and must not reach the taxonomy.
        profile_dict["skills_raw"] = [
            skill.strip()
            for skill in (profile_dict.get("skills_raw") or [])
            if skill and skill.strip() and not _PLACEHOLDER_RE.fullmatch(skill.strip())
        ]
        profile_dict["skills_normalized"] = [
            s.model_dump() for s in self.normalizer.normalize_batch(profile_dict["skills_raw"])
        ]

        trace = obs.current_trace()
        db_profile = ProfileModel(
            type=profile_type,
            file_name=file_name,
            raw_text=raw_text,
            redacted_text=redacted_text,
            redaction_map=redaction_map,
            extracted_profile=profile_dict,
            has_pdf=False,
            trace_id=trace.id if trace else None,
        )
        db.add(db_profile)
        db.commit()
        db.refresh(db_profile)

        if file_bytes:
            db_profile.has_pdf = self._store_pdf(db_profile, file_bytes)
            db.commit()

        with obs.span("index.qdrant", kind=obs.KIND_VECTOR, profile_id=db_profile.id):
            try:
                ingest_profile(
                    get_qdrant(), db_profile.id, profile_type, profile_dict, get_embedding_provider()
                )
            except Exception:
                db.delete(db_profile)
                db.commit()
                raise

        return db_profile

    @staticmethod
    def _store_pdf(profile: ProfileModel, file_bytes: bytes) -> bool:
        try:
            os.makedirs(settings.pdf_dir, exist_ok=True)
            path = os.path.join(settings.pdf_dir, f"{profile.type}_{profile.id}.pdf")
            with open(path, "wb") as f:
                f.write(file_bytes)
            return True
        except OSError as exc:
            obs.annotate(pdf_store_error=str(exc)[:200])
            return False


# ─────────────────────────────────────────────────────────────────────────────
# Serialisation
# ─────────────────────────────────────────────────────────────────────────────
def serialize_profile(profile: ProfileModel, include_raw: bool = True) -> Dict[str, Any]:
    return {
        "id": profile.id,
        "type": profile.type,
        "file_name": profile.file_name,
        "raw_text": profile.raw_text if include_raw else None,
        "redacted_text": profile.redacted_text,
        "redaction_map": profile.redaction_map,
        "extracted_profile": profile.extracted_profile,
        "has_pdf": bool(profile.has_pdf),
        "trace_id": profile.trace_id,
        "created_at": profile.created_at,
    }


def serialize_candidate(candidate: CandidateModel, include_profile: bool = False) -> Dict[str, Any]:
    extracted = (candidate.profile.extracted_profile if candidate.profile else {}) or {}
    rmap = (candidate.profile.redaction_map if candidate.profile else {}) or {}
    # Everything the model wrote is grounded in the anonymised text, so it comes
    # back peppered with placeholders. Restore them at the display boundary only.
    headline = candidate.headline or extracted.get("headline") or extracted.get("current_title")
    payload = {
        "id": candidate.id,
        "profile_id": candidate.profile_id,
        "display_name": candidate.display_name,
        "initials": "".join(p[0] for p in candidate.display_name.split()[:2]).upper(),
        "headline": summarize(rehydrate(headline, rmap)),
        "location": candidate.location,
        "email": mask_email(candidate.email),
        "phone": candidate.phone,
        "source": candidate.source,
        "seniority": extracted.get("seniority"),
        "experience_years": extracted.get("experience_years"),
        "skills": clean_labels(
            [
                s.get("preferred_label") or s.get("original_term")
                for s in (extracted.get("skills_normalized") or [])
            ],
            rmap,
        ),
        "certifications": clean_labels(extracted.get("certifications"), rmap),
        "languages": clean_labels(extracted.get("languages"), rmap),
        "highlights": [rehydrate(h, rmap) for h in (extracted.get("highlights") or [])],
        "narrative": rehydrate(extracted.get("narrative_experience"), rmap),
        "created_at": candidate.created_at,
    }
    if include_profile and candidate.profile:
        payload["profile"] = serialize_profile(candidate.profile)
    return payload


def serialize_job(job: JobModel, db: Optional[Session] = None) -> Dict[str, Any]:
    extracted = (job.profile.extracted_profile if job.profile else {}) or {}
    rmap = (job.profile.redaction_map if job.profile else {}) or {}
    payload = {
        "id": job.id,
        "profile_id": job.profile_id,
        "title": job.title,
        "department": job.department,
        "location": job.location,
        "work_model": job.work_model,
        "employment_type": job.employment_type,
        "seniority": job.seniority or extracted.get("seniority"),
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "status": job.status,
        "headcount": job.headcount,
        "owner": job.owner,
        "must_have_skills": clean_labels(extracted.get("must_have_skills"), rmap),
        "nice_to_have_skills": clean_labels(extracted.get("nice_to_have_skills"), rmap),
        # The model wrote these from the anonymised description, so they can
        # carry placeholders; restore them at the display boundary.
        "responsibilities": [
            rehydrate(r, rmap) for r in (extracted.get("responsibilities") or [])
        ],
        "skills": clean_labels(
            [
                s.get("preferred_label") or s.get("original_term")
                for s in (extracted.get("skills_normalized") or [])
            ],
            rmap,
        ),
        "narrative": rehydrate(extracted.get("narrative_experience"), rmap),
        "experience_years": extracted.get("experience_years"),
        "created_at": job.created_at,
    }
    if db is not None:
        payload["funnel"] = funnel_counts(db, job.id)
        payload["applications_count"] = sum(payload["funnel"].values())
    return payload


def serialize_application(app: ApplicationModel, include_candidate: bool = True) -> Dict[str, Any]:
    payload = {
        "id": app.id,
        "candidate_id": app.candidate_id,
        "job_id": app.job_id,
        "stage": app.stage,
        "stage_label": STAGE_LABELS.get(app.stage, app.stage),
        "ai_score": app.ai_score,
        "ai_rank": app.ai_rank,
        "ai_rrf_score": app.ai_rrf_score,
        "ai_fit": app.ai_fit,
        "ai_summary": app.ai_summary,
        "ai_matched_skills": app.ai_matched_skills or [],
        "ai_missing_skills": app.ai_missing_skills or [],
        "ai_signals": app.ai_signals or {},
        "ranked_at": app.ranked_at,
        "trace_id": app.trace_id,
        "created_at": app.created_at,
        "updated_at": app.updated_at,
    }
    if include_candidate and app.candidate:
        payload["candidate"] = serialize_candidate(app.candidate)
    return payload


def funnel_counts(db: Session, job_id: int) -> Dict[str, int]:
    counts = {stage: 0 for stage in STAGES}
    rows = (
        db.query(ApplicationModel.stage, ApplicationModel.id)
        .filter(ApplicationModel.job_id == job_id)
        .all()
    )
    for stage, _ in rows:
        if stage in counts:
            counts[stage] += 1
    return counts


# ─────────────────────────────────────────────────────────────────────────────
# Funnel operations
# ─────────────────────────────────────────────────────────────────────────────
def log_activity(
    db: Session,
    application_id: int,
    type_: str,
    content: str,
    actor: str = "Sistema",
    payload: Optional[dict] = None,
) -> ActivityModel:
    activity = ActivityModel(
        application_id=application_id,
        type=type_,
        actor=actor,
        content=content,
        payload=payload or {},
    )
    db.add(activity)
    return activity


def ensure_application(db: Session, candidate_id: int, job_id: int) -> ApplicationModel:
    app = (
        db.query(ApplicationModel)
        .filter(ApplicationModel.candidate_id == candidate_id, ApplicationModel.job_id == job_id)
        .first()
    )
    if app:
        return app
    app = ApplicationModel(candidate_id=candidate_id, job_id=job_id, stage="sourced")
    db.add(app)
    db.commit()
    db.refresh(app)
    log_activity(db, app.id, "created", "Candidatura criada.", actor="Sistema")
    db.commit()
    return app


def move_application(
    db: Session, application_id: int, stage: str, actor: str = "Recrutador", note: Optional[str] = None
) -> ApplicationModel:
    if stage not in STAGES:
        raise ValueError(f"Estágio inválido '{stage}'. Válidos: {', '.join(STAGES)}")
    app = db.query(ApplicationModel).filter(ApplicationModel.id == application_id).first()
    if not app:
        raise ValueError(f"Candidatura {application_id} não encontrada.")

    previous = app.stage
    app.stage = stage
    log_activity(
        db,
        app.id,
        "stage_change",
        f"Movido de '{STAGE_LABELS.get(previous, previous)}' para '{STAGE_LABELS.get(stage, stage)}'."
        + (f" Nota: {note}" if note else ""),
        actor=actor,
        payload={"from": previous, "to": stage},
    )
    db.commit()
    db.refresh(app)
    return app


# ─────────────────────────────────────────────────────────────────────────────
# Ranking
# ─────────────────────────────────────────────────────────────────────────────
def rank_job(
    db: Session,
    job_id: int,
    top_n: int = 10,
    top_k: int = 30,
    rerank: bool = True,
    weights: Optional[List[float]] = None,
    min_experience_years: Optional[float] = None,
    seniorities: Optional[List[str]] = None,
    required_certifications: Optional[List[str]] = None,
    explain_top: int = 0,
    persist: bool = True,
) -> Dict[str, Any]:
    """Rank the talent pool for a job and refresh each application's AI snapshot."""
    job = db.query(JobModel).filter(JobModel.id == job_id).first()
    if not job:
        raise ValueError(f"Vaga {job_id} não encontrada.")

    job_profile = job.profile
    job_extracted = job_profile.extracted_profile or {}

    from api.search import build_profile_texts

    texts = build_profile_texts(job_extracted)

    with obs.span("ats.rank_job", kind=obs.KIND_LOGIC, job_id=job_id, top_n=top_n) as sp:
        results = hybrid_search_and_rerank(
            client=get_qdrant(),
            collection="candidates",
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
            weights=weights,
        )

        profile_ids = [r["id"] for r in results]
        candidates_by_profile = {
            c.profile_id: c
            for c in db.query(CandidateModel).filter(CandidateModel.profile_id.in_(profile_ids)).all()
        }
        profiles_by_id = {
            p.id: p for p in db.query(ProfileModel).filter(ProfileModel.id.in_(profile_ids)).all()
        }

        trace = obs.current_trace()
        now = dt.datetime.now()
        ranked: List[Dict[str, Any]] = []

        for result in results:
            profile = profiles_by_id.get(result["id"])
            candidate = candidates_by_profile.get(result["id"])
            if not profile or not candidate:
                continue

            signals = compute_match_signals(profile.extracted_profile or {}, job_extracted)
            fit = fit_from_score(result["score_normalized"])

            entry = {
                "rank": result["rank"],
                "profile_id": profile.id,
                "score": result["score"],
                "score_normalized": result["score_normalized"],
                "rrf_score": result["rrf_score"],
                "rrf_rank": result["rrf_rank"],
                "reranked": result["reranked"],
                "strategy_ranks": result["strategy_ranks"],
                "strategy_scores": result["strategy_scores"],
                "fit": fit,
                "signals": signals,
                "candidate": serialize_candidate(candidate),
            }

            if persist:
                app = ensure_application(db, candidate.id, job_id)
                app.ai_score = result["score_normalized"]
                app.ai_rank = result["rank"]
                app.ai_rrf_score = result["rrf_score"]
                app.ai_fit = fit
                app.ai_matched_skills = signals["matched_skills"]
                app.ai_missing_skills = signals["missing_skills"]
                app.ai_signals = {
                    "skill_coverage": signals["skill_coverage"],
                    "must_have_coverage": signals["must_have_coverage"],
                    "experience_delta_years": signals["experience_delta_years"],
                    "seniority_gap": signals["seniority_gap"],
                    "strategy_ranks": result["strategy_ranks"],
                    "rrf_rank": result["rrf_rank"],
                    "reranked": result["reranked"],
                }
                app.ranked_at = now
                app.trace_id = trace.id if trace else None
                entry["application_id"] = app.id
                entry["stage"] = app.stage

            ranked.append(entry)

        if persist:
            db.commit()

        # Optional LLM pass over the podium.
        for entry in ranked[: max(0, explain_top)]:
            profile = profiles_by_id.get(entry["profile_id"])
            if not profile:
                continue
            explanation = generate_match_explanation(
                candidate_raw_text=profile.raw_text,
                candidate_redacted_text=profile.redacted_text,
                job_raw_text=job_profile.raw_text,
                candidate_extracted=profile.extracted_profile,
                job_extracted=job_extracted,
            )
            entry["explanation"] = explanation
            if persist and entry.get("application_id"):
                app = db.query(ApplicationModel).filter(ApplicationModel.id == entry["application_id"]).first()
                if app:
                    app.ai_summary = explanation["summary"]
                    log_activity(
                        db,
                        app.id,
                        "ai_explain",
                        explanation["summary"],
                        actor="IA",
                        payload={"fit": explanation["fit"], "trace_id": trace.id if trace else None},
                    )
        if persist and explain_top:
            db.commit()

        sp.set(ranked=len(ranked), explained=min(explain_top, len(ranked)))

        return {
            "job": serialize_job(job, db),
            "trace_id": trace.id if trace else None,
            "weights": weights or [1.0, 1.0, 0.5],
            "reranked": rerank,
            "results": ranked,
        }


def pipeline_overview(db: Session) -> Dict[str, Any]:
    """Aggregate numbers for the dashboard."""
    jobs = db.query(JobModel).all()
    applications = db.query(ApplicationModel).all()
    candidates_total = db.query(CandidateModel).count()

    by_stage = {stage: 0 for stage in STAGES}
    for app in applications:
        if app.stage in by_stage:
            by_stage[app.stage] += 1

    scored = [a.ai_score for a in applications if a.ai_score is not None]
    strong = sum(1 for a in applications if a.ai_fit == "forte")

    return {
        "jobs_total": len(jobs),
        "jobs_open": sum(1 for j in jobs if j.status == "open"),
        "candidates_total": candidates_total,
        "applications_total": len(applications),
        "by_stage": [
            {"stage": s, "label": STAGE_LABELS[s], "count": by_stage[s]} for s in STAGES
        ],
        "avg_ai_score": round(sum(scored) / len(scored), 1) if scored else 0.0,
        "strong_fit_count": strong,
        "hired": by_stage.get("hired", 0),
        "rejected": by_stage.get("rejected", 0),
    }
