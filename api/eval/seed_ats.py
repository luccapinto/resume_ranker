"""Load the demo corpus into the ATS.

Runs the real pipeline for every document — PII redaction, LLM extraction, ESCO
normalisation, Qdrant indexing — then ranks every job so the funnel is populated
and the dashboard has something to show.

    python -m api.eval.seed_ats                # skips what already exists
    python -m api.eval.seed_ats --reset        # wipes the ATS first
    python -m api.eval.seed_ats --explain 3    # also writes AI summaries for each job's top 3
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional

from sqlalchemy import text as sql_text

from api import ats as ats_service
from api import observability as obs
from api import telemetry
from api.database import Base, SessionLocal, engine, get_qdrant
from api.embeddings import get_embedding_provider
from api.models import (
    ActivityModel,
    ApplicationModel,
    CandidateModel,
    JobModel,
    ProfileModel,
)
from api.search import COLLECTIONS, init_qdrant_collections
from api.services import get_ingestion

SEED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "seed")

STAGE_PLAN = ["screening", "interview", "offer", "hired"]
SOURCES = ["LinkedIn", "Indicação", "Site de carreiras", "Banco de talentos"]
RECRUITERS = ["Camila Ferreira", "Rodrigo Alencar", "Marina Duarte"]


def load_manifest() -> dict:
    path = os.path.join(SEED_DIR, "manifest.json")
    if not os.path.exists(path):
        print(
            "Corpus não encontrado. Rode primeiro: python -m api.eval.generate_seed_corpus",
            file=sys.stderr,
        )
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_doc(kind: str, slug: str) -> Optional[str]:
    path = os.path.join(SEED_DIR, kind, f"{slug}.txt")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def reset(db) -> None:
    """Truncate the ATS and drop the vector collections."""
    print("Limpando dados existentes…")
    for model in (ActivityModel, ApplicationModel, CandidateModel, JobModel, ProfileModel):
        db.query(model).delete()
    db.commit()
    db.execute(sql_text("DELETE FROM spans"))
    db.execute(sql_text("DELETE FROM traces"))
    db.execute(sql_text("DELETE FROM audit_logs"))
    db.commit()

    client = get_qdrant()
    for collection in COLLECTIONS:
        try:
            client.delete_collection(collection)
        except Exception:  # noqa: BLE001 — collection may simply not exist
            pass
    init_qdrant_collections(client, get_embedding_provider().dimension)


def ingest_document(kind: str, slug: str, raw_text: str) -> Optional[int]:
    """Run one document through the pipeline in its own session and trace."""
    db = SessionLocal()
    try:
        with obs.trace(f"seed.{kind}", slug=slug, source="seed"):
            profile = get_ingestion().build_profile(
                db, raw_text, "candidate" if kind == "candidates" else "job", file_name=f"{slug}.txt"
            )
            return profile.id
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ {slug}: {exc}", file=sys.stderr)
        return None
    finally:
        db.close()


def seed(reset_first: bool = False, workers: int = 4, explain_top: int = 0) -> None:
    telemetry.install()
    Base.metadata.create_all(bind=engine)
    init_qdrant_collections(get_qdrant(), get_embedding_provider().dimension)

    manifest = load_manifest()
    db = SessionLocal()
    rng = random.Random(42)  # deterministic funnel placement

    try:
        if reset_first:
            reset(db)

        # ── Jobs ────────────────────────────────────────────────────────
        existing_jobs = {j.title: j for j in db.query(JobModel).all()}
        job_specs = [j for j in manifest["jobs"] if j["title"] not in existing_jobs]

        print(f"Processando {len(job_specs)} vagas…")
        job_profiles: Dict[str, int] = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for spec in job_specs:
                raw = read_doc("jobs", spec["slug"])
                if raw:
                    futures[pool.submit(ingest_document, "jobs", spec["slug"], raw)] = spec
            for future in as_completed(futures):
                spec = futures[future]
                profile_id = future.result()
                if profile_id:
                    job_profiles[spec["slug"]] = profile_id
                    print(f"  ✓ vaga {spec['title']}")

        jobs_by_slug: Dict[str, JobModel] = {}
        for spec in manifest["jobs"]:
            if spec["title"] in existing_jobs:
                jobs_by_slug[spec["slug"]] = existing_jobs[spec["title"]]
                continue
            profile_id = job_profiles.get(spec["slug"])
            if not profile_id:
                continue
            job = JobModel(
                profile_id=profile_id,
                title=spec["title"],
                department=spec.get("department"),
                location=spec.get("location"),
                work_model=spec.get("work_model"),
                employment_type=spec.get("employment_type"),
                seniority=spec.get("seniority"),
                salary_min=spec.get("salary_min"),
                salary_max=spec.get("salary_max"),
                headcount=spec.get("headcount", 1),
                owner=spec.get("owner"),
                status="open",
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            jobs_by_slug[spec["slug"]] = job

        # ── Candidates ──────────────────────────────────────────────────
        existing_files = {
            p.file_name for p in db.query(ProfileModel).filter(ProfileModel.type == "candidate").all()
        }
        candidate_specs = [
            c for c in manifest["candidates"] if f"{c['slug']}.txt" not in existing_files
        ]

        print(f"\nProcessando {len(candidate_specs)} currículos…")
        candidate_profiles: Dict[str, int] = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for spec in candidate_specs:
                raw = read_doc("candidates", spec["slug"])
                if raw:
                    futures[pool.submit(ingest_document, "candidates", spec["slug"], raw)] = spec
            done = 0
            for future in as_completed(futures):
                spec = futures[future]
                done += 1
                profile_id = future.result()
                if profile_id:
                    candidate_profiles[spec["slug"]] = profile_id
                    print(f"  [{done}/{len(futures)}] ✓ {spec['slug']}")

        for spec in manifest["candidates"]:
            profile_id = candidate_profiles.get(spec["slug"])
            if not profile_id:
                continue
            profile = db.query(ProfileModel).filter(ProfileModel.id == profile_id).first()
            if not profile:
                continue
            identity = ats_service.derive_identity(profile)
            extracted = profile.extracted_profile or {}
            db.add(
                CandidateModel(
                    profile_id=profile.id,
                    display_name=identity["display_name"],
                    headline=extracted.get("headline") or extracted.get("current_title"),
                    location=identity["location"],
                    email=identity["email"],
                    phone=identity["phone"],
                    source=rng.choice(SOURCES),
                )
            )
        db.commit()

        # ── Ranking + funnel ────────────────────────────────────────────
        print("\nRanqueando candidatos para cada vaga…")
        for job in jobs_by_slug.values():
            with obs.trace("seed.rank", job_id=job.id, job=job.title):
                outcome = ats_service.rank_job(
                    db, job_id=job.id, top_n=12, top_k=40, explain_top=explain_top
                )
            print(f"  ✓ {job.title}: {len(outcome['results'])} candidatos ranqueados")

            # Give the board a lived-in look: advance the strongest matches.
            applications = (
                db.query(ApplicationModel)
                .filter(ApplicationModel.job_id == job.id)
                .order_by(ApplicationModel.ai_score.desc().nullslast())
                .all()
            )
            for index, application in enumerate(applications):
                if index < len(STAGE_PLAN) and (application.ai_score or 0) >= 50:
                    stage = STAGE_PLAN[min(index, len(STAGE_PLAN) - 1)]
                    if index == 0 and rng.random() < 0.5:
                        stage = "interview"
                    application.stage = stage
                    ats_service.log_activity(
                        db,
                        application.id,
                        "stage_change",
                        f"Avançado para '{stage}' após a triagem assistida por IA.",
                        actor=rng.choice(RECRUITERS),
                        payload={"to": stage},
                    )
                elif (application.ai_score or 0) < 25:
                    application.stage = "rejected"
                    ats_service.log_activity(
                        db,
                        application.id,
                        "stage_change",
                        "Reprovado na triagem: aderência baixa aos requisitos obrigatórios.",
                        actor=rng.choice(RECRUITERS),
                        payload={"to": "rejected"},
                    )
            db.commit()

        overview = ats_service.pipeline_overview(db)
        print("\n" + "─" * 52)
        print(f"Vagas:        {overview['jobs_total']} ({overview['jobs_open']} abertas)")
        print(f"Candidatos:   {overview['candidates_total']}")
        print(f"Candidaturas: {overview['applications_total']}")
        print(f"Score médio:  {overview['avg_ai_score']}")
        print(f"Aderência forte: {overview['strong_fit_count']}")
        print("─" * 52)

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Apaga todos os dados antes de popular")
    parser.add_argument("--workers", type=int, default=4, help="Ingestões simultâneas")
    parser.add_argument("--explain", type=int, default=0, help="Gera análise de IA para os N primeiros de cada vaga")
    args = parser.parse_args()
    seed(reset_first=args.reset, workers=args.workers, explain_top=args.explain)
