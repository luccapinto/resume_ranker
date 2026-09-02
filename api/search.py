"""Hybrid retrieval over Qdrant: three vectors, RRF fusion, cross-encoder rerank.

Each profile is indexed under three representations:

* `skills_vector`    — dense embedding of the ESCO-normalised skill labels
* `narrative_vector` — dense embedding of the free-form career narrative
* `lexical_vector`   — sparse bag-of-terms, for exact matches on tech and certs

The three rankings are fused with weighted Reciprocal Rank Fusion, then the
top-K is re-scored by a local cross-encoder. Every result carries the per-strategy
ranks that produced it, so the UI can explain *why* someone surfaced.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Union

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    Range,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from api import observability as obs
from api.config import settings
from api.embeddings import EmbeddingProvider

COLLECTIONS = ("candidates", "jobs")
DEFAULT_WEIGHTS = [1.0, 1.0, 0.5]

_cross_encoder_model = None


def get_cross_encoder():
    """Lazy-load the reranker; the first call pays the model download."""
    global _cross_encoder_model
    if _cross_encoder_model is None:
        from sentence_transformers import CrossEncoder

        _cross_encoder_model = CrossEncoder(settings.RERANKER_MODEL)
    return _cross_encoder_model


# Calibration of the 0–100 display scale, measured on the seed corpus with
# `python -m api.eval.calibrate_scores`: scanning every threshold, raw = -2.93
# separates judged-relevant from judged-irrelevant candidates with 95.2%
# accuracy. Anchoring the midpoint there makes "score ≥ 50" mean exactly "the
# reranker considers this candidate relevant", instead of an arbitrary sigmoid
# around zero that crushed every Portuguese résumé into single digits.
# The temperature spreads the two classes apart: with 1.8 the median relevant
# candidate lands near 75 and the median irrelevant one near 8.
SCORE_MIDPOINT = -2.9
SCORE_TEMPERATURE = 1.8


def normalize_score(raw: float) -> float:
    """Map a cross-encoder logit onto a calibrated 0–100 scale."""
    try:
        z = (float(raw) - SCORE_MIDPOINT) / SCORE_TEMPERATURE
        return round(100.0 / (1.0 + math.exp(-z)), 2)
    except (OverflowError, ValueError):
        return 0.0 if raw < SCORE_MIDPOINT else 100.0


def init_qdrant_collections(client: QdrantClient, dimension: int) -> None:
    existing = {c.name for c in client.get_collections().collections}
    for coll in COLLECTIONS:
        if coll in existing:
            continue
        client.create_collection(
            collection_name=coll,
            vectors_config={
                "skills_vector": VectorParams(size=dimension, distance=Distance.COSINE),
                "narrative_vector": VectorParams(size=dimension, distance=Distance.COSINE),
            },
            sparse_vectors_config={
                "lexical_vector": SparseVectorParams(index=SparseIndexParams(on_disk=False))
            },
        )


def _to_sparse(sparse_dict: Dict[int, float]) -> SparseVector:
    indices = sorted(sparse_dict.keys())
    return SparseVector(indices=indices, values=[sparse_dict[i] for i in indices])


def build_profile_texts(extracted_profile: dict) -> Dict[str, str]:
    """Derive the three text representations that get embedded."""
    skills_normalized = extracted_profile.get("skills_normalized") or []
    labels = [s.get("preferred_label") for s in skills_normalized if s.get("preferred_label")]
    skills_text = " ".join(labels) or " ".join(extracted_profile.get("skills_raw") or [])
    narrative_text = extracted_profile.get("narrative_experience") or ""
    certifications = extracted_profile.get("certifications") or []
    return {
        "skills_text": skills_text,
        "narrative_text": narrative_text,
        "lexical_text": f"{skills_text} {narrative_text} {' '.join(certifications)}".strip(),
    }


def ingest_profile(
    client: QdrantClient,
    profile_id: int,
    profile_type: str,
    extracted_profile: dict,
    provider: EmbeddingProvider,
) -> None:
    """Embed a profile under all three representations and upsert it."""
    collection = "candidates" if profile_type == "candidate" else "jobs"
    texts = build_profile_texts(extracted_profile)

    skills_normalized = extracted_profile.get("skills_normalized") or []
    esco_skills_ids = [s["concept_uri"] for s in skills_normalized if s.get("concept_uri")]
    certifications = extracted_profile.get("certifications") or []

    with obs.span(
        "vector.ingest", kind=obs.KIND_VECTOR, collection=collection, profile_id=profile_id
    ) as sp:
        with obs.span("embed.profile", kind=obs.KIND_EMBEDDING, vectors=3):
            skills_vector = provider.get_dense_embedding(texts["skills_text"])
            narrative_vector = provider.get_dense_embedding(texts["narrative_text"])
            sparse_dict = provider.get_sparse_embedding(texts["lexical_text"])

        payload = {
            "esco_skills_ids": esco_skills_ids,
            "seniority": extracted_profile.get("seniority"),
            "experience_years": float(extracted_profile.get("experience_years", 0.0) or 0.0),
            "certifications": certifications,
            "narrative_experience": texts["narrative_text"],
            "skills_text": texts["skills_text"],
            "languages": extracted_profile.get("languages") or [],
        }
        payload["candidate_id" if profile_type == "candidate" else "job_id"] = profile_id

        client.upsert(
            collection_name=collection,
            points=[
                PointStruct(
                    id=profile_id,
                    vector={
                        "skills_vector": skills_vector,
                        "narrative_vector": narrative_vector,
                        "lexical_vector": _to_sparse(sparse_dict),
                    },
                    payload=payload,
                )
            ],
        )
        sp.set(
            esco_skills=len(esco_skills_ids),
            sparse_terms=len(sparse_dict),
            dimension=len(skills_vector),
        )


def delete_profile_vectors(client: QdrantClient, profile_id: int, profile_type: str) -> None:
    collection = "candidates" if profile_type == "candidate" else "jobs"
    try:
        client.delete(collection_name=collection, points_selector=[profile_id])
    except Exception:  # noqa: BLE001 — best effort cleanup
        pass


def reciprocal_rank_fusion(
    rankings: List[List[Union[int, str]]],
    k: int = 60,
    weights: Optional[List[float]] = None,
) -> Dict[Union[int, str], float]:
    """RRF_score(d) = Σ_m  w_m / (k + rank_m(d)), ranks being 1-based."""
    scores: Dict[Union[int, str], float] = {}
    for i, ranking in enumerate(rankings):
        w = weights[i] if (weights and i < len(weights)) else 1.0
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + (w / (k + rank + 1))
    return scores


def build_qdrant_filter(
    min_experience_years: Optional[float] = None,
    required_certifications: Optional[List[str]] = None,
    seniorities: Optional[List[str]] = None,
) -> Optional[Filter]:
    must = []
    if min_experience_years is not None:
        must.append(FieldCondition(key="experience_years", range=Range(gte=min_experience_years)))
    if required_certifications:
        for cert in required_certifications:
            must.append(FieldCondition(key="certifications", match=MatchValue(value=cert)))
    if seniorities:
        must.append(FieldCondition(key="seniority", match=MatchAny(any=seniorities)))
    return Filter(must=must) if must else None


def _query(client: QdrantClient, collection: str, using: str, query, qdrant_filter, limit: int):
    """Run one named-vector query, tolerating collections that don't exist yet."""
    try:
        response = client.query_points(
            collection_name=collection,
            using=using,
            query=query,
            query_filter=qdrant_filter,
            limit=limit,
            with_payload=True,
        )
    except Exception as exc:  # noqa: BLE001
        obs.annotate(**{f"{using}_error": str(exc)[:200]})
        return []
    points = getattr(response, "points", response)
    return list(points) if points else []


def hybrid_search_and_rerank(
    client: QdrantClient,
    collection: str,
    query_text: str,
    skills_text: str,
    provider: EmbeddingProvider,
    qdrant_filter: Optional[Filter] = None,
    k_rrf: int = 60,
    top_k_hybrid: int = 20,
    top_n_final: int = 10,
    rerank: bool = True,
    weights: Optional[List[float]] = None,
) -> List[dict]:
    """Retrieve → fuse → rerank. Returns results ordered best-first."""
    weights = weights or DEFAULT_WEIGHTS

    with obs.span(
        "search.hybrid",
        kind=obs.KIND_VECTOR,
        collection=collection,
        top_k=top_k_hybrid,
        top_n=top_n_final,
        weights=weights,
        rerank=rerank,
        filtered=qdrant_filter is not None,
    ) as search_span:
        with obs.span("embed.query", kind=obs.KIND_EMBEDDING, vectors=3):
            query_skills_vector = provider.get_dense_embedding(skills_text)
            query_narrative_vector = provider.get_dense_embedding(query_text)
            query_lexical = provider.get_sparse_embedding(query_text)

        with obs.span("qdrant.query_points", kind=obs.KIND_VECTOR, strategies=3) as qs:
            res_skills = _query(
                client, collection, "skills_vector", query_skills_vector, qdrant_filter, top_k_hybrid
            )
            res_narrative = _query(
                client, collection, "narrative_vector", query_narrative_vector, qdrant_filter, top_k_hybrid
            )
            res_lexical = (
                _query(
                    client, collection, "lexical_vector", _to_sparse(query_lexical), qdrant_filter, top_k_hybrid
                )
                if query_lexical
                else []
            )
            qs.set(
                hits_skills=len(res_skills),
                hits_narrative=len(res_narrative),
                hits_lexical=len(res_lexical),
            )

        # Fuse, keeping per-strategy ranks so the UI can justify each result.
        points_map = {}
        strategy_ranks: Dict[Union[int, str], Dict[str, int]] = {}
        strategy_scores: Dict[Union[int, str], Dict[str, float]] = {}
        rankings = []

        for label, results in (
            ("skills", res_skills),
            ("narrative", res_narrative),
            ("lexical", res_lexical),
        ):
            ids = []
            for rank, p in enumerate(results, start=1):
                ids.append(p.id)
                points_map[p.id] = p
                strategy_ranks.setdefault(p.id, {})[label] = rank
                strategy_scores.setdefault(p.id, {})[label] = round(float(getattr(p, "score", 0.0) or 0.0), 4)
            rankings.append(ids)

        with obs.span("rrf.fuse", kind=obs.KIND_LOGIC, k=k_rrf, weights=weights) as fs:
            rrf_scores = reciprocal_rank_fusion(rankings, k=k_rrf, weights=weights)
            sorted_by_rrf = sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True)
            top_hybrid_points = [points_map[pid] for pid, _ in sorted_by_rrf[:top_k_hybrid]]
            fs.set(candidates_fused=len(rrf_scores), kept=len(top_hybrid_points))

        rrf_position = {pid: i + 1 for i, (pid, _) in enumerate(sorted_by_rrf)}

        def base_result(p, score: float, reranked: bool) -> dict:
            return {
                "id": p.id,
                "payload": p.payload,
                "rrf_score": rrf_scores[p.id],
                "score": score,
                "score_normalized": normalize_score(score) if reranked else round(score * 1000, 2),
                "reranked": reranked,
                "rrf_rank": rrf_position.get(p.id),
                "strategy_ranks": strategy_ranks.get(p.id, {}),
                "strategy_scores": strategy_scores.get(p.id, {}),
            }

        if rerank and top_hybrid_points:
            with obs.span(
                "rerank.cross_encoder",
                kind=obs.KIND_RERANK,
                model=settings.RERANKER_MODEL,
                pairs=len(top_hybrid_points),
            ) as rs:
                cross_encoder = get_cross_encoder()
                query_ce_text = f"{skills_text} {query_text}".strip()
                pairs = [
                    [
                        query_ce_text,
                        f"{p.payload.get('skills_text', '')} {p.payload.get('narrative_experience', '')}".strip(),
                    ]
                    for p in top_hybrid_points
                ]
                ce_scores = cross_encoder.predict(pairs)
                ce_scores = ce_scores.tolist() if hasattr(ce_scores, "tolist") else list(ce_scores)

                scored = [
                    base_result(p, float(ce_scores[i]), True) for i, p in enumerate(top_hybrid_points)
                ]
                scored.sort(key=lambda x: x["score"], reverse=True)
                results = scored[:top_n_final]

                moved = sum(
                    1
                    for i, r in enumerate(results, start=1)
                    if r["rrf_rank"] is not None and r["rrf_rank"] != i
                )
                rs.set(reordered_positions=moved)
        else:
            results = [base_result(p, rrf_scores[p.id], False) for p in top_hybrid_points][:top_n_final]

        for i, r in enumerate(results, start=1):
            r["rank"] = i

        search_span.set(returned=len(results))
        return results
