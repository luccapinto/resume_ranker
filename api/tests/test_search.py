"""Retrieval engine: RRF maths, filters, indexing and the hybrid pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from qdrant_client.models import FieldCondition, Filter

from api.embeddings import _local_sparse_tokenize
from api.search import (
    SCORE_MIDPOINT,
    build_profile_texts,
    build_qdrant_filter,
    hybrid_search_and_rerank,
    ingest_profile,
    normalize_score,
    reciprocal_rank_fusion,
)
from api.tests.conftest import make_point, make_query_response


# ── RRF ─────────────────────────────────────────────────────────────────────
def test_rrf_uses_one_based_ranks():
    """The first document of a ranking must score w/(k+1), not w/k."""
    scores = reciprocal_rank_fusion([["a", "b"]], k=60)
    assert scores["a"] == pytest.approx(1 / 61)
    assert scores["b"] == pytest.approx(1 / 62)


def test_rrf_sums_across_strategies():
    scores = reciprocal_rank_fusion([["a", "b"], ["b", "a"]], k=60)
    # Both appear once at rank 1 and once at rank 2, so they tie.
    assert scores["a"] == pytest.approx(scores["b"])
    assert scores["a"] == pytest.approx(1 / 61 + 1 / 62)


def test_rrf_weights_shift_the_winner():
    """Doubling the weight of the second strategy must promote its top hit."""
    unweighted = reciprocal_rank_fusion([["a", "b"], ["b", "a"]], k=60)
    weighted = reciprocal_rank_fusion([["a", "b"], ["b", "a"]], k=60, weights=[0.5, 2.0])
    assert unweighted["a"] == pytest.approx(unweighted["b"])
    assert weighted["b"] > weighted["a"]


def test_rrf_missing_weight_defaults_to_one():
    scores = reciprocal_rank_fusion([["a"], ["a"]], k=60, weights=[2.0])
    assert scores["a"] == pytest.approx(2 / 61 + 1 / 61)


# ── Score normalisation ─────────────────────────────────────────────────────
def test_normalize_score_puts_50_at_the_measured_decision_boundary():
    """Score 50 must mean "the reranker judged this relevant", not "logit 0"."""
    assert normalize_score(SCORE_MIDPOINT) == pytest.approx(50.0)


def test_normalize_score_stays_bounded_and_monotonic():
    values = [normalize_score(x) for x in (-12.0, -8.0, -3.5, 0.0, 4.0)]
    assert values == sorted(values)
    assert 0.0 <= values[0] and values[-1] <= 100.0


def test_normalize_score_survives_overflow():
    assert normalize_score(-100000.0) == 0.0
    assert normalize_score(100000.0) == 100.0


# ── Filters ─────────────────────────────────────────────────────────────────
def test_build_qdrant_filter_returns_none_without_criteria():
    assert build_qdrant_filter() is None


def test_build_qdrant_filter_combines_criteria():
    q_filter = build_qdrant_filter(
        min_experience_years=5.0,
        required_certifications=["AWS Certified"],
        seniorities=["Sênior", "Pleno"],
    )
    assert isinstance(q_filter, Filter)
    assert len(q_filter.must) == 3
    keys = [c.key for c in q_filter.must if isinstance(c, FieldCondition)]
    assert keys == ["experience_years", "certifications", "seniority"]


# ── Text derivation ─────────────────────────────────────────────────────────
def test_build_profile_texts_prefers_normalized_labels():
    texts = build_profile_texts(
        {
            "skills_raw": ["k8s"],
            "skills_normalized": [{"preferred_label": "Kubernetes", "concept_uri": "u"}],
            "narrative_experience": "Operou clusters.",
            "certifications": ["CKA"],
        }
    )
    assert texts["skills_text"] == "Kubernetes"
    assert "CKA" in texts["lexical_text"]


def test_build_profile_texts_falls_back_to_raw_skills():
    texts = build_profile_texts({"skills_raw": ["Python", "SQL"], "narrative_experience": ""})
    assert texts["skills_text"] == "Python SQL"


# ── Sparse vectors ──────────────────────────────────────────────────────────
def test_sparse_tokenizer_drops_stopwords_and_weights_repeats():
    sparse = _local_sparse_tokenize("Python python de a com")
    # "de", "a" and "com" are stopwords; only "python" survives, seen twice.
    assert len(sparse) == 1
    assert list(sparse.values())[0] > 1.0


def test_sparse_tokenizer_handles_empty_text():
    assert _local_sparse_tokenize("") == {}


def test_sparse_tokenizer_keeps_technical_symbols():
    assert len(_local_sparse_tokenize("C++ C# CI/CD")) >= 3


# ── Ingestion ───────────────────────────────────────────────────────────────
def test_ingest_profile_writes_three_vectors(mock_qdrant, fake_provider):
    ingest_profile(
        mock_qdrant,
        42,
        "candidate",
        {
            "skills_raw": ["Python"],
            "skills_normalized": [
                {"preferred_label": "Python", "concept_uri": "http://esco/python"}
            ],
            "narrative_experience": "Construiu pipelines de dados.",
            "certifications": ["AWS"],
            "seniority": "Sênior",
            "experience_years": 8.0,
        },
        fake_provider,
    )

    mock_qdrant.upsert.assert_called_once()
    point = mock_qdrant.upsert.call_args.kwargs["points"][0]
    assert point.id == 42
    assert set(point.vector) == {"skills_vector", "narrative_vector", "lexical_vector"}
    assert len(point.vector["skills_vector"]) == fake_provider.dimension
    assert point.payload["candidate_id"] == 42
    assert point.payload["esco_skills_ids"] == ["http://esco/python"]
    assert point.payload["experience_years"] == 8.0


def test_ingest_profile_routes_jobs_to_the_jobs_collection(mock_qdrant, fake_provider):
    ingest_profile(mock_qdrant, 7, "job", {"skills_raw": ["Go"]}, fake_provider)
    assert mock_qdrant.upsert.call_args.kwargs["collection_name"] == "jobs"


# ── Hybrid search ───────────────────────────────────────────────────────────
def _payload(name: str) -> dict:
    return {"skills_text": name, "narrative_experience": f"Trabalhou com {name}."}


def test_hybrid_search_fuses_and_reranks(mock_qdrant, fake_provider):
    mock_qdrant.query_points.side_effect = [
        make_query_response([make_point(1, 0.9, _payload("Kafka")), make_point(2, 0.7, _payload("SQL"))]),
        make_query_response([make_point(2, 0.8, _payload("SQL")), make_point(3, 0.6, _payload("Go"))]),
        make_query_response([make_point(1, 0.5, _payload("Kafka"))]),
    ]

    cross_encoder = MagicMock()
    # Deliberately invert the RRF order: the reranker must win.
    cross_encoder.predict.return_value = [0.1, 0.2, 9.0]

    with patch("api.search.get_cross_encoder", return_value=cross_encoder):
        results = hybrid_search_and_rerank(
            client=mock_qdrant,
            collection="candidates",
            query_text="streaming",
            skills_text="Kafka",
            provider=fake_provider,
            top_k_hybrid=10,
            top_n_final=3,
        )

    assert [r["rank"] for r in results] == [1, 2, 3]
    assert results[0]["score"] == 9.0
    assert results[0]["reranked"] is True
    # The winner started lower in the RRF ordering — that is the point of reranking.
    assert results[0]["rrf_rank"] > 1
    assert 0 <= results[0]["score_normalized"] <= 100


def test_hybrid_search_records_which_strategy_found_each_result(mock_qdrant, fake_provider):
    mock_qdrant.query_points.side_effect = [
        make_query_response([make_point(1, 0.9, _payload("Kafka"))]),
        make_query_response([make_point(2, 0.8, _payload("SQL"))]),
        make_query_response([]),
    ]
    results = hybrid_search_and_rerank(
        client=mock_qdrant,
        collection="candidates",
        query_text="dados",
        skills_text="Kafka",
        provider=fake_provider,
        rerank=False,
    )
    by_id = {r["id"]: r for r in results}
    assert by_id[1]["strategy_ranks"] == {"skills": 1}
    assert by_id[2]["strategy_ranks"] == {"narrative": 1}


def test_hybrid_search_without_rerank_orders_by_rrf(mock_qdrant, fake_provider):
    mock_qdrant.query_points.side_effect = [
        make_query_response([make_point(1, 0.9, _payload("a")), make_point(2, 0.8, _payload("b"))]),
        make_query_response([make_point(1, 0.9, _payload("a"))]),
        make_query_response([]),
    ]
    results = hybrid_search_and_rerank(
        client=mock_qdrant,
        collection="candidates",
        query_text="x",
        skills_text="y",
        provider=fake_provider,
        rerank=False,
    )
    assert [r["id"] for r in results] == [1, 2]
    assert results[0]["reranked"] is False


def test_hybrid_search_survives_a_missing_collection(mock_qdrant, fake_provider):
    """A cold Qdrant must degrade to an empty result, not a 500."""
    mock_qdrant.query_points.side_effect = Exception("collection not found")
    results = hybrid_search_and_rerank(
        client=mock_qdrant,
        collection="candidates",
        query_text="x",
        skills_text="y",
        provider=fake_provider,
    )
    assert results == []
