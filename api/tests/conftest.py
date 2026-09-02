"""Shared fixtures.

Tests run against an in-memory SQLite database with the Qdrant client, the
embedding provider and the LLM all replaced by deterministic doubles — so the
suite is fast, offline and never spends tokens.
"""

from __future__ import annotations

import os
from typing import Dict, List
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("OPENROUTER_API_KEY", "")

import api.models  # noqa: F401,E402 — registers metadata
from api import observability as obs  # noqa: E402
from api.database import Base, get_db  # noqa: E402
from api.embeddings import EmbeddingProvider, _local_sparse_tokenize  # noqa: E402
from api.main import app  # noqa: E402

TEST_DB_URL = "sqlite:///:memory:"
engine_test = create_engine(
    TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)


class FakeEmbeddingProvider(EmbeddingProvider):
    """Deterministic hash-based embeddings — no model download, stable output."""

    DIM = 16

    @property
    def dimension(self) -> int:
        return self.DIM

    @property
    def name(self) -> str:
        return "fake:test"

    def get_dense_embedding(self, text: str) -> List[float]:
        vector = [0.0] * self.DIM
        for token in (text or "").lower().split():
            vector[hash(token) % self.DIM] += 1.0
        norm = sum(v * v for v in vector) ** 0.5 or 1.0
        return [v / norm for v in vector]

    def get_sparse_embedding(self, text: str) -> Dict[int, float]:
        return _local_sparse_tokenize(text)


@pytest.fixture
def fake_provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture(autouse=True)
def reset_tracer():
    """Traces are not persisted during tests unless a test opts in."""
    obs.set_sink(None)
    yield
    obs.set_sink(None)


@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=engine_test)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine_test)


@pytest.fixture
def client(db_session):
    """TestClient wired to the in-memory database."""

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def mock_qdrant():
    """A Qdrant double whose query_points returns whatever a test assigns."""
    mock = MagicMock()
    collections = MagicMock()
    collections.collections = []
    mock.get_collections.return_value = collections
    return mock


def make_point(point_id: int, score: float, payload: dict):
    """Build an object shaped like a Qdrant ScoredPoint."""
    point = MagicMock()
    point.id = point_id
    point.score = score
    point.payload = payload
    return point


def make_query_response(points):
    response = MagicMock()
    response.points = points
    return response
