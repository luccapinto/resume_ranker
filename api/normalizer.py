"""Maps free-text skills onto the ESCO taxonomy.

Three phases, cheapest first:

1. **exact** — the term (normalised) is a preferred label or a registered synonym
2. **fuzzy** — RapidFuzz token-sort ratio ≥ 85 against every known term
3. **embedding** — multilingual sentence embeddings, cosine ≥ 0.75

Anything that survives all three is reported as `unmapped`, which the UI surfaces
explicitly instead of silently dropping.
"""

from __future__ import annotations

import csv
import logging
import os
import re
import threading
from typing import Dict, List, Optional

from pydantic import BaseModel
from rapidfuzz import fuzz, process

from api import observability as obs
from api.config import settings

logger = logging.getLogger("skill_normalizer")

FUZZY_THRESHOLD = 85.0
EMBEDDING_THRESHOLD = 0.75


class ESCOSkill:
    def __init__(self, uri: str, preferred_label: str, alt_labels: List[str]):
        self.uri = uri
        self.preferred_label = preferred_label
        self.alt_labels = alt_labels


class NormalizedSkill(BaseModel):
    original_term: str
    concept_uri: Optional[str] = None
    preferred_label: Optional[str] = None
    match_type: str  # 'exact' | 'fuzzy' | 'embedding' | 'unmapped'
    score: float


def normalize_string(text: str) -> str:
    """Lowercase, strip punctuation except +, # and - (C++, C#, CI/CD), collapse spaces."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s\-\+#]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class SkillNormalizer:
    def __init__(self, csv_path: str = None):
        if csv_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            csv_path = os.path.join(base_dir, "data", "esco_skills.csv")

        self.csv_path = csv_path
        self.exact_match_map: Dict[str, ESCOSkill] = {}
        self.unique_skills: List[ESCOSkill] = []
        self.esco_labels: List[str] = []
        self.all_terms: List[str] = []

        self._embedding_model = None
        self._esco_embeddings = None
        self._embedding_lock = threading.Lock()
        # Skills repeat heavily across a talent pool; memoise the resolution.
        self._cache: Dict[str, NormalizedSkill] = {}

        self._load_taxonomy()

    # ── Taxonomy ────────────────────────────────────────────────────────
    def _load_taxonomy(self) -> None:
        if not os.path.exists(self.csv_path):
            raise FileNotFoundError(f"ESCO skills taxonomy CSV not found at {self.csv_path}")

        try:
            with open(self.csv_path, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                seen_uris = set()

                for row in reader:
                    uri = (row.get("conceptUri") or "").strip()
                    pref_label = (row.get("preferredLabel") or "").strip()
                    alt_labels_str = (row.get("altLabels") or "").strip()

                    if not uri or not pref_label:
                        continue

                    alt_labels = [a.strip() for a in alt_labels_str.split(";") if a.strip()]
                    skill = ESCOSkill(uri, pref_label, alt_labels)

                    if uri not in seen_uris:
                        self.unique_skills.append(skill)
                        self.esco_labels.append(pref_label)
                        seen_uris.add(uri)

                    self.exact_match_map[normalize_string(pref_label)] = skill
                    for alt in alt_labels:
                        self.exact_match_map.setdefault(normalize_string(alt), skill)

            self.all_terms = list(self.exact_match_map.keys())
            logger.info(
                "Loaded %s unique ESCO skills and %s total terms.",
                len(self.unique_skills),
                len(self.all_terms),
            )
        except Exception as e:
            raise RuntimeError(f"Error reading ESCO CSV taxonomy: {str(e)}") from e

    # ── Embeddings (lazy, shared with the retrieval model) ──────────────
    def _init_embeddings(self) -> None:
        if self._embedding_model is not None:
            return
        with self._embedding_lock:
            if self._embedding_model is not None:
                return
            from sentence_transformers import SentenceTransformer

            model_name = settings.EMBEDDING_MODEL_LOCAL
            logger.info("Initializing SentenceTransformer '%s' for skill matching…", model_name)
            model = SentenceTransformer(model_name)
            self._esco_embeddings = model.encode(self.esco_labels, convert_to_tensor=True)
            self._embedding_model = model

    # ── Matching ────────────────────────────────────────────────────────
    def _match_exact(self, norm_query: str, skill_name: str) -> Optional[NormalizedSkill]:
        matched = self.exact_match_map.get(norm_query)
        if not matched:
            return None
        return NormalizedSkill(
            original_term=skill_name,
            concept_uri=matched.uri,
            preferred_label=matched.preferred_label,
            match_type="exact",
            score=100.0,
        )

    def _match_fuzzy(self, norm_query: str, skill_name: str) -> Optional[NormalizedSkill]:
        if not self.all_terms:
            return None
        res = process.extractOne(norm_query, self.all_terms, scorer=fuzz.token_sort_ratio)
        if not res:
            return None
        matched_term, score, _ = res
        if score < FUZZY_THRESHOLD:
            return None
        matched = self.exact_match_map[matched_term]
        return NormalizedSkill(
            original_term=skill_name,
            concept_uri=matched.uri,
            preferred_label=matched.preferred_label,
            match_type="fuzzy",
            score=float(score),
        )

    def _match_embedding(self, skill_name: str) -> Optional[NormalizedSkill]:
        try:
            self._init_embeddings()
            from sentence_transformers import util

            query_emb = self._embedding_model.encode(skill_name, convert_to_tensor=True)
            cos_scores = util.cos_sim(query_emb, self._esco_embeddings)[0]
            best_idx = int(cos_scores.argmax().item())
            best_score = float(cos_scores[best_idx].item())

            if best_score >= EMBEDDING_THRESHOLD:
                matched = self.unique_skills[best_idx]
                return NormalizedSkill(
                    original_term=skill_name,
                    concept_uri=matched.uri,
                    preferred_label=matched.preferred_label,
                    match_type="embedding",
                    score=round(best_score * 100.0, 2),
                )
        except Exception as e:  # noqa: BLE001 — fallback must never break ingestion
            logger.error("Error during embedding fallback matching: %s", e)
        return None

    def normalize_skill(self, skill_name: str) -> NormalizedSkill:
        if not skill_name or not skill_name.strip():
            return NormalizedSkill(original_term=skill_name or "", match_type="unmapped", score=0.0)

        norm_query = normalize_string(skill_name)
        cached = self._cache.get(norm_query)
        if cached is not None:
            return cached.model_copy(update={"original_term": skill_name})

        result = (
            self._match_exact(norm_query, skill_name)
            or self._match_fuzzy(norm_query, skill_name)
            or self._match_embedding(skill_name)
        )

        if result is None:
            logger.info("Skill unmapped: '%s' (normalised '%s').", skill_name, norm_query)
            result = NormalizedSkill(original_term=skill_name, match_type="unmapped", score=0.0)

        self._cache[norm_query] = result
        return result

    def normalize_batch(self, skills: List[str]) -> List[NormalizedSkill]:
        with obs.span("skills.normalize", kind=obs.KIND_LOGIC, count=len(skills or [])) as sp:
            results = [self.normalize_skill(s) for s in (skills or [])]
            by_type: Dict[str, int] = {}
            for r in results:
                by_type[r.match_type] = by_type.get(r.match_type, 0) + 1
            sp.set(
                match_types=by_type,
                coverage=round(
                    sum(1 for r in results if r.match_type != "unmapped") / len(results), 3
                )
                if results
                else 0.0,
            )
            return results
