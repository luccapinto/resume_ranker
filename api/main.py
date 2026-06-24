import os
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import text
from qdrant_client import QdrantClient
from typing import Optional, List

from api.database import get_db, Base, engine
from api.config import settings
import api.models  # Ensures SQLAlchemy registers models for metadata creation
from api.schemas import CandidateProfile, JobRequirements
from api.parser import extract_text_from_pdf
from api.redactor import PIIRedactor
from api.extractor import OpenRouterExtractor
from api.normalizer import SkillNormalizer

app = FastAPI(
    title="Resume Ranker API",
    description="Backend API for Resume Ranker platform - Candidate & Job extraction and normalization",
    version="0.1.0"
)

# Global helper instances
redactor = PIIRedactor()
extractor = OpenRouterExtractor()
normalizer = SkillNormalizer()

@app.on_event("startup")
def on_startup():
    try:
        Base.metadata.create_all(bind=engine)
        print("Database tables initialized successfully.")
    except Exception as e:
        print(f"Error creating database tables: {e}")

@app.get("/health")
def healthcheck(db: Session = Depends(get_db)):
    postgres_status = "disconnected"
    qdrant_status = "disconnected"
    
    # Check Postgres
    try:
        db.execute(text("SELECT 1"))
        postgres_status = "connected"
    except Exception as e:
        postgres_status = f"error: {str(e)}"
        
    # Check Qdrant
    try:
        qdrant_client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        qdrant_client.get_collections()
        qdrant_status = "connected"
    except Exception as e:
        qdrant_status = f"error: {str(e)}"
        
    is_healthy = postgres_status == "connected" and qdrant_status == "connected"
    
    status_code = 200 if is_healthy else 500
    
    response_body = {
        "status": "ok" if is_healthy else "unhealthy",
        "postgres": postgres_status,
        "qdrant": qdrant_status
    }
    
    if not is_healthy:
        raise HTTPException(status_code=status_code, detail=response_body)
        
    return response_body

@app.post("/profiles/candidate", response_model=dict)
def create_candidate_profile(
    file: Optional[UploadFile] = File(None),
    text_content: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Ingests a candidate resume (either via PDF file upload or direct text content),
    redacts PII, extracts a structured profile via OpenRouter, and normalizes skills
    against the ESCO database, returning and storing the profile.
    """
    if not file and not text_content:
        raise HTTPException(status_code=400, detail="Either a file (PDF) or text_content must be provided.")
        
    raw_text = ""
    file_name = None
    
    if file:
        file_name = file.filename
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported.")
        try:
            file_bytes = file.file.read()
            raw_text = extract_text_from_pdf(file_bytes)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse PDF: {str(e)}")
    else:
        raw_text = text_content
        
    if not raw_text or not raw_text.strip():
        raise HTTPException(status_code=400, detail="No readable text found.")
        
    # 1. PII Redaction
    try:
        redacted_text, redaction_map = redactor.redact(raw_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PII Redaction failed: {str(e)}")
        
    # 2. Structured Extraction using OpenRouter LLM
    try:
        profile = extractor.extract(redacted_text, CandidateProfile)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM Extraction failed: {str(e)}")
        
    # 3. Normalization of extracted skills
    skills_normalized = []
    if profile.skills_raw:
        try:
            skills_normalized = [
                normalizer.normalize_skill(skill).model_dump()
                for skill in profile.skills_raw
            ]
        except Exception as e:
            print(f"Error normalizing skills during candidate ingest: {e}")
            
    # Enrich the profile payload
    profile_dict = profile.model_dump()
    profile_dict["skills_normalized"] = skills_normalized
    
    # 4. Save to Database
    db_profile = api.models.ProfileModel(
        type="candidate",
        file_name=file_name,
        raw_text=raw_text,
        redacted_text=redacted_text,
        redaction_map=redaction_map,
        extracted_profile=profile_dict
    )
    
    try:
        db.add(db_profile)
        db.commit()
        db.refresh(db_profile)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database persistence failed: {str(e)}")
        
    return {
        "id": db_profile.id,
        "type": db_profile.type,
        "file_name": db_profile.file_name,
        "raw_text": db_profile.raw_text,
        "redacted_text": db_profile.redacted_text,
        "redaction_map": db_profile.redaction_map,
        "extracted_profile": db_profile.extracted_profile,
        "created_at": db_profile.created_at
    }

@app.post("/profiles/job", response_model=dict)
def create_job_profile(
    file: Optional[UploadFile] = File(None),
    text_content: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Ingests a job description (either via PDF file upload or direct text content),
    redacts PII, extracts structured requirements via OpenRouter, and normalizes skills
    against the ESCO database, returning and storing the profile.
    """
    if not file and not text_content:
        raise HTTPException(status_code=400, detail="Either a file (PDF) or text_content must be provided.")
        
    raw_text = ""
    file_name = None
    
    if file:
        file_name = file.filename
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported.")
        try:
            file_bytes = file.file.read()
            raw_text = extract_text_from_pdf(file_bytes)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse PDF: {str(e)}")
    else:
        raw_text = text_content
        
    if not raw_text or not raw_text.strip():
        raise HTTPException(status_code=400, detail="No readable text found.")
        
    # 1. PII Redaction
    try:
        redacted_text, redaction_map = redactor.redact(raw_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PII Redaction failed: {str(e)}")
        
    # 2. Structured Extraction using OpenRouter LLM
    try:
        profile = extractor.extract(redacted_text, JobRequirements)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM Extraction failed: {str(e)}")
        
    # 3. Normalization of extracted skills
    skills_normalized = []
    if profile.skills_raw:
        try:
            skills_normalized = [
                normalizer.normalize_skill(skill).model_dump()
                for skill in profile.skills_raw
            ]
        except Exception as e:
            print(f"Error normalizing skills during job ingest: {e}")
            
    # Enrich the profile payload
    profile_dict = profile.model_dump()
    profile_dict["skills_normalized"] = skills_normalized
    
    # 4. Save to Database
    db_profile = api.models.ProfileModel(
        type="job",
        file_name=file_name,
        raw_text=raw_text,
        redacted_text=redacted_text,
        redaction_map=redaction_map,
        extracted_profile=profile_dict
    )
    
    try:
        db.add(db_profile)
        db.commit()
        db.refresh(db_profile)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database persistence failed: {str(e)}")
        
    return {
        "id": db_profile.id,
        "type": db_profile.type,
        "file_name": db_profile.file_name,
        "raw_text": db_profile.raw_text,
        "redacted_text": db_profile.redacted_text,
        "redaction_map": db_profile.redaction_map,
        "extracted_profile": db_profile.extracted_profile,
        "created_at": db_profile.created_at
    }

@app.get("/profiles/{profile_id}", response_model=dict)
def get_profile(profile_id: int, db: Session = Depends(get_db)):
    """
    Retrieves a stored profile by ID, including its original raw/redacted text and extracted schema.
    """
    db_profile = db.query(api.models.ProfileModel).filter(api.models.ProfileModel.id == profile_id).first()
    if not db_profile:
        raise HTTPException(status_code=404, detail="Profile not found.")
    return {
        "id": db_profile.id,
        "type": db_profile.type,
        "file_name": db_profile.file_name,
        "raw_text": db_profile.raw_text,
        "redacted_text": db_profile.redacted_text,
        "redaction_map": db_profile.redaction_map,
        "extracted_profile": db_profile.extracted_profile,
        "created_at": db_profile.created_at
    }

@app.post("/skills/normalize", response_model=List[dict])
def normalize_skills_list(skills: List[str]):
    """
    Ad-hoc skill normalization endpoint for bulk normalization requests.
    """
    try:
        results = normalizer.normalize_batch(skills)
        return [r.model_dump() for r in results]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Skill normalization failed: {str(e)}")

@app.get("/openapi.json")
def get_openapi():
    return app.openapi()
