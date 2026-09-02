"""PDF parsing, ESCO normalisation and the end-to-end ingestion route."""

from __future__ import annotations

import concurrent.futures
from unittest.mock import MagicMock, patch

import fitz
import pytest

from api.ats import IngestionService
from api.normalizer import SkillNormalizer, normalize_string
from api.parser import clean_text, extract_text_from_pdf
from api.schemas import CandidateProfile, SeniorityEnum


# ── Parser ──────────────────────────────────────────────────────────────────
def _pdf_bytes(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text)
    data = doc.write()
    doc.close()
    return data


def test_pdf_text_is_extracted():
    text = extract_text_from_pdf(
        _pdf_bytes("Nome: João Doe\nE-mail: joao@email.com\nSkills: Python, JavaScript")
    )
    assert "João Doe" in text
    assert "joao@email.com" in text


def test_clean_text_collapses_whitespace():
    assert clean_text("Olá \n\n\n Mundo   com\tespaços") == "Olá \n Mundo com espaços"


def test_clean_text_handles_empty_input():
    assert clean_text("") == ""


def test_a_corrupt_pdf_raises_a_clear_error():
    with pytest.raises(ValueError, match="Failed to parse PDF"):
        extract_text_from_pdf(b"isso nao e um pdf")


# ── Normalizer ──────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def normalizer() -> SkillNormalizer:
    return SkillNormalizer()


def test_normalize_string_keeps_technical_symbols():
    assert normalize_string("C++") == "c++"
    assert normalize_string("  CI/CD  ") == "cicd"
    assert normalize_string("Node.js!") == "nodejs"


@pytest.mark.parametrize(
    "term,expected",
    [
        ("Python", "Python"),
        ("k8s", "Kubernetes"),          # synonym
        ("ReactJS", "React"),           # synonym
        ("aprendizado de máquina", "Machine Learning"),  # pt-BR synonym
        ("engenharia de dados", "Data Engineering"),
    ],
)
def test_exact_matches_resolve_through_synonyms(normalizer, term, expected):
    result = normalizer.normalize_skill(term)
    assert result.preferred_label == expected
    assert result.match_type == "exact"
    assert result.score == 100.0


def test_a_typo_resolves_by_fuzzy_match(normalizer):
    result = normalizer.normalize_skill("Kubernets")
    assert result.preferred_label == "Kubernetes"
    assert result.match_type == "fuzzy"
    assert result.score >= 85.0


def test_an_unknown_skill_is_reported_as_unmapped(normalizer):
    result = normalizer.normalize_skill("Tecnologia Zorblax Quântica 9000")
    assert result.match_type == "unmapped"
    assert result.preferred_label is None


def test_empty_input_is_unmapped(normalizer):
    assert normalizer.normalize_skill("   ").match_type == "unmapped"


def test_normalize_batch_reports_coverage(normalizer):
    results = normalizer.normalize_batch(["Python", "SQL", "Zorblax Inexistente"])
    assert len(results) == 3
    assert sum(1 for r in results if r.match_type == "unmapped") == 1


def test_the_cache_preserves_the_original_term(normalizer):
    """Repeated lookups must not leak a previous caller's spelling."""
    first = normalizer.normalize_skill("PYTHON")
    second = normalizer.normalize_skill("python")
    assert first.original_term == "PYTHON"
    assert second.original_term == "python"
    assert first.concept_uri == second.concept_uri


def test_the_normalizer_is_thread_safe(normalizer):
    terms = ["Python", "k8s", "React", "SQL", "Docker"] * 6
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(normalizer.normalize_skill, terms))
    assert len(results) == len(terms)
    assert all(r.match_type != "unmapped" for r in results)


# ── Ingestion service ───────────────────────────────────────────────────────
@pytest.fixture
def ingestion(fake_provider):
    redactor = MagicMock()
    redactor.redact.return_value = (
        "[NOME_REDACT_1] atua com Python há 8 anos.",
        {"[NOME_REDACT_1]": "Ana Souza"},
    )

    extractor = MagicMock()
    extractor.extract.return_value = CandidateProfile(
        seniority=SeniorityEnum.SENIOR,
        skills_raw=["Python", "k8s"],
        experience_years=8.0,
        education=[],
        certifications=["AWS"],
        languages=["Português"],
        narrative_experience="Construiu pipelines.",
        headline="Engenheira de dados",
        current_title="Engenheira de Dados Sênior",
        highlights=["Reduziu latência em 90%"],
    )

    normalizer = SkillNormalizer()
    return IngestionService(redactor, extractor, normalizer)


def test_build_profile_persists_the_full_pipeline_output(db_session, ingestion, fake_provider):
    qdrant = MagicMock()
    with (
        patch("api.ats.get_qdrant", return_value=qdrant),
        patch("api.ats.get_embedding_provider", return_value=fake_provider),
    ):
        profile = ingestion.build_profile(
            db_session, "Ana Souza atua com Python há 8 anos.", "candidate"
        )

    assert profile.id is not None
    assert profile.redacted_text.startswith("[NOME_REDACT_1]")
    assert profile.redaction_map == {"[NOME_REDACT_1]": "Ana Souza"}
    assert profile.has_pdf is False

    normalized = profile.extracted_profile["skills_normalized"]
    assert {s["preferred_label"] for s in normalized} == {"Python", "Kubernetes"}
    qdrant.upsert.assert_called_once()


def test_the_raw_text_never_reaches_the_extractor(db_session, ingestion, fake_provider):
    """The PII boundary sits immediately before the model call."""
    raw = "Ana Souza, CPF 307.298.596-06, atua com Python."
    with (
        patch("api.ats.get_qdrant", return_value=MagicMock()),
        patch("api.ats.get_embedding_provider", return_value=fake_provider),
    ):
        ingestion.build_profile(db_session, raw, "candidate")

    sent_to_model = ingestion.extractor.extract.call_args.args[0]
    assert "Ana Souza" not in sent_to_model
    assert "307.298.596-06" not in sent_to_model


def test_a_qdrant_failure_rolls_back_the_profile(db_session, ingestion, fake_provider):
    """A half-ingested profile — in Postgres but not in the index — is worse than none."""
    from api.models import ProfileModel

    qdrant = MagicMock()
    qdrant.upsert.side_effect = RuntimeError("qdrant fora do ar")

    with (
        patch("api.ats.get_qdrant", return_value=qdrant),
        patch("api.ats.get_embedding_provider", return_value=fake_provider),
        pytest.raises(RuntimeError),
    ):
        ingestion.build_profile(db_session, "Ana Souza atua com Python.", "candidate")

    assert db_session.query(ProfileModel).count() == 0


def test_read_source_prefers_the_uploaded_pdf(ingestion):
    text = ingestion.read_source(_pdf_bytes("Conteúdo do PDF"), "cv.pdf", "texto ignorado")
    assert "Conteúdo do PDF" in text


def test_read_source_falls_back_to_plain_text(ingestion):
    assert ingestion.read_source(None, None, "só texto") == "só texto"


# ── HTTP surface ────────────────────────────────────────────────────────────
def test_ingestion_endpoint_requires_a_payload(client):
    response = client.post("/profiles/candidate", data={})
    assert response.status_code == 400


def test_ingestion_endpoint_rejects_non_pdf_uploads(client):
    response = client.post(
        "/profiles/candidate",
        files={"file": ("curriculo.docx", b"conteudo", "application/msword")},
    )
    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]


def test_skills_normalize_endpoint(client):
    response = client.post("/skills/normalize", json=["Python", "k8s"])
    assert response.status_code == 200
    labels = [s["preferred_label"] for s in response.json()]
    assert labels == ["Python", "Kubernetes"]


def test_redaction_placeholders_never_become_skills(db_session, ingestion, fake_provider):
    """The extractor sometimes lists [ORGANIZACAO_REDACT_1] as a competency."""
    from api.schemas import CandidateProfile, SeniorityEnum

    ingestion.extractor.extract.return_value = CandidateProfile(
        seniority=SeniorityEnum.PLENO,
        skills_raw=["Python", "[ORGANIZACAO_REDACT_1]", "  ", "Kubernetes"],
        experience_years=5.0,
        education=[],
        certifications=[],
        languages=["Português"],
        narrative_experience="Atuou em plataformas.",
        headline="Engenheiro de plataforma",
        current_title="SRE",
        highlights=[],
    )

    with (
        patch("api.ats.get_qdrant", return_value=MagicMock()),
        patch("api.ats.get_embedding_provider", return_value=fake_provider),
    ):
        profile = ingestion.build_profile(db_session, "texto qualquer", "candidate")

    assert profile.extracted_profile["skills_raw"] == ["Python", "Kubernetes"]
    labels = [s["original_term"] for s in profile.extracted_profile["skills_normalized"]]
    assert all("REDACT" not in label for label in labels)
