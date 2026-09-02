"""Measure where the reranker's decision boundary actually sits.

The 0–100 score a recruiter sees is a sigmoid over the cross-encoder logit, and
the midpoint of that sigmoid should not be guessed. This script scores every
judged candidate/job pair from the seed corpus, splits the raw logits by their
ground-truth relevance, and reports the threshold that best separates the two
classes — which is what `SCORE_MIDPOINT` in `api/search.py` is set to.

    python -m api.eval.calibrate_scores
"""

from __future__ import annotations

import statistics
from typing import List

from api.config import settings
from api.database import SessionLocal, get_qdrant
from api.embeddings import get_embedding_provider
from api.eval.run_harness import build_qrels
from api.models import ProfileModel
from api.search import (
    SCORE_MIDPOINT,
    SCORE_TEMPERATURE,
    build_profile_texts,
    hybrid_search_and_rerank,
    normalize_score,
)

RELEVANT_THRESHOLD = 2  # graded relevance ≥ 2 counts as "should be shortlisted"


def _describe(label: str, values: List[float]) -> None:
    ordered = sorted(values)
    n = len(ordered)
    print(
        f"{label:<14} n={n:<4} min={ordered[0]:7.2f}  p25={ordered[n // 4]:7.2f}  "
        f"mediana={statistics.median(ordered):7.2f}  p75={ordered[3 * n // 4]:7.2f}  "
        f"max={ordered[-1]:7.2f}"
    )


def main() -> None:
    db = SessionLocal()
    try:
        qrels = build_qrels(db)
        provider = get_embedding_provider()
        client = get_qdrant()

        relevant: List[float] = []
        irrelevant: List[float] = []

        for job_profile_id, judgements in qrels.items():
            job_profile = db.query(ProfileModel).filter(ProfileModel.id == job_profile_id).first()
            if not job_profile:
                continue
            texts = build_profile_texts(job_profile.extracted_profile or {})
            results = hybrid_search_and_rerank(
                client=client,
                collection="candidates",
                query_text=texts["narrative_text"],
                skills_text=texts["skills_text"],
                provider=provider,
                top_k_hybrid=40,
                top_n_final=40,
            )
            for result in results:
                bucket = (
                    relevant
                    if judgements.get(result["id"], 0) >= RELEVANT_THRESHOLD
                    else irrelevant
                )
                bucket.append(result["score"])

        if not relevant or not irrelevant:
            print("Sem julgamentos suficientes — rode `python -m api.eval.seed_ats` primeiro.")
            return

        print(f"Reranker: {settings.RERANKER_MODEL}\n")
        _describe("relevantes", relevant)
        _describe("irrelevantes", irrelevant)

        best_threshold, best_accuracy = SCORE_MIDPOINT, 0.0
        total = len(relevant) + len(irrelevant)
        low = int(min(min(relevant), min(irrelevant)) * 100)
        high = int(max(max(relevant), max(irrelevant)) * 100)
        for step in range(low, high + 1):
            threshold = step / 100
            correct = sum(1 for s in relevant if s >= threshold) + sum(
                1 for s in irrelevant if s < threshold
            )
            accuracy = correct / total
            if accuracy > best_accuracy:
                best_threshold, best_accuracy = threshold, accuracy

        print(
            f"\nLimiar ótimo medido: {best_threshold:.2f} "
            f"(acurácia de separação {best_accuracy:.1%})"
        )
        print(f"SCORE_MIDPOINT configurado: {SCORE_MIDPOINT} (temperatura {SCORE_TEMPERATURE})")
        print(
            f"→ score exibido no limiar medido: {normalize_score(best_threshold):.1f}/100"
        )
        print(
            f"→ mediana dos relevantes: {normalize_score(statistics.median(relevant)):.1f} · "
            f"mediana dos irrelevantes: {normalize_score(statistics.median(irrelevant)):.1f}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
