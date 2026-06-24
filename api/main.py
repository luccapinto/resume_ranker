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
from api.embeddings import get_embedding_provider
from api.search import init_qdrant_collections, ingest_profile, build_qdrant_filter, hybrid_search_and_rerank
from api.explain import generate_match_explanation
from api.fairness import run_counterfactual_bias_audit
from fastapi import Query

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Resume Ranker API",
    description="Backend API for Resume Ranker platform - Candidate & Job extraction and normalization",
    version="0.1.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
        # Initialize Qdrant collections
        qdrant_client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        provider = get_embedding_provider()
        init_qdrant_collections(qdrant_client, provider.dimension)
        print("Qdrant collections initialized successfully.")
    except Exception as e:
        print(f"Error creating database tables or initializing Qdrant: {e}")

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
        
    # Ingest into Qdrant
    try:
        qdrant_client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        provider = get_embedding_provider()
        ingest_profile(qdrant_client, db_profile.id, "candidate", profile_dict, provider)
    except Exception as e:
        db.delete(db_profile)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Qdrant ingestion failed: {str(e)}")
        
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
        
    # Ingest into Qdrant
    try:
        qdrant_client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        provider = get_embedding_provider()
        ingest_profile(qdrant_client, db_profile.id, "job", profile_dict, provider)
    except Exception as e:
        db.delete(db_profile)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Qdrant ingestion failed: {str(e)}")
        
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

@app.post("/matching/candidates", response_model=List[dict])
def match_candidates_for_job(
    job_id: int,
    min_experience_years: Optional[float] = Query(None, description="Anos mínimos de experiência profissional"),
    required_certifications: Optional[List[str]] = Query(None, description="Certificações obrigatórias exigidas"),
    seniorities: Optional[List[str]] = Query(None, description="Níveis de senioridade aceitos"),
    top_k: int = Query(20, description="Top-K candidatos para RRF e Cross-Encoder"),
    top_n: int = Query(10, description="Top-N final a retornar"),
    rerank: bool = Query(True, description="Habilitar reranking com Cross-Encoder"),
    weights: Optional[List[float]] = Query(None, description="Pesos RRF para [skills, narrative, lexical]"),
    db: Session = Depends(get_db)
):
    """
    Busca candidatos compatíveis com uma vaga (Job) usando busca híbrida e reranking.
    """
    # 1. Obter perfil da vaga
    job_profile = db.query(api.models.ProfileModel).filter(
        api.models.ProfileModel.id == job_id,
        api.models.ProfileModel.type == "job"
    ).first()
    if not job_profile:
        raise HTTPException(status_code=404, detail="Job profile not found.")
        
    ext_prof = job_profile.extracted_profile
    
    # Concatenar competências da vaga
    skills_normalized = ext_prof.get("skills_normalized", [])
    skills_labels = [s.get("preferred_label") for s in skills_normalized if s.get("preferred_label")]
    skills_text = " ".join(skills_labels)
    if not skills_text:
        skills_text = " ".join(ext_prof.get("skills_raw", []))
        
    narrative_text = ext_prof.get("narrative_experience", "")
    
    # 2. Executar busca híbrida no Qdrant
    try:
        qdrant_client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        provider = get_embedding_provider()
        
        q_filter = build_qdrant_filter(
            min_experience_years=min_experience_years,
            required_certifications=required_certifications,
            seniorities=seniorities
        )
        
        search_results = hybrid_search_and_rerank(
            client=qdrant_client,
            collection="candidates",
            query_text=narrative_text,
            skills_text=skills_text,
            provider=provider,
            qdrant_filter=q_filter,
            top_k_hybrid=top_k,
            top_n_final=top_n,
            rerank=rerank,
            weights=weights
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Hybrid search failed: {str(e)}")
        
    # 3. Enriquecer resultados com dados do banco
    candidate_ids = [r["id"] for r in search_results]
    db_candidates = db.query(api.models.ProfileModel).filter(
        api.models.ProfileModel.id.in_(candidate_ids)
    ).all()
    candidates_by_id = {c.id: c for c in db_candidates}
    
    response = []
    for r in search_results:
        cand_id = r["id"]
        cand_obj = candidates_by_id.get(cand_id)
        if cand_obj:
            response.append({
                "id": cand_id,
                "score": r["score"],
                "rrf_score": r["rrf_score"],
                "profile": {
                    "id": cand_obj.id,
                    "type": cand_obj.type,
                    "file_name": cand_obj.file_name,
                    "raw_text": cand_obj.raw_text,
                    "redacted_text": cand_obj.redacted_text,
                    "redaction_map": cand_obj.redaction_map,
                    "extracted_profile": cand_obj.extracted_profile,
                    "created_at": cand_obj.created_at
                }
            })
    return response

@app.post("/matching/jobs", response_model=List[dict])
def match_jobs_for_candidate(
    candidate_id: int,
    min_experience_years: Optional[float] = Query(None, description="Anos mínimos de experiência da vaga"),
    required_certifications: Optional[List[str]] = Query(None, description="Certificações obrigatórias exigidas pela vaga"),
    seniorities: Optional[List[str]] = Query(None, description="Níveis de senioridade aceitos pela vaga"),
    top_k: int = Query(20, description="Top-K vagas para RRF e Cross-Encoder"),
    top_n: int = Query(10, description="Top-N final a retornar"),
    rerank: bool = Query(True, description="Habilitar reranking com Cross-Encoder"),
    weights: Optional[List[float]] = Query(None, description="Pesos RRF para [skills, narrative, lexical]"),
    db: Session = Depends(get_db)
):
    """
    Busca vagas (Jobs) compatíveis com um candidato usando busca híbrida e reranking.
    """
    # 1. Obter perfil do candidato
    cand_profile = db.query(api.models.ProfileModel).filter(
        api.models.ProfileModel.id == candidate_id,
        api.models.ProfileModel.type == "candidate"
    ).first()
    if not cand_profile:
        raise HTTPException(status_code=404, detail="Candidate profile not found.")
        
    ext_prof = cand_profile.extracted_profile
    
    # Concatenar competências do candidato
    skills_normalized = ext_prof.get("skills_normalized", [])
    skills_labels = [s.get("preferred_label") for s in skills_normalized if s.get("preferred_label")]
    skills_text = " ".join(skills_labels)
    if not skills_text:
        skills_text = " ".join(ext_prof.get("skills_raw", []))
        
    narrative_text = ext_prof.get("narrative_experience", "")
    
    # 2. Executar busca híbrida no Qdrant
    try:
        qdrant_client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        provider = get_embedding_provider()
        
        q_filter = build_qdrant_filter(
            min_experience_years=min_experience_years,
            required_certifications=required_certifications,
            seniorities=seniorities
        )
        
        search_results = hybrid_search_and_rerank(
            client=qdrant_client,
            collection="jobs",
            query_text=narrative_text,
            skills_text=skills_text,
            provider=provider,
            qdrant_filter=q_filter,
            top_k_hybrid=top_k,
            top_n_final=top_n,
            rerank=rerank,
            weights=weights
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Hybrid search failed: {str(e)}")
        
    # 3. Enriquecer resultados com dados do banco
    job_ids = [r["id"] for r in search_results]
    db_jobs = db.query(api.models.ProfileModel).filter(
        api.models.ProfileModel.id.in_(job_ids)
    ).all()
    jobs_by_id = {j.id: j for j in db_jobs}
    
    response = []
    for r in search_results:
        j_id = r["id"]
        job_obj = jobs_by_id.get(j_id)
        if job_obj:
            response.append({
                "id": j_id,
                "score": r["score"],
                "rrf_score": r["rrf_score"],
                "profile": {
                    "id": job_obj.id,
                    "type": job_obj.type,
                    "file_name": job_obj.file_name,
                    "raw_text": job_obj.raw_text,
                    "redacted_text": job_obj.redacted_text,
                    "redaction_map": job_obj.redaction_map,
                    "extracted_profile": job_obj.extracted_profile,
                    "created_at": job_obj.created_at
                }
            })
    return response

@app.post("/matching/explain")
def explain_match(
    candidate_id: int,
    job_id: int,
    db: Session = Depends(get_db)
):
    """
    Explica a relevância de um match candidato-vaga e valida trechos citados contra
    o texto bruto original.
    """
    candidate = db.query(api.models.ProfileModel).filter(
        api.models.ProfileModel.id == candidate_id,
        api.models.ProfileModel.type == "candidate"
    ).first()
    job = db.query(api.models.ProfileModel).filter(
        api.models.ProfileModel.id == job_id,
        api.models.ProfileModel.type == "job"
    ).first()
    
    if not candidate or not job:
        raise HTTPException(status_code=404, detail="Candidate or Job profile not found.")
        
    try:
        explanation = generate_match_explanation(
            candidate_raw_text=candidate.raw_text,
            candidate_redacted_text=candidate.redacted_text,
            job_raw_text=job.raw_text,
            candidate_extracted=candidate.extracted_profile,
            job_extracted=job.extracted_profile
        )
        return explanation
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Explanation generation failed: {str(e)}")

@app.post("/matching/audit-bias")
def audit_bias(
    candidate_id: int,
    job_id: int,
    db: Session = Depends(get_db)
):
    """
    Gera variantes contrárias de um currículo (counterfactual pairs),
    submete ambas ao pipeline e compara a variação do score de relevância.
    """
    try:
        qdrant_client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        provider = get_embedding_provider()
        redactor = PIIRedactor()
        extractor = OpenRouterExtractor()
        
        audit_result = run_counterfactual_bias_audit(
            db=db,
            qdrant_client=qdrant_client,
            candidate_id=candidate_id,
            job_id=job_id,
            provider=provider,
            extractor=extractor,
            normalizer=normalizer,
            redactor=redactor
        )
        return audit_result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Counterfactual bias audit failed: {str(e)}")

@app.get("/profiles/candidates", response_model=List[dict])
def list_candidates(db: Session = Depends(get_db)):
    """
    Lista todos os candidatos cadastrados no banco de dados.
    """
    candidates = db.query(api.models.ProfileModel).filter(
        api.models.ProfileModel.type == "candidate"
    ).order_by(api.models.ProfileModel.created_at.desc()).all()
    
    return [
        {
            "id": c.id,
            "type": c.type,
            "file_name": c.file_name,
            "raw_text": c.raw_text,
            "redacted_text": c.redacted_text,
            "redaction_map": c.redaction_map,
            "extracted_profile": c.extracted_profile,
            "created_at": c.created_at
        }
        for c in candidates
    ]

@app.get("/profiles/jobs", response_model=List[dict])
def list_jobs(db: Session = Depends(get_db)):
    """
    Lista todas as vagas cadastradas no banco de dados.
    """
    jobs = db.query(api.models.ProfileModel).filter(
        api.models.ProfileModel.type == "job"
    ).order_by(api.models.ProfileModel.created_at.desc()).all()
    
    return [
        {
            "id": j.id,
            "type": j.type,
            "file_name": j.file_name,
            "raw_text": j.raw_text,
            "redacted_text": j.redacted_text,
            "redaction_map": j.redaction_map,
            "extracted_profile": j.extracted_profile,
            "created_at": j.created_at
        }
        for j in jobs
    ]

@app.get("/audit/logs", response_model=List[dict])
def list_audit_logs(db: Session = Depends(get_db)):
    """
    Lista todo o histórico de logs de auditoria de viés.
    """
    logs = db.query(api.models.AuditLogModel).order_by(
        api.models.AuditLogModel.created_at.desc()
    ).all()
    
    return [
        {
            "id": l.id,
            "query_type": l.query_type,
            "query_id": l.query_id,
            "embedding_model": l.embedding_model,
            "reranker_model": l.reranker_model,
            "execution_time_ms": l.execution_time_ms,
            "bias_audit_passed": bool(l.bias_audit_passed),
            "bias_audit_results": l.bias_audit_results,
            "created_at": l.created_at
        }
        for l in logs
    ]

@app.get("/openapi.json")
def get_openapi():
    return app.openapi()

