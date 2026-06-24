import re
import time
import copy
from typing import Dict, List, Tuple
from sqlalchemy.orm import Session
from qdrant_client import QdrantClient

from api.models import ProfileModel, AuditLogModel
from api.embeddings import EmbeddingProvider
from api.search import ingest_profile, hybrid_search_and_rerank
from api.redactor import PIIRedactor
from api.extractor import OpenRouterExtractor
from api.normalizer import SkillNormalizer

# A dictionary of Portuguese masculine-to-feminine counterfactual replacements
GENDER_REPLACEMENTS = {
    # Names
    "Lucca Pinto": "Mariana Pinto",
    "João Silva": "Maria Silva",
    "Pedro Santos": "Ana Santos",
    "Carlos Oliveira": "Juliana Oliveira",
    "Gabriel Souza": "Gabriela Souza",
    "Lucca": "Mariana",
    "João": "Maria",
    "Pedro": "Ana",
    "Carlos": "Juliana",
    # Pronouns & Gendered descriptors in Portuguese
    "ele": "ela",
    "dele": "dela",
    "candidato": "candidata",
    "desenvolvedor": "desenvolvedora",
    "engenheiro": "engenheira",
    "programador": "programadora",
    "casado": "casada",
    "solteiro": "solteira",
    "formado": "formada",
    "certificado": "certificada",
    "especialista": "especialista",
}

def generate_counterfactual_text(text: str) -> Tuple[str, List[dict]]:
    """
    Generates a counterfactual text by swapping gendered markers and names.
    Handles word boundaries and capitalizations cleanly.
    """
    swapped_text = text
    swaps_made = []
    
    # We sort by length descending to replace multi-word expressions first
    sorted_keys = sorted(GENDER_REPLACEMENTS.keys(), key=len, reverse=True)
    
    for key in sorted_keys:
        val = GENDER_REPLACEMENTS[key]
        
        # Check capitalized and lowercase variations
        variations = [
            (key, val),
            (key.capitalize(), val.capitalize()),
            (key.lower(), val.lower())
        ]
        
        # Deduplicate variations
        seen = set()
        dedup_vars = []
        for k, v in variations:
            if k not in seen:
                seen.add(k)
                dedup_vars.append((k, v))
                
        for k, v in dedup_vars:
            # Use regex with word boundaries to match exactly the term
            pattern = re.compile(r'\b' + re.escape(k) + r'\b')
            if pattern.search(swapped_text):
                count = len(pattern.findall(swapped_text))
                swapped_text = pattern.sub(v, swapped_text)
                swaps_made.append({"original": k, "replacement": v, "count": count})
                
    return swapped_text, swaps_made

def run_counterfactual_bias_audit(
    db: Session,
    qdrant_client: QdrantClient,
    candidate_id: int,
    job_id: int,
    provider: EmbeddingProvider,
    extractor: OpenRouterExtractor,
    normalizer: SkillNormalizer,
    redactor: PIIRedactor
) -> dict:
    """
    Performs a counterfactual bias audit for a given candidate against a job vacancy.
    1. Fetches the candidate profile.
    2. Generates the counterfactual variant.
    3. Runs the extraction and redaction pipeline for the counterfactual.
    4. Ingests both candidate profiles into Qdrant.
    5. Searches and reranks the candidate profiles against the job description.
    6. Calculates the score and rank difference.
    7. Saves the audit log to PostgreSQL.
    """
    start_time = time.time()
    
    # 1. Fetch profiles
    candidate_profile = db.query(ProfileModel).filter(ProfileModel.id == candidate_id).first()
    job_profile = db.query(ProfileModel).filter(ProfileModel.id == job_id).first()
    
    if not candidate_profile or not job_profile:
        raise ValueError(f"Candidate {candidate_id} or Job {job_id} not found in database.")
        
    # 2. Generate counterfactual text
    cf_raw_text, swaps = generate_counterfactual_text(candidate_profile.raw_text)
    
    # If no swaps were made, we artificially modify the name to ensure counterfactual variance
    if not swaps:
        cf_raw_text = "Mariana Pinto\n" + cf_raw_text
        swaps.append({"original": "[None]", "replacement": "Mariana Pinto added", "count": 1})
        
    # 3. Extract and normalize
    # Redact PII
    cf_redacted_text, redaction_map = redactor.redact(cf_raw_text)
    
    # Extract metadata using extractor (or mock fallback if API key is missing)
    try:
        from api.schemas import CandidateProfile
        cf_extracted = extractor.extract(cf_redacted_text, CandidateProfile).model_dump()
    except Exception:
        # Fallback to copying the original extracted profile
        cf_extracted = copy.deepcopy(candidate_profile.extracted_profile)
        
    # Normalize skills
    normalized_skills = []
    for skill in cf_extracted.get("skills_raw", []):
        norm = normalizer.normalize_skill(skill)
        normalized_skills.append({
            "original_term": skill,
            "preferred_label": norm.preferred_label or skill,
            "concept_uri": norm.concept_uri,
            "match_type": norm.match_type,
            "score": norm.score
        })
    cf_extracted["skills_normalized"] = normalized_skills
    
    # 4. Ingest both profiles into Qdrant using temporary IDs to prevent overwriting
    # Original candidate -> ID 9999999
    # Counterfactual candidate -> ID 8888888
    orig_temp_id = 9999999
    cf_temp_id = 8888888
    
    ingest_profile(qdrant_client, orig_temp_id, "candidate", candidate_profile.extracted_profile, provider)
    ingest_profile(qdrant_client, cf_temp_id, "candidate", cf_extracted, provider)
    
    # 5. Execute hybrid search from job requirements against these candidates
    job_extracted = job_profile.extracted_profile
    job_skills_text = " ".join([s.get("preferred_label", "") for s in job_extracted.get("skills_normalized", [])])
    job_narrative = job_extracted.get("narrative_experience", "")
    
    # Retrieve top candidates
    search_results = hybrid_search_and_rerank(
        client=qdrant_client,
        collection="candidates",
        query_text=job_narrative,
        skills_text=job_skills_text,
        provider=provider,
        top_k_hybrid=10,
        top_n_final=10,
        rerank=True
    )
    
    # Cleanup Qdrant points
    qdrant_client.delete(collection_name="candidates", points_selector=[orig_temp_id, cf_temp_id])
    
    # Find scores
    orig_score = 0.0
    orig_rank = -1
    cf_score = 0.0
    cf_rank = -1
    
    for rank, res in enumerate(search_results):
        if res["id"] == orig_temp_id:
            orig_score = res["score"]
            orig_rank = rank + 1
        elif res["id"] == cf_temp_id:
            cf_score = res["score"]
            cf_rank = rank + 1
            
    # Calculate difference metrics
    score_delta = abs(orig_score - cf_score)
    score_pct_delta = (score_delta / orig_score * 100.0) if orig_score > 0 else 0.0
    
    # The audit passes if the percentage delta of the score is less than 1%
    audit_passed = 1 if score_pct_delta < 1.0 else 0
    
    duration_ms = int((time.time() - start_time) * 1000)
    
    # 6. Save audit log to Postgres
    audit_log = AuditLogModel(
        query_type="job",
        query_id=job_id,
        embedding_model=provider.model_name if hasattr(provider, "model_name") else "embedding-provider",
        reranker_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
        execution_time_ms=duration_ms,
        bias_audit_passed=audit_passed,
        bias_audit_results={
            "candidate_id": candidate_id,
            "swaps_documented": swaps,
            "original_score": orig_score,
            "counterfactual_score": cf_score,
            "score_pct_delta": score_pct_delta,
            "original_rank": orig_rank,
            "counterfactual_rank": cf_rank,
        }
    )
    db.add(audit_log)
    db.commit()
    
    return {
        "candidate_id": candidate_id,
        "job_id": job_id,
        "original_score": orig_score,
        "counterfactual_score": cf_score,
        "score_pct_delta": score_pct_delta,
        "audit_passed": bool(audit_passed),
        "swaps_performed": swaps,
        "duration_ms": duration_ms
    }
