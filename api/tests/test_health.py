import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from api.main import app

client = TestClient(app)

def test_healthcheck_success():
    # We will mock the database and Qdrant connections to verify that the healthcheck endpoint works correctly
    # when both services are healthy.
    
    mock_db = MagicMock()
    # Mocking db.execute to not raise any exceptions
    mock_db.execute.return_value = None
    
    with patch("api.main.QdrantClient") as MockQdrantClient:
        mock_qdrant = MagicMock()
        mock_qdrant.get_collections.return_value = []
        MockQdrantClient.return_value = mock_qdrant
        
        # Override the dependency get_db
        from api.main import get_db
        app.dependency_overrides[get_db] = lambda: mock_db
        
        response = client.get("/health")
        
        # Clean up dependency overrides
        app.dependency_overrides.clear()
        
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "postgres": "connected",
            "qdrant": "connected"
        }

def test_healthcheck_postgres_failure():
    # Test that the endpoint returns 500 if Postgres is down
    mock_db = MagicMock()
    mock_db.execute.side_effect = Exception("Postgres connection timeout")
    
    with patch("api.main.QdrantClient") as MockQdrantClient:
        mock_qdrant = MagicMock()
        mock_qdrant.get_collections.return_value = []
        MockQdrantClient.return_value = mock_qdrant
        
        from api.main import get_db
        app.dependency_overrides[get_db] = lambda: mock_db
        
        response = client.get("/health")
        app.dependency_overrides.clear()
        
        assert response.status_code == 500
        data = response.json()
        assert data["detail"]["status"] == "unhealthy"
        assert "error: Postgres connection timeout" in data["detail"]["postgres"]
        assert data["detail"]["qdrant"] == "connected"

def test_healthcheck_qdrant_failure():
    # Test that the endpoint returns 500 if Qdrant is down
    mock_db = MagicMock()
    mock_db.execute.return_value = None
    
    with patch("api.main.QdrantClient") as MockQdrantClient:
        MockQdrantClient.side_effect = Exception("Qdrant connection refused")
        
        from api.main import get_db
        app.dependency_overrides[get_db] = lambda: mock_db
        
        response = client.get("/health")
        app.dependency_overrides.clear()
        
        assert response.status_code == 500
        data = response.json()
        assert data["detail"]["status"] == "unhealthy"
        assert data["detail"]["postgres"] == "connected"
        assert "error: Qdrant connection refused" in data["detail"]["qdrant"]

def test_healthcheck_live_integration():
    # Since we spin up Postgres and Qdrant in compose, this test tries to hit the real services.
    # If the docker services are healthy, this integration test should pass against the live containers.
    # If they are not running, it will return unhealthy but we can still assert that the structure is correct.
    response = client.get("/health")
    
    # We don't assert 200/500 here since in some environments it may be running or not, 
    # but we assert that the response JSON contains status, postgres, and qdrant keys.
    data = response.json()
    if response.status_code == 200:
        assert data["status"] == "ok"
        assert data["postgres"] == "connected"
        assert data["qdrant"] == "connected"
    else:
        assert response.status_code == 500
        detail = data["detail"]
        assert "status" in detail
        assert "postgres" in detail
        assert "qdrant" in detail
