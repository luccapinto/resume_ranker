import pytest
import fitz
import json
import concurrent.futures
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.main import app, get_db
from api.database import Base
from api.parser import extract_text_from_pdf, clean_text
from api.normalizer import SkillNormalizer, normalize_string
from api.schemas import SeniorityEnum

from sqlalchemy.pool import StaticPool

# ----------------- Database Setup for Testing -----------------
# We use an in-memory SQLite database for robust, real persistence testing.
# We configure StaticPool to ensure all connections share the same database instance and tables.
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if get_db in app.dependency_overrides:
        del app.dependency_overrides[get_db]

client = TestClient(app)

# ----------------- Helper to generate PDF -----------------
def generate_mock_pdf_bytes() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (50, 50), 
        "Nome do Candidato: John Doe\nE-mail: john.doe@email.com\nCPF: 123.456.789-00\nSkills: Python, JavaScript, CSS"
    )
    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes

# ----------------- Test Parser -----------------
def test_pdf_parser_and_cleaner():
    pdf_bytes = generate_mock_pdf_bytes()
    extracted_text = extract_text_from_pdf(pdf_bytes)
    
    assert "John Doe" in extracted_text
    assert "john.doe@email.com" in extracted_text
    assert "Python, JavaScript, CSS" in extracted_text
    
    # Test cleaning utility directly
    messy_text = "Hello \n\n\n World   with\tspaces"
    cleaned = clean_text(messy_text)
    assert cleaned == "Hello \n World with spaces"

# ----------------- Test Skill Normalizer -----------------
def test_skill_normalizer_phases():
    normalizer = SkillNormalizer()
    
    # Phase 1: Exact Match
    match_exact_pref = normalizer.normalize_skill("Python")
    assert match_exact_pref.match_type == "exact"
    assert match_exact_pref.preferred_label == "Python"
    assert match_exact_pref.concept_uri == "http://data.europa.eu/esco/skill/python"
    
    # Synonyms (AltLabels)
    match_exact_alt = normalizer.normalize_skill("py")
    assert match_exact_alt.match_type == "exact"
    assert match_exact_alt.preferred_label == "Python"
    
    # Case insensitivity & characters
    match_case = normalizer.normalize_skill("  jAVAsCrIpt  ")
    assert match_case.match_type == "exact"
    assert match_case.preferred_label == "JavaScript"
    
    # Phase 2: Fuzzy Match
    match_fuzzy = normalizer.normalize_skill("Pythn")  # missing 'o'
    assert match_fuzzy.match_type == "fuzzy"
    assert match_fuzzy.preferred_label == "Python"
    
    # Phase 3: Fallback by Embedding (lazy model loads here)
    # "postgres database" is not in altLabels or preferredLabel exactly,
    # but the sentence-transformer should match it to "PostgreSQL" via semantic similarity
    match_emb = normalizer.normalize_skill("postgres database")
    assert match_emb.match_type in ["exact", "fuzzy", "embedding"]
    if match_emb.match_type == "embedding":
        assert match_emb.preferred_label == "PostgreSQL"
        assert match_emb.score >= 75.0
        
    # Unmapped
    match_unmapped = normalizer.normalize_skill("abracadabra-random-word")
    assert match_unmapped.match_type == "unmapped"
    assert match_unmapped.concept_uri is None

# ----------------- Test Concurrency & Thread-Safety -----------------
def test_skill_normalizer_thread_safety():
    normalizer = SkillNormalizer()
    skills_to_test = ["Python", "JS", "Kubernetes", "Docker", "AWS", "abracadabra"] * 10
    
    def worker(skill):
        return normalizer.normalize_skill(skill)
        
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(worker, skills_to_test))
        
    assert len(results) == len(skills_to_test)
    assert results[0].preferred_label == "Python"
    assert results[1].preferred_label == "JavaScript"
    assert results[5].match_type == "unmapped"

# ----------------- Test Extraction & Persistence -----------------
@patch("api.extractor.httpx.Client")
def test_candidate_extraction_and_persistence(mock_httpx_client):
    # Setup mock response for OpenRouter structured output
    mock_response = MagicMock()
    mock_response.status_code = 200
    
    # This must follow the exact CandidateProfile Pydantic schema structure
    mock_extracted_profile = {
        "seniority": "Sênior",
        "skills_raw": ["Python", "React", "Docker", "abracadabra"],
        "experience_years": 5.5,
        "education": [
            {"degree": "Bacharelado", "field": "Ciência da Computação", "year": 2020}
        ],
        "certifications": ["AWS Certified Practitioner"],
        "languages": ["Português", "Inglês"],
        "narrative_experience": "Engenheiro de software sênior com vasta experiência em desenvolvimento backend usando Python e React."
    }
    
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(mock_extracted_profile)
                }
            }
        ]
    }
    
    # Configure the context manager of httpx.Client().post()
    mock_client_instance = MagicMock()
    mock_client_instance.post.return_value = mock_response
    mock_httpx_client.return_value.__enter__.return_value = mock_client_instance
    
    # We will test the API candidate endpoint
    pdf_bytes = generate_mock_pdf_bytes()
    
    # Setup openrouter key so it does not fail early
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "fake_key_for_testing"}):
        response = client.post(
            "/profiles/candidate",
            files={"file": ("curriculo.pdf", pdf_bytes, "application/pdf")}
        )
        
    assert response.status_code == 200
    data = response.json()
    
    assert data["id"] is not None
    assert data["type"] == "candidate"
    assert data["file_name"] == "curriculo.pdf"
    assert "[NOME_REDACT_1]" in data["redacted_text"]  # Verify PII was redacted
    assert "john.doe@email.com" not in data["redacted_text"]
    
    # Check that skills were normalized in the returned payload
    extracted = data["extracted_profile"]
    assert extracted["seniority"] == "Sênior"
    assert extracted["experience_years"] == 5.5
    
    skills_norm = extracted["skills_normalized"]
    assert len(skills_norm) == 4
    
    # Verify Python was mapped to ESCO Python preferred label
    python_norm = next(s for s in skills_norm if s["original_term"] == "Python")
    assert python_norm["preferred_label"] == "Python"
    assert python_norm["match_type"] == "exact"
    
    # Verify abracadabra is unmapped
    abra_norm = next(s for s in skills_norm if s["original_term"] == "abracadabra")
    assert abra_norm["match_type"] == "unmapped"

    # Verify database query retrieves the same profile
    get_response = client.get(f"/profiles/{data['id']}")
    assert get_response.status_code == 200
    get_data = get_response.json()
    assert get_data["file_name"] == "curriculo.pdf"
    assert get_data["extracted_profile"]["seniority"] == "Sênior"
