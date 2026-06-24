import os
import csv
import re
import logging
from typing import List, Dict, Tuple, Optional
from pydantic import BaseModel
from rapidfuzz import fuzz, process

logger = logging.getLogger("skill_normalizer")

class ESCOSkill:
    def __init__(self, uri: str, preferred_label: str, alt_labels: List[str]):
        self.uri = uri
        self.preferred_label = preferred_label
        self.alt_labels = alt_labels

class NormalizedSkill(BaseModel):
    original_term: str
    concept_uri: Optional[str] = None
    preferred_label: Optional[str] = None
    match_type: str  # 'exact', 'fuzzy', 'embedding', or 'unmapped'
    score: float

def normalize_string(text: str) -> str:
    """
    Normalizes string by making it lowercase, removing special punctuation characters
    except for +, #, - which are common in tech terms (C++, C#, CI/CD), and collapsing whitespace.
    """
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s\-\+#]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

class SkillNormalizer:
    def __init__(self, csv_path: str = None):
        if csv_path is None:
            # Fallback to default location relative to project root
            base_dir = os.path.dirname(os.path.abspath(__file__))
            csv_path = os.path.join(base_dir, "data", "esco_skills.csv")
            
        self.csv_path = csv_path
        self.exact_match_map: Dict[str, ESCOSkill] = {}
        self.unique_skills: List[ESCOSkill] = []
        self.esco_labels: List[str] = []
        self.all_terms: List[str] = []
        
        # Lazy loaded model and embeddings
        self._embedding_model = None
        self._esco_embeddings = None
        
        self._load_taxonomy()

    def _load_taxonomy(self):
        """Loads ESCO skills from CSV file and builds exact match maps."""
        if not os.path.exists(self.csv_path):
            raise FileNotFoundError(f"ESCO skills taxonomy CSV not found at {self.csv_path}")

        try:
            with open(self.csv_path, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                seen_uris = set()
                
                for row in reader:
                    uri = row.get("conceptUri", "").strip()
                    pref_label = row.get("preferredLabel", "").strip()
                    alt_labels_str = row.get("altLabels", "").strip()
                    
                    if not uri or not pref_label:
                        continue
                        
                    alt_labels = [
                        a.strip() for a in alt_labels_str.split(";") if a.strip()
                    ]
                    
                    skill = ESCOSkill(uri, pref_label, alt_labels)
                    
                    # Store unique skills for embedding search
                    if uri not in seen_uris:
                        self.unique_skills.append(skill)
                        self.esco_labels.append(pref_label)
                        seen_uris.add(uri)
                    
                    # Populate exact match map
                    pref_norm = normalize_string(pref_label)
                    self.exact_match_map[pref_norm] = skill
                    
                    for alt in alt_labels:
                        alt_norm = normalize_string(alt)
                        self.exact_match_map[alt_norm] = skill
                        
            self.all_terms = list(self.exact_match_map.keys())
            logger.info(f"Loaded {len(self.unique_skills)} unique ESCO skills and {len(self.all_terms)} total terms.")
            
        except Exception as e:
            raise RuntimeError(f"Error reading ESCO CSV taxonomy: {str(e)}") from e

    def _init_embeddings(self):
        """Initializes the embedding model and precomputes taxonomy embeddings if not done yet."""
        if self._embedding_model is None:
            # We import sentence-transformers here to avoid slowdown during module startup
            from sentence_transformers import SentenceTransformer
            
            logger.info("Initializing local SentenceTransformer model 'all-MiniLM-L6-v2'...")
            self._embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            
            # Precompute embeddings for all unique preferred labels in ESCO taxonomy
            logger.info("Precomputing taxonomy embeddings...")
            self._esco_embeddings = self._embedding_model.encode(self.esco_labels, convert_to_tensor=True)

    def normalize_skill(self, skill_name: str) -> NormalizedSkill:
        """
        Normalizes a single skill name to the ESCO taxonomy using a 3-phase matching pipeline:
        Phase 1: Exact Match (including synonyms)
        Phase 2: Fuzzy Match (RapidFuzz) with threshold >= 85
        Phase 3: Embedding Fallback (Sentence-Transformers) with threshold >= 0.75
        """
        if not skill_name or not skill_name.strip():
            return NormalizedSkill(
                original_term=skill_name,
                match_type="unmapped",
                score=0.0
            )

        norm_query = normalize_string(skill_name)

        # === Phase 1: Exact Match ===
        if norm_query in self.exact_match_map:
            matched_skill = self.exact_match_map[norm_query]
            return NormalizedSkill(
                original_term=skill_name,
                concept_uri=matched_skill.concept_uri if hasattr(matched_skill, 'concept_uri') else matched_skill.uri,
                preferred_label=matched_skill.preferred_label,
                match_type="exact",
                score=100.0
            )

        # === Phase 2: Fuzzy Match ===
        if self.all_terms:
            # Find best match using RapidFuzz
            res = process.extractOne(norm_query, self.all_terms, scorer=fuzz.token_sort_ratio)
            if res:
                matched_term, score, _ = res
                if score >= 85.0:
                    matched_skill = self.exact_match_map[matched_term]
                    return NormalizedSkill(
                        original_term=skill_name,
                        concept_uri=matched_skill.concept_uri if hasattr(matched_skill, 'concept_uri') else matched_skill.uri,
                        preferred_label=matched_skill.preferred_label,
                        match_type="fuzzy",
                        score=float(score)
                    )

        # === Phase 3: Fallback by Embedding ===
        try:
            self._init_embeddings()
            from sentence_transformers import util
            
            query_emb = self._embedding_model.encode(skill_name, convert_to_tensor=True)
            cos_scores = util.cos_sim(query_emb, self._esco_embeddings)[0]
            
            best_idx = cos_scores.argmax().item()
            best_score = cos_scores[best_idx].item()
            
            if best_score >= 0.75:
                matched_skill = self.unique_skills[best_idx]
                return NormalizedSkill(
                    original_term=skill_name,
                    concept_uri=matched_skill.concept_uri if hasattr(matched_skill, 'concept_uri') else matched_skill.uri,
                    preferred_label=matched_skill.preferred_label,
                    match_type="embedding",
                    score=float(best_score * 100.0)  # Scale to 0-100 to match fuzzy
                )
        except Exception as e:
            logger.error(f"Error during embedding fallback matching: {str(e)}")

        # === Unmapped Fallback ===
        logger.warning(f"Skill unmapped: '{skill_name}' (normalized to '{norm_query}') could not be mapped to ESCO.")
        return NormalizedSkill(
            original_term=skill_name,
            match_type="unmapped",
            score=0.0
        )

    def normalize_batch(self, skills: List[str]) -> List[NormalizedSkill]:
        """Normalizes a list of skills in batch."""
        return [self.normalize_skill(s) for s in skills]
