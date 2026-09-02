"""ATS domain: identity recovery, funnel moves and the ranking snapshot."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from api import ats
from api.models import ApplicationModel, CandidateModel, JobModel, ProfileModel
from api.tests.conftest import make_point, make_query_response


# ── Identity recovery ───────────────────────────────────────────────────────
def _profile(**overrides) -> ProfileModel:
    defaults = dict(
        id=1,
        type="candidate",
        raw_text="Ana Souza\nana@exemplo.com",
        redacted_text="[NOME_REDACT_1]\n[EMAIL_REDACT_1]",
        redaction_map={
            "[NOME_REDACT_1]": "Ana Souza",
            "[EMAIL_REDACT_1]": "ana@exemplo.com",
            "[TELEFONE_REDACT_1]": "(11) 98765-4321",
        },
        extracted_profile={},
    )
    defaults.update(overrides)
    return ProfileModel(**defaults)


def test_identity_is_recovered_from_the_redaction_map():
    """The recruiter's screen gets the real name — the model never did."""
    identity = ats.derive_identity(_profile())
    assert identity["display_name"] == "Ana Souza"
    assert identity["email"] == "ana@exemplo.com"
    assert identity["phone"] == "(11) 98765-4321"


def test_identity_falls_back_to_the_first_résumé_line():
    profile = _profile(raw_text="Carlos Mendes\nEngenheiro\n", redaction_map={})
    assert ats.derive_identity(profile)["display_name"] == "Carlos Mendes"


def test_identity_falls_back_to_an_anonymous_label():
    profile = _profile(id=9, raw_text="joao@x.com 11999999999", redaction_map={})
    assert ats.derive_identity(profile)["display_name"] == "Candidato #9"


def test_mask_email_keeps_the_domain_visible():
    assert ats.mask_email("anabeatriz@empresa.com").endswith("@empresa.com")
    assert "anabeatriz" not in ats.mask_email("anabeatriz@empresa.com")


def test_mask_email_passes_through_non_emails():
    assert ats.mask_email(None) is None
    assert ats.mask_email("sem-arroba") == "sem-arroba"


# ── Fit thresholds ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "score,expected",
    [(95.0, "forte"), (75.0, "forte"), (74.9, "moderado"), (50.0, "moderado"), (49.9, "baixo")],
)
def test_fit_thresholds(score, expected):
    assert ats.fit_from_score(score) == expected


# ── Funnel ──────────────────────────────────────────────────────────────────
@pytest.fixture
def seeded(db_session):
    """One job, one candidate, one application."""
    job_profile = ProfileModel(
        type="job",
        raw_text="Vaga de dados",
        redacted_text="Vaga de dados",
        redaction_map={},
        extracted_profile={
            "skills_raw": ["Python"],
            "skills_normalized": [{"preferred_label": "Python", "concept_uri": "u/py"}],
            "narrative_experience": "Pipeline de dados.",
            "experience_years": 5.0,
            "seniority": "Sênior",
        },
    )
    candidate_profile = ProfileModel(
        type="candidate",
        raw_text="Ana Souza faz pipelines em Python.",
        redacted_text="[NOME_REDACT_1] faz pipelines em Python.",
        redaction_map={"[NOME_REDACT_1]": "Ana Souza"},
        extracted_profile={
            "skills_raw": ["Python"],
            "skills_normalized": [{"preferred_label": "Python", "concept_uri": "u/py"}],
            "narrative_experience": "Construiu pipelines.",
            "experience_years": 8.0,
            "seniority": "Sênior",
        },
    )
    db_session.add_all([job_profile, candidate_profile])
    db_session.commit()

    job = JobModel(profile_id=job_profile.id, title="Engenheira de Dados", status="open")
    candidate = CandidateModel(profile_id=candidate_profile.id, display_name="Ana Souza")
    db_session.add_all([job, candidate])
    db_session.commit()
    return {"db": db_session, "job": job, "candidate": candidate, "candidate_profile": candidate_profile}


def test_ensure_application_is_idempotent(seeded):
    first = ats.ensure_application(seeded["db"], seeded["candidate"].id, seeded["job"].id)
    second = ats.ensure_application(seeded["db"], seeded["candidate"].id, seeded["job"].id)
    assert first.id == second.id
    assert seeded["db"].query(ApplicationModel).count() == 1


def test_move_application_records_the_transition(seeded):
    application = ats.ensure_application(seeded["db"], seeded["candidate"].id, seeded["job"].id)
    moved = ats.move_application(seeded["db"], application.id, "interview", note="Bom fit")

    assert moved.stage == "interview"
    entries = [a for a in moved.activities if a.type == "stage_change"]
    assert len(entries) == 1
    assert entries[0].payload == {"from": "sourced", "to": "interview"}
    assert "Bom fit" in entries[0].content


def test_move_application_rejects_an_unknown_stage(seeded):
    application = ats.ensure_application(seeded["db"], seeded["candidate"].id, seeded["job"].id)
    with pytest.raises(ValueError, match="Estágio inválido"):
        ats.move_application(seeded["db"], application.id, "entrevistado")


def test_funnel_counts_every_stage(seeded):
    application = ats.ensure_application(seeded["db"], seeded["candidate"].id, seeded["job"].id)
    ats.move_application(seeded["db"], application.id, "offer")
    counts = ats.funnel_counts(seeded["db"], seeded["job"].id)
    assert counts["offer"] == 1
    assert counts["sourced"] == 0


# ── Ranking ─────────────────────────────────────────────────────────────────
def test_rank_job_persists_the_ai_snapshot(seeded, fake_provider):
    db = seeded["db"]
    profile_id = seeded["candidate_profile"].id

    qdrant = MagicMock()
    qdrant.query_points.side_effect = [
        make_query_response(
            [make_point(profile_id, 0.9, {"skills_text": "Python", "narrative_experience": "pipelines"})]
        ),
        make_query_response([]),
        make_query_response([]),
    ]
    cross_encoder = MagicMock()
    cross_encoder.predict.return_value = [4.0]

    with (
        patch("api.ats.get_qdrant", return_value=qdrant),
        patch("api.ats.get_embedding_provider", return_value=fake_provider),
        patch("api.search.get_cross_encoder", return_value=cross_encoder),
    ):
        outcome = ats.rank_job(db, job_id=seeded["job"].id, top_n=5)

    assert len(outcome["results"]) == 1
    entry = outcome["results"][0]
    assert entry["rank"] == 1
    assert entry["fit"] == "forte"  # sigmoid(4.0) ≈ 98
    assert entry["candidate"]["display_name"] == "Ana Souza"

    application = db.query(ApplicationModel).one()
    assert application.ai_rank == 1
    assert application.ai_fit == "forte"
    assert application.ai_matched_skills == ["Python"]
    assert application.ranked_at is not None


def test_rank_job_raises_for_an_unknown_job(seeded):
    with pytest.raises(ValueError, match="não encontrada"):
        ats.rank_job(seeded["db"], job_id=9999)


def test_rank_job_skips_vectors_without_an_ats_candidate(seeded, fake_provider):
    """A profile indexed in Qdrant but absent from the ATS must not crash ranking."""
    qdrant = MagicMock()
    qdrant.query_points.side_effect = [
        make_query_response([make_point(424242, 0.9, {"skills_text": "x", "narrative_experience": "y"})]),
        make_query_response([]),
        make_query_response([]),
    ]
    cross_encoder = MagicMock()
    cross_encoder.predict.return_value = [1.0]

    with (
        patch("api.ats.get_qdrant", return_value=qdrant),
        patch("api.ats.get_embedding_provider", return_value=fake_provider),
        patch("api.search.get_cross_encoder", return_value=cross_encoder),
    ):
        outcome = ats.rank_job(seeded["db"], job_id=seeded["job"].id)

    assert outcome["results"] == []


def test_pipeline_overview_aggregates_the_funnel(seeded):
    application = ats.ensure_application(seeded["db"], seeded["candidate"].id, seeded["job"].id)
    application.ai_score = 88.0
    application.ai_fit = "forte"
    seeded["db"].commit()

    overview = ats.pipeline_overview(seeded["db"])
    assert overview["jobs_open"] == 1
    assert overview["candidates_total"] == 1
    assert overview["applications_total"] == 1
    assert overview["avg_ai_score"] == 88.0
    assert overview["strong_fit_count"] == 1


# ── Display-layer helpers ───────────────────────────────────────────────────
@pytest.mark.parametrize(
    "value,expected",
    [
        ("Ana Beatriz Mendes", True),
        ("FELIPE AUGUSTO DE OLIVEIRA", True),   # résumé headers are often shouted
        ("João da Silva", True),
        ("Kimball", False),                     # single word
        ("DAGs", False),
        ("Machine Learning", False),            # a real ESCO competency
        ("Retrieval-Augmented Generation", False),
        ("joao@empresa.com", False),
        ("Rua das Flores 123", False),
        ("", False),
    ],
)
def test_person_name_detection(value, expected):
    assert ats.looks_like_person_name(value) is expected


def test_all_caps_names_are_rendered_normally():
    assert ats._titleize("FELIPE AUGUSTO DE OLIVEIRA") == "Felipe Augusto de Oliveira"
    assert ats._titleize("Ana Beatriz Mendes") == "Ana Beatriz Mendes"


def test_rehydrate_restores_placeholders_for_display():
    """The model writes about [ORGANIZACAO_REDACT_1]; the recruiter reads the company."""
    text = "Atuou na [ORGANIZACAO_REDACT_1] em [LOCALIZACAO_REDACT_2]."
    restored = ats.rehydrate(
        text,
        {"[ORGANIZACAO_REDACT_1]": "DataFlow", "[LOCALIZACAO_REDACT_2]": "Curitiba"},
    )
    assert restored == "Atuou na DataFlow em Curitiba."


def test_rehydrate_leaves_unknown_placeholders_intact():
    assert ats.rehydrate("Olá [NOME_REDACT_9].", {"[NOME_REDACT_1]": "Ana"}) == "Olá [NOME_REDACT_9]."


def test_rehydrate_passes_through_empty_input():
    assert ats.rehydrate(None, {"a": "b"}) is None
    assert ats.rehydrate("texto", {}) == "texto"


def test_summarize_cuts_on_a_word_boundary():
    long_text = "palavra " * 60
    result = ats.summarize(long_text, limit=40)
    assert len(result) <= 41
    assert result.endswith("…")
    assert "palavr…" not in result


def test_summarize_leaves_short_text_alone():
    assert ats.summarize("Engenheira de dados sênior") == "Engenheira de dados sênior"


def test_clean_labels_drops_bare_placeholders():
    """A redacted company is not a skill, and showing the token reads as a bug."""
    labels = ats.clean_labels(
        ["Kubernetes", "[ORGANIZACAO_REDACT_2]", "  ", "AWS na [LOCALIZACAO_REDACT_1]"],
        {"[ORGANIZACAO_REDACT_2]": "DataFlow", "[LOCALIZACAO_REDACT_1]": "Curitiba"},
    )
    assert labels == ["Kubernetes", "AWS na Curitiba"]


def test_clean_labels_handles_missing_input():
    assert ats.clean_labels(None, {}) == []
    assert ats.clean_labels([], {"a": "b"}) == []
