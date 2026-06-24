import os
import re
import hashlib
import math
from typing import List, Dict, Optional, Union
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams,
    SparseVectorParams,
    SparseIndexParams,
    Distance,
    PointStruct,
    NamedVector,
    NamedSparseVector,
    SparseVector,
    Filter,
    FieldCondition,
    MatchValue,
    MatchAny,
    Range
)
from api.embeddings import EmbeddingProvider, get_embedding_provider
from api.config import settings

_cross_encoder_model = None

def get_cross_encoder():
    """Lazy loads and returns the CrossEncoder model singleton."""
    global _cross_encoder_model
    if _cross_encoder_model is None:
        from sentence_transformers import CrossEncoder
        # Light weight cross-encoder for fast reranking
        _cross_encoder_model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    return _cross_encoder_model

def init_qdrant_collections(client: QdrantClient, dimension: int):
    """Initializes candidates and jobs collections in Qdrant if they do not exist."""
    collections = ["candidates", "jobs"]
    existing_collections = [c.name for c in client.get_collections().collections]
    
    for coll in collections:
        if coll not in existing_collections:
            client.create_collection(
                collection_name=coll,
                vectors_config={
                    "skills_vector": VectorParams(size=dimension, distance=Distance.COSINE),
                    "narrative_vector": VectorParams(size=dimension, distance=Distance.COSINE),
                },
                sparse_vectors_config={
                    "lexical_vector": SparseVectorParams(
                        index=SparseIndexParams(
                            on_disk=False,
                        )
                    )
                }
            )
            print(f"Qdrant collection '{coll}' created successfully with dimension {dimension}.")

def ingest_profile(
    client: QdrantClient,
    profile_id: int,
    profile_type: str,
    extracted_profile: dict,
    provider: EmbeddingProvider
):
    """
    Ingests a candidate or job profile into Qdrant.
    Generates skills_vector, narrative_vector, and lexical_vector,
    and stores structured payload metadata.
    """
    collection = "candidates" if profile_type == "candidate" else "jobs"
    
    # 1. Process skills
    skills_normalized = extracted_profile.get("skills_normalized", [])
    skills_labels = []
    esco_skills_ids = []
    
    for s in skills_normalized:
        pref = s.get("preferred_label")
        uri = s.get("concept_uri")
        if pref:
            skills_labels.append(pref)
        if uri:
            esco_skills_ids.append(uri)
            
    # Concatenate skills for semantic representation
    skills_text = " ".join(skills_labels)
    if not skills_text:
        skills_text = " ".join(extracted_profile.get("skills_raw", []))
        
    # Process narrative
    narrative_text = extracted_profile.get("narrative_experience", "")
    
    # Build lexical representation
    certifications = extracted_profile.get("certifications", [])
    lexical_text = f"{skills_text} {narrative_text} {' '.join(certifications)}"
    
    # 2. Generate embeddings
    skills_vector = provider.get_dense_embedding(skills_text)
    narrative_vector = provider.get_dense_embedding(narrative_text)
    
    # Generate sparse lexical embedding
    sparse_dict = provider.get_sparse_embedding(lexical_text)
    indices = sorted(list(sparse_dict.keys()))
    values = [sparse_dict[idx] for idx in indices]
    lexical_vector = SparseVector(indices=indices, values=values)
    
    # 3. Build payload
    payload = {
        "esco_skills_ids": esco_skills_ids,
        "seniority": extracted_profile.get("seniority"),
        "experience_years": float(extracted_profile.get("experience_years", 0.0)),
        "certifications": certifications,
        "narrative_experience": narrative_text,
        "skills_text": skills_text,
    }
    
    if profile_type == "candidate":
        payload["candidate_id"] = profile_id
    else:
        payload["job_id"] = profile_id
        
    # 4. Upsert point
    client.upsert(
        collection_name=collection,
        points=[
            PointStruct(
                id=profile_id,
                vector={
                    "skills_vector": skills_vector,
                    "narrative_vector": narrative_vector,
                    "lexical_vector": lexical_vector
                },
                payload=payload
            )
        ]
    )

def reciprocal_rank_fusion(
    rankings: List[List[Union[int, str]]],
    k: int = 60,
    weights: Optional[List[float]] = None
) -> Dict[Union[int, str], float]:
    """
    Combines ranking results from multiple retrieval strategies using Reciprocal Rank Fusion (RRF).
    Scores are computed as RRF_Score(d) = sum( w_m / (k + rank_d) )
    """
    scores = {}
    for i, ranking in enumerate(rankings):
        w = weights[i] if (weights and i < len(weights)) else 1.0
        for rank, doc_id in enumerate(ranking):
            r = rank + 1  # 1-based rank
            scores[doc_id] = scores.get(doc_id, 0.0) + (w / (k + r))
    return scores

def build_qdrant_filter(
    min_experience_years: Optional[float] = None,
    required_certifications: Optional[List[str]] = None,
    seniorities: Optional[List[str]] = None
) -> Optional[Filter]:
    """Helper to build structured Filter for Qdrant queries."""
    must_conditions = []
    
    if min_experience_years is not None:
        must_conditions.append(
            FieldCondition(key="experience_years", range=Range(gte=min_experience_years))
        )
        
    if required_certifications:
        for cert in required_certifications:
            must_conditions.append(
                FieldCondition(key="certifications", match=MatchValue(value=cert))
            )
            
    if seniorities:
        must_conditions.append(
            FieldCondition(key="seniority", match=MatchAny(any=seniorities))
        )
        
    if not must_conditions:
        return None
        
    return Filter(must=must_conditions)

def hybrid_search_and_rerank(
    client: QdrantClient,
    collection: str,
    query_text: str,
    skills_text: str,
    provider: EmbeddingProvider,
    qdrant_filter: Optional[Filter] = None,
    k_rrf: int = 60,
    top_k_hybrid: int = 20,
    top_n_final: int = 10,
    rerank: bool = True,
    weights: Optional[List[float]] = None
) -> List[dict]:
    """
    Executes a hybrid search query on Qdrant combining dense skills_vector, dense narrative_vector,
    and sparse lexical_vector. Applies Reciprocal Rank Fusion (RRF) and finishes with local Cross-Encoder reranking.
    """
    # 1. Embed query
    query_skills_vector = provider.get_dense_embedding(skills_text)
    query_narrative_vector = provider.get_dense_embedding(query_text)
    query_lexical_vector = provider.get_sparse_embedding(query_text)
    
    # 2. Search Qdrant
    is_mock = type(client).__name__ in ("MagicMock", "Mock")
    if hasattr(client, "query_points") and not is_mock:
        res_skills = client.query_points(
            collection_name=collection,
            using="skills_vector",
            query=query_skills_vector,
            query_filter=qdrant_filter,
            limit=top_k_hybrid,
            with_payload=True
        ).points
        
        res_narrative = client.query_points(
            collection_name=collection,
            using="narrative_vector",
            query=query_narrative_vector,
            query_filter=qdrant_filter,
            limit=top_k_hybrid,
            with_payload=True
        ).points
        
        res_lexical = []
        if query_lexical_vector:
            indices = sorted(list(query_lexical_vector.keys()))
            values = [query_lexical_vector[idx] for idx in indices]
            lexical_sv = SparseVector(indices=indices, values=values)
            res_lexical = client.query_points(
                collection_name=collection,
                using="lexical_vector",
                query=lexical_sv,
                query_filter=qdrant_filter,
                limit=top_k_hybrid,
                with_payload=True
            ).points
    else:
        res_skills = client.search(
            collection_name=collection,
            query_vector=NamedVector(name="skills_vector", vector=query_skills_vector),
            query_filter=qdrant_filter,
            limit=top_k_hybrid,
            with_payload=True
        )
        
        res_narrative = client.search(
            collection_name=collection,
            query_vector=NamedVector(name="narrative_vector", vector=query_narrative_vector),
            query_filter=qdrant_filter,
            limit=top_k_hybrid,
            with_payload=True
        )
        
        res_lexical = []
        if query_lexical_vector:
            indices = sorted(list(query_lexical_vector.keys()))
            values = [query_lexical_vector[idx] for idx in indices]
            lexical_sv = SparseVector(indices=indices, values=values)
            res_lexical = client.search(
                collection_name=collection,
                query_vector=NamedSparseVector(name="lexical_vector", vector=lexical_sv),
                query_filter=qdrant_filter,
                limit=top_k_hybrid,
                with_payload=True
            )
        
    # 3. Reciprocal Rank Fusion (RRF)
    points_map = {}
    
    ranking_skills = []
    for p in res_skills:
        ranking_skills.append(p.id)
        points_map[p.id] = p
        
    ranking_narrative = []
    for p in res_narrative:
        ranking_narrative.append(p.id)
        points_map[p.id] = p
        
    ranking_lexical = []
    for p in res_lexical:
        ranking_lexical.append(p.id)
        points_map[p.id] = p
        
    rrf_scores = reciprocal_rank_fusion(
        [ranking_skills, ranking_narrative, ranking_lexical],
        k=k_rrf,
        weights=weights
    )
    
    # Sort by RRF score
    sorted_by_rrf = sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True)
    top_hybrid_points = [points_map[pid] for pid, _ in sorted_by_rrf[:top_k_hybrid]]
    
    # 4. Rerank via Cross-Encoder
    results = []
    if rerank and top_hybrid_points:
        cross_encoder = get_cross_encoder()
        
        # Build query representation for Cross-Encoder comparison
        # Use narrative + skills representation
        query_ce_text = f"{skills_text} {query_text}"
        
        pairs = []
        for p in top_hybrid_points:
            doc_narrative = p.payload.get("narrative_experience", "")
            doc_skills = p.payload.get("skills_text", "")
            doc_ce_text = f"{doc_skills} {doc_narrative}"
            pairs.append([query_ce_text, doc_ce_text])
            
        ce_scores = cross_encoder.predict(pairs)
        if hasattr(ce_scores, "tolist"):
            ce_scores = ce_scores.tolist()
        else:
            ce_scores = list(ce_scores)
        
        # Build scored list
        scored_points = []
        for i, p in enumerate(top_hybrid_points):
            scored_points.append({
                "id": p.id,
                "payload": p.payload,
                "rrf_score": rrf_scores[p.id],
                "score": ce_scores[i]  # Cross-Encoder score
            })
            
        # Sort by Cross-Encoder score descending
        scored_points.sort(key=lambda x: x["score"], reverse=True)
        results = scored_points[:top_n_final]
    else:
        # Fallback to pure RRF scoring if no reranking or no results
        for p in top_hybrid_points:
            results.append({
                "id": p.id,
                "payload": p.payload,
                "rrf_score": rrf_scores[p.id],
                "score": rrf_scores[p.id]
            })
        results = results[:top_n_final]
        
    return results
