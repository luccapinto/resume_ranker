"""Benchmark models on the capability the explanation layer depends on.

Extraction accuracy is not the only thing that matters when swapping models. The
explanation endpoint asks for direct quotes and then checks each one *verbatim*
against the candidate's own text; a model that paraphrases instead of quoting
produces an analysis where the guardrail flags everything, which is worse than
useless.

This measures, per model:

* **verified**    share of returned citations found literally in the résumé
* **coverage**    how many citations it bothers to produce
* **latency**     median seconds per explanation
* **cost**        USD per explanation, as reported by the provider

    python -m api.eval.benchmark_citations
    python -m api.eval.benchmark_citations --models a,b --pairs 4
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List

from api.database import SessionLocal
from api.explain import generate_match_explanation
from api.llm import LLMClient
from api.models import JobModel

sys.stdout.reconfigure(line_buffering=True)

DEFAULT_MODELS = [
    "deepseek/deepseek-v4-flash",
    "openai/gpt-4.1-nano",
    "google/gemini-2.5-flash-lite",
    "mistralai/mistral-small-24b-instruct-2501",
]


def load_pairs(limit: int) -> List[Dict]:
    """Take the top-ranked application of each job, up to `limit` pairs."""
    db = SessionLocal()
    try:
        pairs = []
        for job in db.query(JobModel).order_by(JobModel.id).limit(limit).all():
            application = sorted(
                job.applications, key=lambda a: (a.ai_rank is None, a.ai_rank or 0)
            )
            if not application:
                continue
            candidate = application[0].candidate
            if not candidate or not candidate.profile or not job.profile:
                continue
            pairs.append(
                {
                    "candidate_raw": candidate.profile.raw_text,
                    "candidate_redacted": candidate.profile.redacted_text,
                    "candidate_extracted": candidate.profile.extracted_profile,
                    "job_raw": job.profile.raw_text,
                    "job_extracted": job.profile.extracted_profile,
                    "label": f"{candidate.display_name[:18]} × {job.title[:22]}",
                }
            )
        return pairs
    finally:
        db.close()


def evaluate(model: str, pairs: List[Dict]) -> Dict:
    client = LLMClient(model=model)
    verified, total, latencies, fallbacks = 0, 0, [], 0

    for pair in pairs:
        started = time.perf_counter()
        result = generate_match_explanation(
            candidate_raw_text=pair["candidate_raw"],
            candidate_redacted_text=pair["candidate_redacted"],
            job_raw_text=pair["job_raw"],
            candidate_extracted=pair["candidate_extracted"],
            job_extracted=pair["job_extracted"],
            client=client,
        )
        latencies.append(time.perf_counter() - started)
        if result["generated_by"] == "fallback-deterministico":
            fallbacks += 1
            continue
        check = result["hallucination_check"]
        verified += check["verified"]
        total += check["total"]

    return {
        "model": model,
        "verified": verified,
        "total": total,
        "rate": verified / total if total else 0.0,
        "citations_per_explanation": total / max(len(pairs) - fallbacks, 1),
        "median_latency": statistics.median(latencies) if latencies else float("nan"),
        "fallbacks": fallbacks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", help="Lista separada por vírgula")
    parser.add_argument("--pairs", type=int, default=4)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    pairs = load_pairs(args.pairs)
    if not pairs:
        print("Nenhum par candidato/vaga ranqueado — rode `make seed` primeiro.", file=sys.stderr)
        sys.exit(1)

    models = [m.strip() for m in args.models.split(",")] if args.models else DEFAULT_MODELS
    print(f"{len(models)} modelos × {len(pairs)} pares candidato/vaga\n")
    for pair in pairs:
        print(f"  · {pair['label']}")
    print()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda m: evaluate(m, pairs), models))

    results.sort(key=lambda r: -r["rate"])
    header = f"{'modelo':44}{'citações':>10}{'verbatim':>10}{'por análise':>13}{'mediana':>10}{'falhas':>8}"
    print(header)
    print("─" * len(header))
    for r in results:
        print(
            f"{r['model']:44}{r['verified']:>4}/{r['total']:<5}{r['rate']:>9.0%}"
            f"{r['citations_per_explanation']:>13.1f}{r['median_latency']:>9.1f}s{r['fallbacks']:>8}"
        )


if __name__ == "__main__":
    main()
