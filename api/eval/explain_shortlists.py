"""Generate the AI analysis for the top candidates of every job.

Seeding leaves the funnel populated but without written summaries, because the
explanation step is the slowest part of the pipeline. This runs it afterwards,
in parallel, so the kanban cards and the candidate timelines have real
LLM-written summaries with verified citations.

    python -m api.eval.explain_shortlists            # top 3 of each job
    python -m api.eval.explain_shortlists --top 5
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

from api import observability as obs
from api import telemetry
from api.database import SessionLocal
from api.explain import generate_match_explanation
from api.models import ApplicationModel, JobModel

# Progress must reach a redirected log immediately; block buffering makes these
# scripts look frozen for the twenty minutes they take to run.
sys.stdout.reconfigure(line_buffering=True)


def explain_one(application_id: int) -> Tuple[int, str]:
    """Run one explanation in its own session and trace."""
    db = SessionLocal()
    try:
        app = db.query(ApplicationModel).filter(ApplicationModel.id == application_id).first()
        if not app or not app.candidate or not app.job:
            return application_id, "candidatura incompleta"

        candidate_profile = app.candidate.profile
        job_profile = app.job.profile
        if not candidate_profile or not job_profile:
            return application_id, "perfis indisponíveis"

        with obs.trace("seed.explain", application_id=application_id) as trace:
            explanation = generate_match_explanation(
                candidate_raw_text=candidate_profile.raw_text,
                candidate_redacted_text=candidate_profile.redacted_text,
                job_raw_text=job_profile.raw_text,
                candidate_extracted=candidate_profile.extracted_profile,
                job_extracted=job_profile.extracted_profile,
            )
            # ai_fit stays derived from the calibrated score so the badge and the
            # ring never contradict each other; the model's own verdict lives in
            # the analysis payload.
            app.ai_summary = explanation["summary"]
            app.trace_id = trace.id

            from api.ats import log_activity

            log_activity(
                db,
                app.id,
                "ai_explain",
                explanation["summary"],
                actor="IA",
                payload={
                    "fit": explanation["fit"],
                    "citations": explanation["hallucination_check"],
                    "trace_id": trace.id,
                },
            )
            db.commit()

        check = explanation["hallucination_check"]
        return application_id, (
            f"{app.candidate.display_name[:26]:28} {explanation['fit']:9} "
            f"citações {check['verified']}/{check['total']}"
        )
    except Exception as exc:  # noqa: BLE001 — one failure must not stop the batch
        return application_id, f"falhou: {exc}"
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=3, help="Quantos candidatos por vaga")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    telemetry.install()
    db = SessionLocal()
    try:
        targets: List[int] = []
        for job in db.query(JobModel).all():
            shortlist = (
                db.query(ApplicationModel)
                .filter(ApplicationModel.job_id == job.id)
                .order_by(ApplicationModel.ai_rank.asc().nullslast())
                .limit(args.top)
                .all()
            )
            targets.extend(a.id for a in shortlist)
    finally:
        db.close()

    if not targets:
        print("Nenhuma candidatura ranqueada — rode `python -m api.eval.seed_ats` primeiro.", file=sys.stderr)
        sys.exit(1)

    print(f"Gerando análise para {len(targets)} candidaturas com {args.workers} chamadas em paralelo…")
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(explain_one, application_id) for application_id in targets]
        for future in as_completed(futures):
            application_id, message = future.result()
            done += 1
            print(f"  [{done}/{len(targets)}] #{application_id} {message}")


if __name__ == "__main__":
    main()
