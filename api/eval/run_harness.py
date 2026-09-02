"""Information-retrieval evaluation of the ranking pipeline.

Relevance judgements come from the seed manifest: each synthetic résumé was
written to be a `forte` / `moderado` / `baixo` fit for one specific job, which
maps to graded relevance 3 / 2 / 0. Candidates written for a *different* job are
graded 0 for this one, so every job has a full judged pool.

    python -m api.eval.run_harness                 # compare configurations
    python -m api.eval.run_harness --json out.json # also write the raw numbers

Reported metrics: NDCG@5, NDCG@10 and MRR (first result with relevance ≥ 2).
"""

from __future__ import annotations

import argparse
import json
import math
import os
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from api.config import settings
from api.database import SessionLocal, get_qdrant
from api.embeddings import get_embedding_provider
from api.models import CandidateModel, JobModel, ProfileModel
from api.search import build_profile_texts, hybrid_search_and_rerank

FIT_TO_RELEVANCE = {"forte": 3, "moderado": 2, "baixo": 0}
SEED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "seed")


# ── Metrics ─────────────────────────────────────────────────────────────────
def dcg_at_k(relevances: List[float], k: int) -> float:
    return sum((2**rel - 1.0) / math.log2(i + 2.0) for i, rel in enumerate(relevances[:k]))


def ndcg_at_k(retrieved: List[float], k: int, ideal: List[float]) -> float:
    idcg = dcg_at_k(sorted(ideal, reverse=True), k)
    return dcg_at_k(retrieved, k) / idcg if idcg else 0.0


def reciprocal_rank(relevances: List[float], threshold: float = 2.0) -> float:
    for i, rel in enumerate(relevances):
        if rel >= threshold:
            return 1.0 / (i + 1.0)
    return 0.0


# ── Ground truth ────────────────────────────────────────────────────────────
def build_qrels(db: Session) -> Dict[int, Dict[int, int]]:
    """Map job profile id → {candidate profile id: graded relevance}."""
    manifest_path = os.path.join(SEED_DIR, "manifest.json")
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(
            "manifest.json não encontrado — rode `python -m api.eval.generate_seed_corpus` primeiro."
        )
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    jobs_by_title = {j.title: j for j in db.query(JobModel).all()}
    job_profile_by_slug = {
        spec["slug"]: jobs_by_title[spec["title"]].profile_id
        for spec in manifest["jobs"]
        if spec["title"] in jobs_by_title
    }

    profiles_by_file = {
        p.file_name: p.id
        for p in db.query(ProfileModel).filter(ProfileModel.type == "candidate").all()
    }

    qrels: Dict[int, Dict[int, int]] = {pid: {} for pid in job_profile_by_slug.values()}
    for spec in manifest["candidates"]:
        candidate_profile_id = profiles_by_file.get(f"{spec['slug']}.txt")
        if candidate_profile_id is None:
            continue
        target_job_profile = job_profile_by_slug.get(spec.get("job") or "")
        for job_profile_id in qrels:
            if job_profile_id == target_job_profile:
                qrels[job_profile_id][candidate_profile_id] = FIT_TO_RELEVANCE[spec["fit"]]
            else:
                # Written for another role (or an outlier) — irrelevant here.
                qrels[job_profile_id][candidate_profile_id] = 0
    return qrels


# ── Evaluation ──────────────────────────────────────────────────────────────
def evaluate(
    db: Session,
    qrels: Dict[int, Dict[int, int]],
    weights: Optional[List[float]],
    rerank: bool,
    top_k: int = 30,
    top_n: int = 10,
) -> Tuple[float, float, float, int]:
    provider = get_embedding_provider()
    client = get_qdrant()

    totals = [0.0, 0.0, 0.0]
    queries = 0

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
            top_k_hybrid=top_k,
            top_n_final=top_n,
            rerank=rerank,
            weights=weights,
        )

        retrieved = [float(judgements.get(r["id"], 0)) for r in results]
        ideal = [float(v) for v in judgements.values()]

        totals[0] += ndcg_at_k(retrieved, 5, ideal)
        totals[1] += ndcg_at_k(retrieved, 10, ideal)
        totals[2] += reciprocal_rank(retrieved)
        queries += 1

    if not queries:
        return 0.0, 0.0, 0.0, 0
    return totals[0] / queries, totals[1] / queries, totals[2] / queries, queries


# Labels are English because they end up in the README table.
SHIPPED = "RRF, default weights + cross-encoder"

CONFIGURATIONS = [
    ("Skills vector only (dense)", [1.0, 0.0, 0.0], False),
    ("Narrative vector only (dense)", [0.0, 1.0, 0.0], False),
    ("Lexical vector only (sparse)", [0.0, 0.0, 1.0], False),
    ("RRF, equal weights, no rerank", [1.0, 1.0, 1.0], False),
    ("RRF, default weights, no rerank", [1.0, 1.0, 0.5], False),
    (SHIPPED, [1.0, 1.0, 0.5], True),
    ("RRF, skills-heavy + cross-encoder", [1.5, 1.0, 0.5], True),
    ("RRF, narrative-heavy + cross-encoder", [1.0, 1.5, 0.5], True),
]


README_MARKER = "<!-- EVAL_TABLE -->"


def to_markdown(rows: List[dict], reranker: str, jobs: int, candidates: int, judgements: int) -> str:
    """Render the results as the table embedded in the README."""
    best5 = max(rows, key=lambda r: r["ndcg@5"])
    best10 = max(rows, key=lambda r: r["ndcg@10"])
    lines = [
        README_MARKER,
        "",
        "| Configuration | Weights | Rerank | NDCG@5 | NDCG@10 | MRR |",
        "|---|---|:---:|---:|---:|---:|",
    ]
    for row in rows:
        weights = ", ".join(f"{w:g}" for w in row["weights"])
        label = f"**{row['config']}** ← shipped" if row["config"] == SHIPPED else row["config"]
        cell5 = f"**{row['ndcg@5']:.4f}**" if row is best5 else f"{row['ndcg@5']:.4f}"
        cell10 = f"**{row['ndcg@10']:.4f}**" if row is best10 else f"{row['ndcg@10']:.4f}"
        lines.append(
            f"| {label} | `{weights}` | {'yes' if row['rerank'] else 'no'} | "
            f"{cell5} | {cell10} | {row['mrr']:.4f} |"
        )
    lines += [
        "",
        f"<sub>{jobs} queries · {candidates} candidates · {judgements} graded judgements · "
        f"reranker <code>{reranker}</code>. Best value per column in bold. "
        f"Regenerate with <code>make eval</code>.</sub>",
    ]
    return "\n".join(lines)


def update_readme(markdown: str) -> None:
    """Replace the table in the README, keeping everything around it intact."""
    readme = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "README.md"
    )
    with open(readme, encoding="utf-8") as f:
        content = f.read()

    start = content.find(README_MARKER)
    if start == -1:
        print(f"Marcador {README_MARKER} não encontrado no README; nada a atualizar.")
        return

    # The block runs until the next top-level separator.
    end = content.find("\n\nTwo findings", start)
    if end == -1:
        end = content.find("\n\n---", start)
    with open(readme, "w", encoding="utf-8") as f:
        f.write(content[:start] + markdown + content[end:])
    print("README atualizado com a tabela de avaliação.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", help="Caminho para gravar os resultados brutos")
    parser.add_argument("--readme", action="store_true", help="Atualiza a tabela no README.md")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        qrels = build_qrels(db)
        judged = sum(len(v) for v in qrels.values())
        candidates = db.query(CandidateModel).count()

        print(f"Reranker: {settings.RERANKER_MODEL}")
        print(f"Embeddings: {get_embedding_provider().name}")
        print(f"{len(qrels)} vagas · {candidates} candidatos · {judged} julgamentos de relevância\n")

        header = f"{'Configuration':<40}{'NDCG@5':>9}{'NDCG@10':>10}{'MRR':>8}"
        print(header)
        print("─" * len(header))

        rows = []
        for label, weights, rerank in CONFIGURATIONS:
            ndcg5, ndcg10, mrr, queries = evaluate(db, qrels, weights, rerank)
            rows.append(
                {
                    "config": label,
                    "weights": weights,
                    "rerank": rerank,
                    "ndcg@5": round(ndcg5, 4),
                    "ndcg@10": round(ndcg10, 4),
                    "mrr": round(mrr, 4),
                    "queries": queries,
                }
            )
            print(f"{label:<40}{ndcg5:>9.4f}{ndcg10:>10.4f}{mrr:>8.4f}")

        for metric in ("ndcg@5", "ndcg@10", "mrr"):
            best = max(rows, key=lambda r: r[metric])
            print(f"Melhor por {metric.upper():<8} {best['config']} ({best[metric]:.4f})")

        if args.readme:
            update_readme(
                to_markdown(
                    rows, settings.RERANKER_MODEL, len(qrels), candidates, judged
                )
            )

        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "reranker": settings.RERANKER_MODEL,
                        "embeddings": get_embedding_provider().name,
                        "jobs": len(qrels),
                        "candidates": candidates,
                        "results": rows,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            print(f"Resultados gravados em {args.json}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
