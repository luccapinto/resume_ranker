"""HTTP surface of the ATS: jobs, candidates, funnel and the kanban payload."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from api import ats
from api.models import STAGES, ApplicationModel, CandidateModel, JobModel, ProfileModel
from api.schemas import JobRequirements, SeniorityEnum


@pytest.fixture
def populated(db_session):
    job_profile = ProfileModel(
        type="job",
        raw_text="Vaga de plataforma.",
        redacted_text="Vaga de plataforma.",
        redaction_map={},
        extracted_profile={
            "role_title": "SRE Pleno",
            "must_have_skills": ["Kubernetes", "Terraform"],
            "nice_to_have_skills": ["Go"],
            "responsibilities": ["Manter SLOs"],
            "skills_normalized": [{"preferred_label": "Kubernetes", "concept_uri": "u/k8s"}],
            "narrative_experience": "Plataforma interna.",
            "seniority": "Pleno",
            "experience_years": 4.0,
        },
    )
    candidate_profile = ProfileModel(
        type="candidate",
        raw_text="Tatiana Reis\nOpera Kubernetes há 6 anos.",
        redacted_text="[NOME_REDACT_1]\nOpera Kubernetes há 6 anos.",
        redaction_map={"[NOME_REDACT_1]": "Tatiana Reis"},
        extracted_profile={
            "headline": "SRE",
            "skills_normalized": [{"preferred_label": "Kubernetes", "concept_uri": "u/k8s"}],
            "narrative_experience": "SRE em produção.",
            "seniority": "Pleno",
            "experience_years": 6.0,
            "certifications": ["CKA"],
            "languages": ["Português"],
            "highlights": ["Reduziu MTTR em 40%"],
        },
    )
    db_session.add_all([job_profile, candidate_profile])
    db_session.commit()

    job = JobModel(
        profile_id=job_profile.id,
        title="SRE Pleno",
        department="Plataforma",
        location="Remoto",
        seniority="Pleno",
        status="open",
    )
    candidate = CandidateModel(
        profile_id=candidate_profile.id,
        display_name="Tatiana Reis",
        headline="SRE",
        email="tatiana.reis@empresa.com",
    )
    db_session.add_all([job, candidate])
    db_session.commit()
    return {"db": db_session, "job": job, "candidate": candidate}


# ── Overview ────────────────────────────────────────────────────────────────
def test_overview_returns_stages_and_activity(client, populated):
    body = client.get("/ats/overview").json()
    assert body["jobs_open"] == 1
    assert body["candidates_total"] == 1
    assert [s["key"] for s in body["stages"]] == STAGES
    assert isinstance(body["recent_activity"], list)


# ── Jobs ────────────────────────────────────────────────────────────────────
def test_list_jobs_includes_the_funnel(client, populated):
    body = client.get("/ats/jobs").json()
    assert body[0]["title"] == "SRE Pleno"
    assert body[0]["must_have_skills"] == ["Kubernetes", "Terraform"]
    assert body[0]["applications_count"] == 0


def test_list_jobs_filters_by_status(client, populated):
    assert client.get("/ats/jobs?status=closed").json() == []


def test_get_job_embeds_the_source_profile(client, populated):
    body = client.get(f"/ats/jobs/{populated['job'].id}").json()
    assert body["profile"]["redacted_text"].startswith("Vaga")


def test_get_job_404s_for_an_unknown_id(client, populated):
    assert client.get("/ats/jobs/9999").status_code == 404


def test_job_status_transition(client, populated):
    job_id = populated["job"].id
    assert client.patch(f"/ats/jobs/{job_id}/status?status=paused").json()["status"] == "paused"
    assert client.patch(f"/ats/jobs/{job_id}/status?status=invalido").status_code == 400


def test_create_job_runs_the_pipeline(client, db_session, fake_provider):
    extracted = JobRequirements(
        seniority=SeniorityEnum.PLENO,
        skills_raw=["Go"],
        experience_years=3.0,
        education=[],
        certifications=[],
        languages=["Português"],
        narrative_experience="Backend em Go.",
        role_title="Engenheiro Backend Pleno",
        must_have_skills=["Go"],
        nice_to_have_skills=[],
        responsibilities=["Manter serviços"],
    )

    ingestion = MagicMock()
    ingestion.read_source.return_value = "Descrição da vaga de backend em Go."
    real_service = ats.IngestionService(
        MagicMock(**{"redact.return_value": ("texto anonimizado", {})}),
        MagicMock(**{"extract.return_value": extracted}),
        MagicMock(**{"normalize_batch.return_value": []}),
    )
    ingestion.build_profile.side_effect = lambda *a, **k: real_service.build_profile(*a, **k)

    with (
        patch("api.routers.ats.get_ingestion", return_value=ingestion),
        patch("api.ats.get_qdrant", return_value=MagicMock()),
        patch("api.ats.get_embedding_provider", return_value=fake_provider),
    ):
        response = client.post(
            "/ats/jobs",
            data={
                "text_content": "Descrição da vaga de backend em Go.",
                "meta": json.dumps({"department": "Engenharia", "location": "Remoto"}),
            },
        )

    assert response.status_code == 200
    body = response.json()
    # No title in meta → falls back to the title the model extracted.
    assert body["title"] == "Engenheiro Backend Pleno"
    assert body["department"] == "Engenharia"


def test_create_job_rejects_malformed_meta(client):
    response = client.post(
        "/ats/jobs", data={"text_content": "texto qualquer", "meta": "{não é json"}
    )
    assert response.status_code == 400
    assert "meta" in response.json()["detail"]


def test_create_job_requires_content(client):
    assert client.post("/ats/jobs", data={}).status_code == 400


# ── Candidates ──────────────────────────────────────────────────────────────
def test_list_candidates_masks_the_email(client, populated):
    body = client.get("/ats/candidates").json()
    assert body[0]["display_name"] == "Tatiana Reis"
    assert body[0]["email"].endswith("@empresa.com")
    assert "tatiana.reis" not in body[0]["email"]


def test_list_candidates_filters_by_query(client, populated):
    assert len(client.get("/ats/candidates?q=Tatiana").json()) == 1
    assert client.get("/ats/candidates?q=Fulano").json() == []


def test_get_candidate_includes_profile_and_applications(client, populated):
    body = client.get(f"/ats/candidates/{populated['candidate'].id}").json()
    assert body["highlights"] == ["Reduziu MTTR em 40%"]
    assert body["profile"]["redaction_map"] == {"[NOME_REDACT_1]": "Tatiana Reis"}
    assert body["applications"] == []


def test_get_candidate_404s(client, populated):
    assert client.get("/ats/candidates/9999").status_code == 404


# ── Applications ────────────────────────────────────────────────────────────
def test_board_groups_applications_by_stage(client, populated):
    application = ats.ensure_application(
        populated["db"], populated["candidate"].id, populated["job"].id
    )
    ats.move_application(populated["db"], application.id, "interview")

    body = client.get(f"/ats/jobs/{populated['job'].id}/applications").json()
    assert body["total"] == 1
    by_stage = {s["key"]: s for s in body["stages"]}
    assert len(by_stage["interview"]["applications"]) == 1
    assert by_stage["interview"]["applications"][0]["candidate"]["display_name"] == "Tatiana Reis"
    assert by_stage["sourced"]["applications"] == []


def test_stage_update_endpoint_and_timeline(client, populated):
    application = ats.ensure_application(
        populated["db"], populated["candidate"].id, populated["job"].id
    )

    response = client.patch(
        f"/ats/applications/{application.id}/stage",
        json={"stage": "offer", "note": "Aprovado no técnico", "actor": "Marina"},
    )
    assert response.status_code == 200
    assert response.json()["stage_label"] == "Proposta"

    timeline = client.get(f"/ats/applications/{application.id}").json()["timeline"]
    assert any(entry["actor"] == "Marina" for entry in timeline)


def test_stage_update_rejects_an_invalid_stage(client, populated):
    application = ats.ensure_application(
        populated["db"], populated["candidate"].id, populated["job"].id
    )
    response = client.patch(
        f"/ats/applications/{application.id}/stage", json={"stage": "contratadissimo"}
    )
    assert response.status_code == 400


def test_notes_are_appended_to_the_timeline(client, populated):
    application = ats.ensure_application(
        populated["db"], populated["candidate"].id, populated["job"].id
    )
    response = client.post(
        f"/ats/applications/{application.id}/notes",
        json={"content": "Disponível para começar em 30 dias.", "actor": "Camila"},
    )
    assert response.status_code == 200
    assert response.json()["type"] == "note"

    timeline = client.get(f"/ats/applications/{application.id}").json()["timeline"]
    assert any("30 dias" in (e["content"] or "") for e in timeline)


def test_application_404s(client, populated):
    assert client.get("/ats/applications/9999").status_code == 404


# ── Ranking route ───────────────────────────────────────────────────────────
def test_rank_route_persists_applications(client, populated, fake_provider):
    from api.tests.conftest import make_point, make_query_response

    qdrant = MagicMock()
    qdrant.query_points.side_effect = [
        make_query_response(
            [
                make_point(
                    populated["candidate"].profile_id,
                    0.9,
                    {"skills_text": "Kubernetes", "narrative_experience": "SRE"},
                )
            ]
        ),
        make_query_response([]),
        make_query_response([]),
    ]
    cross_encoder = MagicMock()
    cross_encoder.predict.return_value = [2.0]

    with (
        patch("api.ats.get_qdrant", return_value=qdrant),
        patch("api.ats.get_embedding_provider", return_value=fake_provider),
        patch("api.search.get_cross_encoder", return_value=cross_encoder),
    ):
        response = client.post(f"/ats/jobs/{populated['job'].id}/rank", json={"job_id": populated["job"].id, "top_n": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["results"][0]["candidate"]["display_name"] == "Tatiana Reis"
    assert body["trace_id"]
    assert populated["db"].query(ApplicationModel).count() == 1


def test_rank_route_404s_for_an_unknown_job(client, populated):
    assert client.post("/ats/jobs/9999/rank", json={"job_id": 9999}).status_code == 404


# ── Deletion ────────────────────────────────────────────────────────────────
def test_deleting_a_candidate_removes_the_document_and_the_vector(client, populated):
    """A dangling ProfileModel or Qdrant point would keep showing up in searches."""
    candidate_id = populated["candidate"].id
    profile_id = populated["candidate"].profile_id
    qdrant = MagicMock()

    with patch("api.routers.ats.get_qdrant", return_value=qdrant):
        assert client.delete(f"/ats/candidates/{candidate_id}").status_code == 200

    assert populated["db"].query(CandidateModel).count() == 0
    assert populated["db"].query(ProfileModel).filter(ProfileModel.id == profile_id).count() == 0
    qdrant.delete.assert_called_once()


def test_deleting_a_job_removes_the_document_and_the_vector(client, populated):
    job_id = populated["job"].id
    profile_id = populated["job"].profile_id
    qdrant = MagicMock()

    with patch("api.routers.ats.get_qdrant", return_value=qdrant):
        assert client.delete(f"/ats/jobs/{job_id}").status_code == 200

    assert populated["db"].query(JobModel).count() == 0
    assert populated["db"].query(ProfileModel).filter(ProfileModel.id == profile_id).count() == 0


def test_deleting_an_unknown_record_404s(client, populated):
    assert client.delete("/ats/jobs/9999").status_code == 404
    assert client.delete("/ats/candidates/9999").status_code == 404
