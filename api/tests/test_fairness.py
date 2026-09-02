"""Counterfactual bias auditing across the four demographic axes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from api.fairness import (
    AXES,
    PASS_THRESHOLD_PCT,
    generate_counterfactual_text,
    run_counterfactual_bias_audit,
)
from api.models import AuditLogModel, ProfileModel


# ── Counterfactual generation ───────────────────────────────────────────────
def test_gender_axis_swaps_pronouns_and_titles():
    text = "O candidato é um desenvolvedor sênior. Ele é formado em engenharia."
    swapped, swaps = generate_counterfactual_text(text, "genero")
    assert "desenvolvedora" in swapped
    assert "Ela" in swapped or "ela" in swapped
    assert "formada" in swapped
    assert swaps


def test_swaps_respect_word_boundaries():
    """'Eleição' must not become 'elaição'."""
    swapped, _ = generate_counterfactual_text("Participou da eleição do time.", "genero")
    assert "eleição" in swapped


def test_name_axis_swaps_the_name_the_pii_layer_detected():
    """The axis must work on whoever the résumé is about, not a hard-coded list."""
    swapped, swaps = generate_counterfactual_text(
        "Tatiana Rezende Peixoto lidera o time. Tatiana atua com Kubernetes.",
        "nome",
        detected_names=["Tatiana Rezende Peixoto"],
    )
    assert "Tatiana" not in swapped
    assert swaps
    # Both the full name and the later given-name mention were replaced.
    assert sum(s["count"] for s in swaps) >= 2


def test_name_axis_falls_back_to_the_static_table():
    swapped, swaps = generate_counterfactual_text("João Silva trabalhou na área.", "nome")
    assert "João" not in swapped
    assert "Silva" not in swapped
    assert len(swaps) == 2


def test_institution_axis_matches_any_named_institution():
    """Real institutions are unbounded, so the axis matches the pattern."""
    for original in (
        "Universidade Nova Aurora",
        "Instituto de Tecnologia Avançada",
        "Pontifícia Universidade Católica",
    ):
        swapped, swaps = generate_counterfactual_text(
            f"Bacharelado - {original} | 2016", "instituicao"
        )
        assert original not in swapped, original
        assert swaps[0]["original"] == original


def test_institution_axis_falls_back_to_the_elite_list_for_acronyms():
    """USP and FGV are acronyms, not "Universidade X" — the static table covers them."""
    swapped, _ = generate_counterfactual_text("Bacharel pela USP, MBA na FGV.", "instituicao")
    assert "USP" not in swapped
    assert "FGV" not in swapped


def test_age_axis_shifts_graduation_years():
    swapped, _ = generate_counterfactual_text("Formado em 2020.", "idade")
    assert "2020" not in swapped


def test_no_applicable_markers_yields_no_swaps():
    _, swaps = generate_counterfactual_text("Trabalha com Python e SQL.", "nome")
    assert swaps == []


def test_an_unknown_axis_falls_back_to_gender():
    _, swaps = generate_counterfactual_text("O candidato é engenheiro.", "inexistente")
    assert swaps


def test_every_declared_axis_is_usable():
    for axis in AXES:
        text, _ = generate_counterfactual_text("Texto qualquer.", axis)
        assert isinstance(text, str)


# ── Audit ───────────────────────────────────────────────────────────────────
@pytest.fixture
def audit_fixtures(db_session):
    job = ProfileModel(
        type="job",
        raw_text="Vaga para desenvolvedor.",
        redacted_text="Vaga para desenvolvedor.",
        redaction_map={},
        extracted_profile={
            "skills_raw": ["Python"],
            "skills_normalized": [{"preferred_label": "Python", "concept_uri": "u/py"}],
            "narrative_experience": "Desenvolvimento de sistemas.",
        },
    )
    candidate = ProfileModel(
        type="candidate",
        raw_text="João Silva é um desenvolvedor sênior formado em 2015 pela USP. Ele lidera times.",
        redacted_text="[NOME_REDACT_1] é um desenvolvedor sênior.",
        redaction_map={"[NOME_REDACT_1]": "João Silva"},
        extracted_profile={
            "skills_raw": ["Python"],
            "skills_normalized": [{"preferred_label": "Python", "concept_uri": "u/py"}],
            "narrative_experience": "O candidato é um desenvolvedor sênior formado em 2015. Ele lidera times.",
        },
    )
    db_session.add_all([job, candidate])
    db_session.commit()
    return {"db": db_session, "job": job, "candidate": candidate}


def _run(fixtures, cross_encoder, fake_provider, **kwargs):
    with patch("api.fairness.get_cross_encoder", return_value=cross_encoder):
        return run_counterfactual_bias_audit(
            db=fixtures["db"],
            qdrant_client=MagicMock(),
            candidate_id=fixtures["candidate"].id,
            job_id=fixtures["job"].id,
            provider=fake_provider,
            extractor=MagicMock(),
            normalizer=MagicMock(),
            redactor=MagicMock(),
            **kwargs,
        )


def test_identical_scores_pass_every_axis(audit_fixtures, fake_provider):
    """A pipeline that ignores demographics scores both variants identically."""
    cross_encoder = MagicMock()
    cross_encoder.predict.side_effect = lambda pairs: [2.5] * len(pairs)

    result = _run(audit_fixtures, cross_encoder, fake_provider)

    assert result["audit_passed"] is True
    assert result["max_score_pct_delta"] == 0.0
    assert {a["axis"] for a in result["axes"]} == set(AXES)


def test_a_moved_score_fails_the_audit(audit_fixtures, fake_provider):
    """First doc is the original; every variant scores much lower → biased."""
    def predict(pairs):
        return [5.0] + [-5.0] * (len(pairs) - 1)

    cross_encoder = MagicMock()
    cross_encoder.predict.side_effect = predict

    result = _run(audit_fixtures, cross_encoder, fake_provider, axes=["genero"])

    assert result["audit_passed"] is False
    assert result["max_score_pct_delta"] > PASS_THRESHOLD_PCT
    assert result["axes"][0]["passed"] is False


def test_an_axis_without_markers_is_reported_as_not_applicable(audit_fixtures, fake_provider):
    audit_fixtures["candidate"].raw_text = "Profissional de tecnologia."
    audit_fixtures["candidate"].redaction_map = {}
    audit_fixtures["db"].commit()

    cross_encoder = MagicMock()
    cross_encoder.predict.side_effect = lambda pairs: [1.0] * len(pairs)

    result = _run(audit_fixtures, cross_encoder, fake_provider, axes=["nome"])

    axis = result["axes"][0]
    assert axis["applicable"] is False
    assert axis["passed"] is True
    assert "Nenhum marcador" in axis["reason"]


def test_a_marker_absent_from_the_extracted_text_is_reported_honestly(audit_fixtures, fake_provider):
    """A shallow audit that cannot change the scored document must say so."""
    audit_fixtures["candidate"].extracted_profile = {
        "skills_raw": ["Python"],
        "skills_normalized": [{"preferred_label": "Python", "concept_uri": "u/py"}],
        # No gendered marker here, though the résumé itself has one.
        "narrative_experience": "Atuou em plataformas de dados.",
    }
    audit_fixtures["db"].commit()

    cross_encoder = MagicMock()
    cross_encoder.predict.side_effect = lambda pairs: [1.0] * len(pairs)

    axis = _run(audit_fixtures, cross_encoder, fake_provider, axes=["genero"])["axes"][0]

    assert axis["applicable"] is False
    assert "auditoria profunda" in axis["reason"]


def test_the_audit_is_written_to_the_log(audit_fixtures, fake_provider):
    cross_encoder = MagicMock()
    cross_encoder.predict.side_effect = lambda pairs: [3.0] * len(pairs)

    _run(audit_fixtures, cross_encoder, fake_provider, axes=["genero"])

    log = audit_fixtures["db"].query(AuditLogModel).one()
    assert log.bias_audit_passed == 1
    assert log.bias_audit_results["axes"][0]["axis"] == "genero"
    assert log.reranker_model


def test_missing_profiles_raise_a_clear_error(db_session, fake_provider):
    with pytest.raises(ValueError, match="não encontrados"):
        run_counterfactual_bias_audit(
            db=db_session,
            qdrant_client=MagicMock(),
            candidate_id=1,
            job_id=2,
            provider=fake_provider,
            extractor=MagicMock(),
            normalizer=MagicMock(),
            redactor=MagicMock(),
        )


def test_deep_mode_reruns_the_extraction(audit_fixtures, fake_provider):
    """Deep mode puts the LLM extraction itself under audit."""
    cross_encoder = MagicMock()
    cross_encoder.predict.side_effect = lambda pairs: [1.0] * len(pairs)

    extractor = MagicMock()
    extracted = MagicMock()
    extracted.model_dump.return_value = {
        "skills_raw": ["Python"],
        "narrative_experience": "Liderou times.",
    }
    extractor.extract.return_value = extracted

    normalizer = MagicMock()
    normalizer.normalize_batch.return_value = []

    redactor = MagicMock()
    redactor.redact.return_value = ("texto anonimizado", {})

    with patch("api.fairness.get_cross_encoder", return_value=cross_encoder):
        run_counterfactual_bias_audit(
            db=audit_fixtures["db"],
            qdrant_client=MagicMock(),
            candidate_id=audit_fixtures["candidate"].id,
            job_id=audit_fixtures["job"].id,
            provider=fake_provider,
            extractor=extractor,
            normalizer=normalizer,
            redactor=redactor,
            axes=["genero"],
            deep=True,
        )

    extractor.extract.assert_called_once()
    redactor.redact.assert_called_once()


def test_the_audit_never_writes_to_qdrant(audit_fixtures, fake_provider):
    """Scoring happens in-process — the live collections must stay untouched."""
    qdrant = MagicMock()
    cross_encoder = MagicMock()
    cross_encoder.predict.side_effect = lambda pairs: [1.0] * len(pairs)

    with patch("api.fairness.get_cross_encoder", return_value=cross_encoder):
        run_counterfactual_bias_audit(
            db=audit_fixtures["db"],
            qdrant_client=qdrant,
            candidate_id=audit_fixtures["candidate"].id,
            job_id=audit_fixtures["job"].id,
            provider=fake_provider,
            extractor=MagicMock(),
            normalizer=MagicMock(),
            redactor=MagicMock(),
            axes=["genero"],
        )

    qdrant.upsert.assert_not_called()
    qdrant.delete.assert_not_called()


def test_the_shallow_audit_actually_changes_the_scored_document(audit_fixtures, fake_provider):
    """Reusing the original extraction verbatim would make every audit pass for free."""
    from api.fairness import _profile_doc_text, _swap_extracted_profile

    original = {
        "narrative_experience": "O candidato é um desenvolvedor sênior. Ele liderou o time.",
        "headline": "Desenvolvedor sênior",
        "skills_normalized": [{"preferred_label": "Python", "concept_uri": "u/py"}],
    }
    swapped = _swap_extracted_profile(original, "genero", detected_names=[])

    assert swapped["narrative_experience"] != original["narrative_experience"]
    assert "desenvolvedora" in swapped["narrative_experience"]
    assert _profile_doc_text(swapped) != _profile_doc_text(original)
    # The original must not be mutated in place.
    assert "desenvolvedor sênior" in original["narrative_experience"]


def test_the_shallow_swap_reaches_the_cross_encoder(audit_fixtures, fake_provider):
    """The reranker must receive two genuinely different documents."""
    seen: list[str] = []

    def predict(pairs):
        seen.extend(doc for _, doc in pairs)
        return [1.0] * len(pairs)

    cross_encoder = MagicMock()
    cross_encoder.predict.side_effect = predict

    _run(audit_fixtures, cross_encoder, fake_provider, axes=["genero"])

    # First doc is the original, second is the counterfactual.
    assert seen[0] != seen[1]
