import pytest
import json
import math
import hashlib
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from qdrant_client.models import ScoredPoint

import api.models
from api.database import Base, get_db
from api.main import app
from api.embeddings import (
    _local_sparse_tokenize,
    get_embedding_provider,
    LocalEmbeddingProvider,
    OpenAIEmbeddingProvider,
    VoyageEmbeddingProvider
)
from api.search import (
    reciprocal_rank_fusion,
    build_qdrant_filter,
    ingest_profile,
    hybrid_search_and_rerank
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Database Setup for Testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine_test = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine_test)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if get_db in app.dependency_overrides:
        del app.dependency_overrides[get_db]

# ----------------- 1. Test RRF Mathematics -----------------
def test_rrf_math():
    """
    Validates the mathematical calculation of Reciprocal Rank Fusion (RRF).
    Calculates expected values using formula: 1 / (60 + rank)
    """
    # Rankings from 3 simulated search runs
    # Candidate A: rank 1 (skills), rank 2 (narrative), rank 3 (lexical)
    # Candidate B: rank 2 (skills), rank 1 (narrative), not in lexical
    # Candidate C: not in skills, rank 3 (narrative), rank 1 (lexical)
    rankings = [
        ["A", "B"],         # skills
        ["B", "A", "C"],    # narrative
        ["C", "A"]          # lexical
    ]
    
    k = 60
    scores = reciprocal_rank_fusion(rankings, k=k)
    
    # Expected scores calculation:
    # A: 1/(60+1) + 1/(60+2) + 1/(60+2) = 1/61 + 1/62 + 1/62 = 0.01639344 + 0.01612903 + 0.01612903 = 0.0486515
    # B: 1/(60+2) + 1/(60+1) = 1/62 + 1/61 = 0.01612903 + 0.01639344 = 0.03252247
    # C: 1/(60+3) + 1/(60+1) = 1/63 + 1/61 = 0.01587301 + 0.01639344 = 0.03226645
    
    assert scores["A"] == pytest.approx(1/61 + 1/62 + 1/62)
    assert scores["B"] == pytest.approx(1/62 + 1/61)
    assert scores["C"] == pytest.approx(1/63 + 1/61)
    
    # Sort and assert ranking order: A > B > C
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    assert sorted_scores[0][0] == "A"
    assert sorted_scores[1][0] == "B"
    assert sorted_scores[2][0] == "C"


# ----------------- 2. Test Local Sparse Tokenizer -----------------
def test_sparse_embedding_tokenization():
    """
    Validates that the local sparse tokenizer correctly tokenizes, handles Technical terms,
    uses log frequency scaling, and computes correct stable hash indexes.
    """
    text = "Python, JS, React, Python, C++, C#!"
    vector = _local_sparse_tokenize(text)
    
    # "python": 2 times
    # "js": 1 time
    # "react": 1 time
    # "c++": 1 time
    # "c#": 1 time
    assert len(vector) == 5
    
    # Calculate hashes
    hash_python = int(hashlib.md5(b"python").hexdigest(), 16) % 1000000
    hash_js = int(hashlib.md5(b"js").hexdigest(), 16) % 1000000
    hash_cpp = int(hashlib.md5(b"c++").hexdigest(), 16) % 1000000
    hash_csharp = int(hashlib.md5(b"c#").hexdigest(), 16) % 1000000
    
    assert hash_python in vector
    assert hash_js in vector
    assert hash_cpp in vector
    assert hash_csharp in vector
    
    # Verify TF log-scaling (1.0 + ln(count))
    assert vector[hash_python] == pytest.approx(1.0 + math.log(2))
    assert vector[hash_js] == pytest.approx(1.0 + math.log(1))
    assert vector[hash_cpp] == pytest.approx(1.0 + math.log(1))


# ----------------- 3. Test Embedding Provider Factory & Switching -----------------
def test_embedding_provider_switching(monkeypatch):
    """Validates that get_embedding_provider instantiates the configured subclass based on env settings."""
    from api.config import settings
    
    # 1. Local
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "local")
    provider = get_embedding_provider()
    assert isinstance(provider, LocalEmbeddingProvider)
    
    # 2. OpenAI
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "fake-key")
    provider = get_embedding_provider()
    assert isinstance(provider, OpenAIEmbeddingProvider)
    assert provider.dimension == 1536
    
    # 3. Voyage
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "voyage")
    monkeypatch.setattr(settings, "VOYAGE_API_KEY", "fake-key")
    provider = get_embedding_provider()
    assert isinstance(provider, VoyageEmbeddingProvider)
    assert provider.dimension == 1024


# ----------------- 4. Test Qdrant Filter Builder -----------------
def test_build_qdrant_filter():
    """Validates that Qdrant filters are correctly constructed from parameters."""
    from qdrant_client.models import Range, MatchValue, MatchAny
    
    # Empty filter
    assert build_qdrant_filter() is None
    
    # Full filter
    q_filter = build_qdrant_filter(
        min_experience_years=5.0,
        required_certifications=["AWS Practitioner"],
        seniorities=["Sênior"]
    )
    
    assert q_filter is not None
    assert len(q_filter.must) == 3
    
    # Check experience filter
    exp_cond = next(c for c in q_filter.must if c.key == "experience_years")
    assert isinstance(exp_cond.range, Range)
    assert exp_cond.range.gte == 5.0
    
    # Check certifications filter
    cert_cond = next(c for c in q_filter.must if c.key == "certifications")
    assert isinstance(cert_cond.match, MatchValue)
    assert cert_cond.match.value == "AWS Practitioner"
    
    # Check seniority filter
    sen_cond = next(c for c in q_filter.must if c.key == "seniority")
    assert isinstance(sen_cond.match, MatchAny)
    assert sen_cond.match.any == ["Sênior"]


# ----------------- 5. Test Qdrant Ingestion -----------------
def test_qdrant_ingestion(mock_qdrant):
    """Validates that ingest_profile converts payloads and uploads correct points."""
    extracted = {
        "seniority": "Sênior",
        "skills_raw": ["Python", "Docker"],
        "skills_normalized": [
            {"original_term": "Python", "preferred_label": "Python", "concept_uri": "uri-py", "match_type": "exact", "score": 100.0}
        ],
        "experience_years": 8.0,
        "certifications": ["AWS Practitioner"],
        "narrative_experience": "Vasta trajetória no backend."
    }
    
    provider = get_embedding_provider()
    # Mock embeddings generation to avoid calling sentence-transformers or network
    with patch.object(provider, "get_dense_embedding", return_value=[0.1]*384), \
         patch.object(provider, "get_sparse_embedding", return_value={100: 1.0}):
         
        ingest_profile(
            client=mock_qdrant,
            profile_id=456,
            profile_type="candidate",
            extracted_profile=extracted,
            provider=provider
        )
        
        # Check call arguments
        mock_qdrant.upsert.assert_called_once()
        args = mock_qdrant.upsert.call_args[1]
        
        assert args["collection_name"] == "candidates"
        point = args["points"][0]
        
        assert point.id == 456
        assert "skills_vector" in point.vector
        assert "narrative_vector" in point.vector
        assert "lexical_vector" in point.vector
        
        payload = point.payload
        assert payload["seniority"] == "Sênior"
        assert payload["experience_years"] == 8.0
        assert payload["certifications"] == ["AWS Practitioner"]
        assert payload["candidate_id"] == 456
        assert payload["esco_skills_ids"] == ["uri-py"]


# ----------------- 6. Test Hybrid Search + Reranker -----------------
@patch("api.search.get_cross_encoder")
def test_hybrid_search_and_reranker(mock_get_ce, mock_qdrant):
    """Validates that RRF search results are forwarded and ranked correctly by the CrossEncoder."""
    # Qdrant search mocked results
    mock_skills_res = [
        ScoredPoint(id=1, version=1, score=0.9, payload={"narrative_experience": "Desc 1", "skills_text": "Python"}),
        ScoredPoint(id=2, version=1, score=0.8, payload={"narrative_experience": "Desc 2", "skills_text": "Java"})
    ]
    mock_narrative_res = [
        ScoredPoint(id=2, version=1, score=0.95, payload={"narrative_experience": "Desc 2", "skills_text": "Java"}),
        ScoredPoint(id=1, version=1, score=0.7, payload={"narrative_experience": "Desc 1", "skills_text": "Python"})
    ]
    mock_lexical_res = [] # empty lexical
    
    mock_qdrant.search.side_effect = [
        mock_skills_res,
        mock_narrative_res,
        mock_lexical_res
    ]
    
    # Mock CrossEncoder predict
    mock_ce = MagicMock()
    # Mock CE assigns 0.95 score to point 2 and 0.50 score to point 1
    mock_ce.predict.return_value = [0.50, 0.95]
    mock_get_ce.return_value = mock_ce
    
    provider = get_embedding_provider()
    with patch.object(provider, "get_dense_embedding", return_value=[0.1]*384), \
         patch.object(provider, "get_sparse_embedding", return_value={}):
         
        results = hybrid_search_and_rerank(
            client=mock_qdrant,
            collection="candidates",
            query_text="Java developer query",
            skills_text="Java",
            provider=provider,
            rerank=True
        )
        
        # Verify result count
        assert len(results) == 2
        
        # Verify reranked sorting: point 2 must come first (score 0.95 > 0.50)
        assert results[0]["id"] == 2
        assert results[0]["score"] == 0.95
        assert results[1]["id"] == 1
        assert results[1]["score"] == 0.50
# ----------------- 7. Integration: API Endpoint Route Testing -----------------
@patch("api.main.OpenRouterExtractor")
@patch("api.main.SkillNormalizer")
def test_matching_endpoints(mock_normalizer, mock_extractor, mock_qdrant):
    """Tests the /matching/candidates and /matching/jobs endpoints routing and payload enrichment."""
    # Seed database profiles
    db = TestingSessionLocal()
    
    # Insert candidate profile
    cand_db = api.models.ProfileModel(
        id=10,
        type="candidate",
        raw_text="Cand raw text",
        redacted_text="Cand redacted",
        extracted_profile={
            "seniority": "Sênior",
            "skills_raw": ["Python"],
            "skills_normalized": [{"original_term": "Python", "preferred_label": "Python", "concept_uri": "uri-py", "match_type": "exact", "score": 100.0}],
            "experience_years": 5.0,
            "certifications": ["AWS Practitioner"],
            "languages": ["English"],
            "narrative_experience": "Backend developer trajectory"
        }
    )
    # Insert job profile
    job_db = api.models.ProfileModel(
        id=20,
        type="job",
        raw_text="Job raw text",
        redacted_text="Job redacted",
        extracted_profile={
            "seniority": "Sênior",
            "skills_raw": ["Python"],
            "skills_normalized": [{"original_term": "Python", "preferred_label": "Python", "concept_uri": "uri-py", "match_type": "exact", "score": 100.0}],
            "experience_years": 4.0,
            "certifications": ["AWS Practitioner"],
            "languages": ["English"],
            "narrative_experience": "Backend developer vacancy"
        }
    )
    db.add(cand_db)
    db.add(job_db)
    db.commit()
    
    # Mock Qdrant Client Search inside endpoint
    mock_point = ScoredPoint(
        id=10,
        version=1,
        score=0.92,
        payload={
            "narrative_experience": "Backend developer trajectory",
            "skills_text": "Python",
            "candidate_id": 10
        }
    )
    mock_qdrant.search.side_effect = [
        [mock_point], # skills
        [mock_point], # narrative
        []            # lexical
    ]
    
    # Mock CrossEncoder
    with patch("api.search.get_cross_encoder") as mock_get_ce:
        mock_ce = MagicMock()
        mock_ce.predict.return_value = [0.92]
        mock_get_ce.return_value = mock_ce
        
        # Test client query
        test_client = TestClient(app)
        response = test_client.post("/matching/candidates?job_id=20")
        print("MATCHING RESPONSE:", response.status_code, response.text)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == 10
        assert data[0]["score"] == 0.92
        assert data[0]["profile"]["extracted_profile"]["seniority"] == "Sênior"
