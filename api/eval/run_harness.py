import os
import json
import math
from typing import List, Dict, Tuple
from sqlalchemy.orm import Session
from qdrant_client import QdrantClient

from api.database import SessionLocal
from api.models import ProfileModel
from sqlalchemy import text
from api.embeddings import get_embedding_provider
from api.search import hybrid_search_and_rerank
from api.config import settings

def dcg_at_k(r: List[float], k: int) -> float:
    """Calculates Discounted Cumulative Gain (DCG) at rank K."""
    r = r[:k]
    dcg = 0.0
    for idx, rel in enumerate(r):
        dcg += (2**rel - 1.0) / math.log2(idx + 2.0)
    return dcg

def ndcg_at_k(r: List[float], k: int, ideal_r: List[float]) -> float:
    """Calculates Normalized Discounted Cumulative Gain (NDCG) at rank K."""
    dcg_val = dcg_at_k(r, k)
    # Ideal DCG is calculated from sorted ideal relevances
    sorted_ideal = sorted(ideal_r, reverse=True)
    idcg_val = dcg_at_k(sorted_ideal, k)
    if idcg_val == 0.0:
        return 0.0
    return dcg_val / idcg_val

def mean_reciprocal_rank(r: List[float], threshold: float = 2.0) -> float:
    """Calculates Reciprocal Rank (RR) based on the first item with relevance >= threshold."""
    for idx, rel in enumerate(r):
        if rel >= threshold:
            return 1.0 / (idx + 1.0)
    return 0.0

def run_evaluation(
    db: Session,
    qdrant_client: QdrantClient,
    qrels: Dict[str, Dict[str, int]],
    weights: List[float]
) -> Tuple[float, float, float]:
    """Runs evaluation over all query/job keys in qrels and returns mean NDCG@5, NDCG@10, and MRR."""
    provider = get_embedding_provider()
    
    total_ndcg_5 = 0.0
    total_ndcg_10 = 0.0
    total_mrr = 0.0
    queries_run = 0
    
    for job_id_str, candidate_relevances in qrels.items():
        job_id = int(job_id_str)
        # Fetch job requirements
        job_db = db.query(ProfileModel).filter(ProfileModel.id == job_id, ProfileModel.type == "job").first()
        if not job_db:
            continue
            
        ext_prof = job_db.extracted_profile
        skills_normalized = ext_prof.get("skills_normalized", [])
        skills_labels = [s.get("preferred_label") for s in skills_normalized if s.get("preferred_label")]
        skills_text = " ".join(skills_labels)
        if not skills_text:
            skills_text = " ".join(ext_prof.get("skills_raw", []))
            
        narrative_text = ext_prof.get("narrative_experience", "")
        
        # Execute hybrid search with candidate collection
        try:
            results = hybrid_search_and_rerank(
                client=qdrant_client,
                collection="candidates",
                query_text=narrative_text,
                skills_text=skills_text,
                provider=provider,
                top_k_hybrid=20,
                top_n_final=10,
                rerank=True,
                weights=weights
            )
        except Exception as e:
            print(f"Query for job {job_id} failed: {e}")
            continue
            
        # Map retrieved candidate IDs to their relevance judgments
        retrieved_rels = []
        for r in results:
            cand_id_str = str(r["id"])
            rel = candidate_relevances.get(cand_id_str, 0)
            retrieved_rels.append(float(rel))
            
        # Get all relevance scores for the query to calculate ideal DCG
        ideal_rels = [float(rel) for rel in candidate_relevances.values()]
        
        ndcg_5 = ndcg_at_k(retrieved_rels, 5, ideal_rels)
        ndcg_10 = ndcg_at_k(retrieved_rels, 10, ideal_rels)
        mrr = mean_reciprocal_rank(retrieved_rels, threshold=2.0)
        
        total_ndcg_5 += ndcg_5
        total_ndcg_10 += ndcg_10
        total_mrr += mrr
        queries_run += 1
        
    if queries_run == 0:
        return 0.0, 0.0, 0.0
        
    return (
        total_ndcg_5 / queries_run,
        total_ndcg_10 / queries_run,
        total_mrr / queries_run
    )

def main():
    # Load relevance judgments
    qrels_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qrels.json")
    if not os.path.exists(qrels_path):
        print(f"Qrels file not found at {qrels_path}")
        return
        
    with open(qrels_path, "r", encoding="utf-8") as f:
        qrels = json.load(f)
        
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    # 1. Setup Postgres or SQLite
    try:
        db = SessionLocal()
        # Test connection
        db.execute(text("SELECT 1"))
        print("Using real PostgreSQL database.")
    except Exception:
        print("Aviso: Falha ao conectar ao Postgres Docker. Usando SQLite local (api/eval/resume_ranker_eval.db).")
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume_ranker_eval.db")
        engine_sqlite = create_engine(f"sqlite:///{db_path}")
        db = sessionmaker(bind=engine_sqlite)()
        
    # 2. Setup Qdrant
    try:
        qdrant_client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        qdrant_client.get_collections()
        print("Using real Docker Qdrant client.")
    except Exception:
        print("Aviso: Falha ao conectar ao Qdrant Docker. Usando Qdrant local persistido no disco (api/eval/qdrant_storage).")
        qdrant_storage_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qdrant_storage")
        qdrant_client = QdrantClient(path=qdrant_storage_path)
    
    # Check if database has profiles
    candidate_count = db.query(ProfileModel).filter(ProfileModel.type == "candidate").count()
    job_count = db.query(ProfileModel).filter(ProfileModel.type == "job").count()
    
    if candidate_count == 0 or job_count == 0:
        print("Aviso: A base de dados está vazia ou sem perfis cadastrados.")
        print("Por favor, execute o script de seeding primeiro: python -m api.eval.seed_data")
        db.close()
        return
        
    print(f"Iniciando Harness de Avaliação de Retrieval ({candidate_count} candidatos, {job_count} vagas)...")
    print("-" * 75)
    
    # 3 distinct configurations to benchmark:
    # 1. Balanced: [1.0, 1.0, 1.0] (skills, narrative, lexical)
    # 2. Hard Skills Weighted: [2.0, 0.5, 1.0]
    # 3. Narrative/Soft weighted: [0.5, 2.0, 0.5]
    configs = [
        {"name": "Balanced (Skills=1.0, Narrative=1.0, Lexical=1.0)", "weights": [1.0, 1.0, 1.0]},
        {"name": "Hard Skills Heavy (Skills=2.0, Narrative=0.5, Lexical=1.0)", "weights": [2.0, 0.5, 1.0]},
        {"name": "Narrative Heavy (Skills=0.5, Narrative=2.0, Lexical=0.5)", "weights": [0.5, 2.0, 0.5]},
    ]
    
    print(f"{'Configuração':<50} | {'NDCG@5':<8} | {'NDCG@10':<8} | {'MRR':<6}")
    print("-" * 80)
    
    for cfg in configs:
        ndcg_5, ndcg_10, mrr = run_evaluation(db, qdrant_client, qrels, cfg["weights"])
        print(f"{cfg['name']:<50} | {ndcg_5:8.4f} | {ndcg_10:8.4f} | {mrr:6.4f}")
        
    print("-" * 80)
    db.close()

if __name__ == "__main__":
    main()
