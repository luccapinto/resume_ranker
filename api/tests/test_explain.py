"""Explanation layer: deterministic signals and the citation guardrail."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from api.explain import (
    ExplanationSchema,
    compute_match_signals,
    generate_match_explanation,
    verify_citation,
)

RESUME = (
    "Ana Souza\n"
    "Engenheira de dados com 8 anos de experiência.\n"
    "Liderou a migração de batch para streaming com Apache Kafka, "
    "reduzindo a latência de 4 horas para 2 minutos."
)


# ── Citation guardrail ──────────────────────────────────────────────────────
def test_verify_citation_accepts_exact_quote():
    assert verify_citation("Liderou a migração de batch para streaming", RESUME)


def test_verify_citation_is_insensitive_to_case_and_whitespace():
    assert verify_citation("LIDEROU   a  migração\nde batch", RESUME)


def test_verify_citation_is_insensitive_to_accents():
    """Models routinely drop accents when quoting Portuguese."""
    assert verify_citation("Liderou a migracao de batch", RESUME)


def test_verify_citation_rejects_a_paraphrase():
    assert not verify_citation("Coordenou a transição para tempo real", RESUME)


def test_verify_citation_strips_surrounding_quotes():
    assert verify_citation('"Engenheira de dados"', RESUME)


def test_verify_citation_rejects_empty_input():
    assert not verify_citation("", RESUME)
    assert not verify_citation("qualquer coisa", "")


# ── Deterministic signals ───────────────────────────────────────────────────
def _candidate(skills, years=8.0, seniority="Sênior"):
    return {
        "skills_normalized": [{"preferred_label": s, "concept_uri": f"u/{s}"} for s in skills],
        "experience_years": years,
        "seniority": seniority,
    }


def _job(skills, years=5.0, seniority="Sênior", must_have=None):
    payload = _candidate(skills, years, seniority)
    payload["must_have_skills"] = must_have or []
    return payload


def test_signals_split_matched_and_missing_skills():
    signals = compute_match_signals(
        _candidate(["Python", "Kafka"]), _job(["Python", "Kafka", "Spark"])
    )
    assert signals["matched_skills"] == ["Kafka", "Python"]
    assert signals["missing_skills"] == ["Spark"]
    assert signals["skill_coverage"] == pytest.approx(2 / 3, abs=1e-3)


def test_signals_match_skills_regardless_of_case_and_accents():
    signals = compute_match_signals(
        _candidate(["experiência do usuário"]), _job(["Experiencia do Usuario"])
    )
    assert len(signals["matched_skills"]) == 1


def test_signals_track_must_have_coverage_separately():
    signals = compute_match_signals(
        _candidate(["Python"]), _job(["Python", "Kafka"], must_have=["Python", "Kafka"])
    )
    assert signals["must_have_matched"] == ["Python"]
    assert signals["must_have_missing"] == ["Kafka"]
    assert signals["must_have_coverage"] == pytest.approx(0.5)


def test_signals_compute_experience_and_seniority_gaps():
    signals = compute_match_signals(
        _candidate(["Python"], years=8.0, seniority="Sênior"),
        _job(["Python"], years=5.0, seniority="Pleno"),
    )
    assert signals["experience_delta_years"] == 3.0
    assert signals["meets_experience"] is True
    assert signals["seniority_gap"] == 1


def test_signals_flag_insufficient_experience():
    signals = compute_match_signals(
        _candidate(["Python"], years=2.0), _job(["Python"], years=5.0)
    )
    assert signals["meets_experience"] is False
    assert signals["experience_delta_years"] == -3.0


def test_signals_handle_a_job_with_no_skills():
    signals = compute_match_signals(_candidate(["Python"]), _job([]))
    assert signals["skill_coverage"] == 0.0
    assert signals["must_have_coverage"] is None


# ── Generation ──────────────────────────────────────────────────────────────
def _llm_returning(schema: ExplanationSchema) -> MagicMock:
    llm = MagicMock()
    llm.is_configured = True
    llm.model = "test/model"
    llm.structured.return_value = schema
    return llm


def test_generate_explanation_flags_unverified_citations():
    """A quote the model invented must be surfaced, not silently dropped."""
    llm = _llm_returning(
        ExplanationSchema(
            fit="forte",
            confidence=0.9,
            summary="Encaixe forte.",
            explanation="Tem a stack exigida.",
            strengths=["Kafka"],
            gaps=[],
            citations=[
                "Liderou a migração de batch para streaming",  # real
                "Certificada pela NASA em foguetes",            # invented
            ],
            interview_questions=["Como você monitorou o lag do Kafka?"],
        )
    )

    result = generate_match_explanation(
        candidate_raw_text=RESUME,
        candidate_redacted_text=RESUME,
        job_raw_text="Vaga de engenharia de dados.",
        candidate_extracted=_candidate(["Kafka"]),
        job_extracted=_job(["Kafka"]),
        client=llm,
    )

    assert [c["verified"] for c in result["citations"]] == [True, False]
    assert result["hallucination_check"] == {
        "total": 2,
        "verified": 1,
        "unverified": 1,
        "rate": 0.5,
    }


def test_generate_explanation_normalises_an_unknown_fit_label():
    llm = _llm_returning(
        ExplanationSchema(
            fit="EXCELENTE",  # not one of the three allowed labels
            confidence=2.5,   # out of range
            summary="s",
            explanation="e",
            strengths=[],
            gaps=[],
            citations=[],
            interview_questions=[],
        )
    )
    result = generate_match_explanation(
        RESUME, RESUME, "vaga", _candidate(["Kafka"]), _job(["Kafka"]), client=llm
    )
    assert result["fit"] == "moderado"
    assert result["confidence"] == 1.0


def test_generate_explanation_falls_back_when_the_llm_fails():
    """A provider outage must still produce a usable, honest answer."""
    llm = MagicMock()
    llm.is_configured = True
    llm.model = "test/model"
    llm.structured.side_effect = RuntimeError("502 do provedor")

    result = generate_match_explanation(
        RESUME, RESUME, "vaga", _candidate(["Kafka", "Python"]), _job(["Kafka"]), client=llm
    )

    assert result["generated_by"] == "fallback-deterministico"
    assert "502" in result["fallback_reason"]
    assert result["fit"] in {"forte", "moderado", "baixo"}
    assert result["signals"]["matched_skills"] == ["Kafka"]


def test_generate_explanation_falls_back_without_an_api_key():
    llm = MagicMock()
    llm.is_configured = False
    result = generate_match_explanation(
        RESUME, RESUME, "vaga", _candidate(["Kafka"]), _job(["Kafka"]), client=llm
    )
    assert result["generated_by"] == "fallback-deterministico"
    llm.structured.assert_not_called()
