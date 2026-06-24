import pytest
from unittest.mock import patch, MagicMock
from qdrant_client.models import ScoredPoint

from api.explain import verify_citation, generate_match_explanation
from api.fairness import generate_counterfactual_text, run_counterfactual_bias_audit
from api.eval.run_harness import dcg_at_k, ndcg_at_k, mean_reciprocal_rank
import api.models
from api.embeddings import get_embedding_provider
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from api.database import Base, get_db
from api.main import app

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

# ----------------- 1. Test NDCG & MRR Math -----------------
def test_ndcg_and_mrr_math():
    """Validates the mathematical calculation of DCG, NDCG, and MRR using fixed vectors."""
    # Test case 1: relevance rankings
    # Retrieved relevance scores: [3, 2, 0, 0, 1]
    r = [3.0, 2.0, 0.0, 0.0, 1.0]
    
    # DCG calculation:
    # idx 0: rel=3 -> (2^3 - 1) / log2(2) = 7.0 / 1.0 = 7.0
    # idx 1: rel=2 -> (2^2 - 1) / log2(3) = 3.0 / 1.5849625 = 1.892789
    # idx 2: rel=0 -> 0
    # idx 3: rel=0 -> 0
    # idx 4: rel=1 -> (2^1 - 1) / log2(6) = 1.0 / 2.5849625 = 0.3868528
    # Total DCG = 7.0 + 1.892789 + 0.3868528 = 9.27964
    assert dcg_at_k(r, 5) == pytest.approx(7.0 + 3.0 / math.log2(3) + 1.0 / math.log2(6))
    
    # Ideal relevance scores (sorted descending): [3, 2, 1, 0, 0]
    ideal_r = [3.0, 2.0, 1.0, 0.0, 0.0]
    # Ideal DCG:
    # idx 0: rel=3 -> 7.0
    # idx 1: rel=2 -> 1.892789
    # idx 2: rel=1 -> (2^1 - 1) / log2(4) = 1.0 / 2.0 = 0.5
    # Total IDCG = 7.0 + 1.892789 + 0.5 = 9.392789
    # NDCG@5 = DCG@5 / IDCG@5 = 9.27964 / 9.392789 = 0.98795
    assert ndcg_at_k(r, 5, ideal_r) == pytest.approx(
        (7.0 + 3.0 / math.log2(3) + 1.0 / math.log2(6)) / (7.0 + 3.0 / math.log2(3) + 0.5)
    )
    
    # Test MRR:
    # Relevance >= 2.0 (relevant items are at index 0 and 1, first is index 0 -> rank 1 -> MRR = 1.0)
    assert mean_reciprocal_rank(r, threshold=2.0) == 1.0
    
    # Retrieved relevance scores: [0, 1, 2, 3, 0]
    # First relevant item (>=2) is at index 2 -> rank 3 -> MRR = 1/3 = 0.3333
    assert mean_reciprocal_rank([0.0, 1.0, 2.0, 3.0, 0.0], threshold=2.0) == pytest.approx(1.0 / 3.0)
    
    # No relevant items
    assert mean_reciprocal_rank([0.0, 1.0, 1.0, 0.0], threshold=2.0) == 0.0

import math

# ----------------- 2. Test Explainability Citation Guardrails -----------------
def test_citation_verification():
    """Checks the case/whitespace insensitive exact quote checking."""
    source = "João Silva é um Desenvolvedor Sênior Python com foco em microserviços e nuvem AWS."
    
    # Clean substring match
    assert verify_citation("Desenvolvedor Sênior Python", source) is True
    # Case mismatch (should pass)
    assert verify_citation("desenvolvedor sênior python", source) is True
    # Extra whitespace mismatch (should pass)
    assert verify_citation("  Desenvolvedor   Sênior \n Python ", source) is True
    # Mismatch text (should fail)
    assert verify_citation("desenvolvedor java", source) is False
    # Empty citation (should fail)
    assert verify_citation("", source) is False

def test_explain_endpoint_guardrail_simulation():
    """Simulates match explanation and verifies returned citation tags."""
    # Test fallback mode
    cand_extracted = {"experience_years": 5.0, "skills_normalized": [{"preferred_label": "Python"}]}
    job_extracted = {"experience_years": 5.0, "skills_normalized": [{"preferred_label": "Python"}]}
    
    res = generate_match_explanation(
        candidate_raw_text="João Silva, 5 anos de experiência com Python.",
        candidate_redacted_text="[NOME_1], 5 anos de experiência com Python.",
        job_raw_text="Requisitos: Python.",
        candidate_extracted=cand_extracted,
        job_extracted=job_extracted
    )
    
    assert "explanation" in res
    assert "citations" in res
    assert len(res["citations"]) > 0
    # The default mock citation should verify successfully
    assert res["citations"][0]["verified"] is True

# ----------------- 3. Test Counterfactual Term Swapping -----------------
def test_counterfactual_swapping():
    """Verifies that masculine names and pronouns are swapped to feminine equivalents."""
    text = "Sou o desenvolvedor João Silva. Ele trabalhou com infraestrutura."
    cf_text, swaps = generate_counterfactual_text(text)
    
    assert "desenvolvedora" in cf_text
    assert "Maria Silva" in cf_text
    assert "Ela trabalhou" in cf_text
    assert len(swaps) > 0

# ----------------- 4. Integration: Counterfactual Bias Audit -----------------
@patch("api.fairness.OpenRouterExtractor")
@patch("api.fairness.SkillNormalizer")
def test_bias_audit_integration(mock_norm, mock_ext, mock_qdrant):
    """Verifies the complete flow of counterfactual bias audit and delta scoring assertions."""
    db = TestingSessionLocal()
    
    # 1. Seed database profiles
    cand_db = api.models.ProfileModel(
        id=50,
        type="candidate",
        raw_text="Sou João Silva, programador experiente.",
        redacted_text="Sou [NOME], programador experiente.",
        extracted_profile={
            "seniority": "Pleno",
            "skills_raw": ["Python"],
            "skills_normalized": [{"original_term": "Python", "preferred_label": "Python", "concept_uri": "uri-py", "match_type": "exact", "score": 100.0}],
            "experience_years": 4.0,
            "certifications": [],
            "languages": [],
            "narrative_experience": "desenvolvedor experiente"
        }
    )
    job_db = api.models.ProfileModel(
        id=60,
        type="job",
        raw_text="Buscamos desenvolvedor Python.",
        redacted_text="Buscamos desenvolvedor Python.",
        extracted_profile={
            "seniority": "Pleno",
            "skills_raw": ["Python"],
            "skills_normalized": [{"original_term": "Python", "preferred_label": "Python", "concept_uri": "uri-py", "match_type": "exact", "score": 100.0}],
            "experience_years": 3.0,
            "certifications": [],
            "languages": [],
            "narrative_experience": "desenvolvedor Python"
        }
    )
    db.add(cand_db)
    db.add(job_db)
    db.commit()
    
    # Mock Qdrant Client Search response
    # Return same score for both original and counterfactual to verify delta < 1%
    mock_point_orig = ScoredPoint(id=9999999, version=1, score=0.95, payload={"narrative_experience": "desenvolvedor experiente"})
    mock_point_cf = ScoredPoint(id=8888888, version=1, score=0.95, payload={"narrative_experience": "desenvolvedora experiente"})
    
    mock_qdrant.search.side_effect = [
        [mock_point_orig, mock_point_cf], # skills search
        [mock_point_orig, mock_point_cf], # narrative search
        []                               # lexical search
    ]
    
    # Mock CrossEncoder
    with patch("api.search.get_cross_encoder") as mock_get_ce:
        mock_ce = MagicMock()
        mock_ce.predict.return_value = [0.95, 0.95]
        mock_get_ce.return_value = mock_ce
        
        mock_ext.extract.side_effect = Exception("API Key not found")
        
        mock_norm_result = MagicMock()
        mock_norm_result.preferred_label = "Python"
        mock_norm_result.concept_uri = "uri-py"
        mock_norm_result.match_type = "exact"
        mock_norm_result.score = 100.0
        mock_norm.normalize_skill.return_value = mock_norm_result
        
        provider = get_embedding_provider()
        redactor = MagicMock()
        redactor.redact.return_value = ("redacted text", {})
        
        result = run_counterfactual_bias_audit(
            db=db,
            qdrant_client=mock_qdrant,
            candidate_id=50,
            job_id=60,
            provider=provider,
            extractor=mock_ext,
            normalizer=mock_norm,
            redactor=redactor
        )
        
        # Verify delta is 0% and audit passes
        assert result["score_pct_delta"] == 0.0
        assert result["audit_passed"] is True
        
        # Verify log persisted in database
        log = db.query(api.models.AuditLogModel).filter(api.models.AuditLogModel.query_id == 60).first()
        assert log is not None
        assert log.bias_audit_passed == 1
        assert log.bias_audit_results["original_score"] == 0.95
