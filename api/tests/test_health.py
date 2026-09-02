"""Liveness and runtime configuration endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch



def _healthy_qdrant() -> MagicMock:
    qdrant = MagicMock()
    qdrant.get_collections.return_value = MagicMock(collections=[])
    return qdrant


def test_health_reports_ok_when_both_stores_answer(client):
    with patch("api.routers.health.get_qdrant", return_value=_healthy_qdrant()):
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "postgres": "connected", "qdrant": "connected"}


def test_health_fails_when_qdrant_is_down(client):
    qdrant = MagicMock()
    qdrant.get_collections.side_effect = Exception("connection refused")

    with patch("api.routers.health.get_qdrant", return_value=qdrant):
        response = client.get("/health")

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["status"] == "unhealthy"
    assert detail["postgres"] == "connected"
    assert "connection refused" in detail["qdrant"]


def test_health_fails_when_postgres_is_down(client, db_session):
    with (
        patch("api.routers.health.get_qdrant", return_value=_healthy_qdrant()),
        patch.object(db_session, "execute", side_effect=Exception("timeout")),
    ):
        response = client.get("/health")

    assert response.status_code == 500
    assert "timeout" in response.json()["detail"]["postgres"]


def test_config_exposes_the_running_stack(client):
    body = client.get("/config").json()
    assert set(body) == {
        "llm_model",
        "llm_configured",
        "llm_models_by_task",
        "embedding_provider",
        "embedding_model",
        "reranker_model",
        "vector_store",
    }
    assert body["vector_store"].startswith("qdrant://")


def test_config_reports_a_model_per_task(client):
    """Extraction and explanation are benchmarked separately and may differ."""
    by_task = client.get("/config").json()["llm_models_by_task"]
    assert set(by_task) == {"extraction", "explanation", "copilot"}
    assert all(model for model in by_task.values())


def test_the_openapi_document_is_served(client):
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "Resume Ranker ATS API"
    for path in ("/ats/overview", "/copilot/chat", "/observability/metrics"):
        assert path in spec["paths"]


def test_responses_carry_a_server_timing_header(client):
    response = client.get("/config")
    assert float(response.headers["X-Response-Time-Ms"]) >= 0
