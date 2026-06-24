import pytest
from unittest.mock import MagicMock, patch

@pytest.fixture(autouse=True)
def mock_qdrant():
    """Globally mocks QdrantClient to prevent real network calls during testing."""
    with patch("api.main.QdrantClient") as MockQdrantClient, \
         patch("api.search.QdrantClient") as MockSearchQdrantClient:
        
        mock_client = MagicMock()
        # mock collections list
        mock_collections_response = MagicMock()
        mock_collections_response.collections = []
        mock_client.get_collections.return_value = mock_collections_response
        
        MockQdrantClient.return_value = mock_client
        MockSearchQdrantClient.return_value = mock_client
        yield mock_client
