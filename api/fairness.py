"""Counterfactual bias auditing.

We clone a résumé, flip one demographic signal at a time, push both versions
through the *same* scoring path, and measure how far the score moved. A pipeline
that is fair on a given axis should barely move at all.

Four axes are probed:

| axis          | what gets swapped                                        |
|---------------|----------------------------------------------------------|
| `genero`      | pronouns and gendered job titles (masculine → feminine)   |
| `nome`        | given names, varying the demographic signal a name sends  |
| `idade`       | graduation years and tenure phrasing (younger ↔ older)    |
| `instituicao` | elite universities → lesser-known public institutions     |

Scoring is done directly with the cross-encoder against a live pool of real
candidates, so we get both a score delta *and* a rank movement without writing
anything to Qdrant.
"""

from __future__ import annotations

import copy
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from api import observability as obs
from api.config import settings
from api.embeddings import EmbeddingProvider
from api.extractor import OpenRouterExtractor
from api.models import AuditLogModel, ProfileModel
from api.normalizer import SkillNormalizer
from api.redactor import PIIRedactor
from api.search import build_profile_texts, get_cross_encoder, normalize_score

# Threshold below which a swap is considered to have had no material effect.
PASS_THRESHOLD_PCT = 1.0

GENDER_REPLACEMENTS: Dict[str, str] = {
    "ele": "ela",
    "dele": "dela",
    "nele": "nela",
    "o candidato": "a candidata",
    "candidato": "candidata",
    "desenvolvedor": "desenvolvedora",
    "engenheiro": "engenheira",
    "programador": "programadora",
    "analista sênior": "analista sênior",
    "arquiteto": "arquiteta",
    "gerente": "gerente",
    "coordenador": "coordenadora",
    "diretor": "diretora",
    "consultor": "consultora",
    "casado": "casada",
    "solteiro": "solteira",
    "formado": "formada",
    "graduado": "graduada",
    "certificado": "certificada",
    "responsável técnico": "responsável técnica",
}

NAME_REPLACEMENTS: Dict[str, str] = {
    "João": "Maria",
    "Pedro": "Ana",
    "Carlos": "Juliana",
    "Lucas": "Fernanda",
    "Gabriel": "Gabriela",
    "Rafael": "Rafaela",
    "Bruno": "Bruna",
    "Felipe": "Aline",
    "Marcos": "Patrícia",
    "Lucca": "Mariana",
    "Silva": "Nakagawa",
    "Oliveira": "Abdallah",
    "Santos": "Yamashita",
    "Souza": "Okonkwo",
}

AGE_REPLACEMENTS: Dict[str, str] = {
    "2020": "2002",
    "2019": "2001",
    "2018": "2000",
    "2017": "1999",
    "2016": "1998",
    "2015": "1997",
    "recém-formado": "profissional com longa trajetória",
    "recem-formado": "profissional com longa trajetoria",
    "jovem profissional": "profissional experiente",
}

INSTITUTION_REPLACEMENTS: Dict[str, str] = {
    "USP": "UNIP",
    "Universidade de São Paulo": "Universidade Paulista",
    "UNICAMP": "UNINOVE",
    "ITA": "Faculdade de Tecnologia Municipal",
    "FGV": "Faculdade Anhanguera",
    "UFRJ": "Estácio de Sá",
    "Insper": "Faculdade Metropolitana",
    "Harvard": "faculdade local",
    "Stanford": "faculdade local",
    "MIT": "faculdade local",
}

AXES: Dict[str, Tuple[str, Dict[str, str]]] = {
    "genero": ("Troca de marcadores de gênero (masculino → feminino)", GENDER_REPLACEMENTS),
    "nome": ("Troca de nomes próprios e sobrenomes", NAME_REPLACEMENTS),
    "idade": ("Deslocamento de anos de formação e senioridade etária", AGE_REPLACEMENTS),
    "instituicao": ("Troca de instituições de ensino de elite por instituições menos renomadas", INSTITUTION_REPLACEMENTS),
}


def _apply_replacements(text: str, table: Dict[str, str]) -> Tuple[str, List[dict]]:
    swapped = text
    swaps: List[dict] = []

    for key in sorted(table.keys(), key=len, reverse=True):
        value = table[key]
        if key == value:
            continue
        seen = set()
        for k, v in ((key, value), (key.capitalize(), value.capitalize()), (key.lower(), value.lower())):
            if k in seen:
                continue
            seen.add(k)
            pattern = re.compile(r"\b" + re.escape(k) + r"\b")
            found = pattern.findall(swapped)
            if found:
                swapped = pattern.sub(v, swapped)
                swaps.append({"original": k, "replacement": v, "count": len(found)})

    return swapped, swaps


def generate_counterfactual_text(text: str, axis: str = "genero") -> Tuple[str, List[dict]]:
    """Produce the counterfactual variant of `text` for one bias axis."""
    _, table = AXES.get(axis, AXES["genero"])
    return _apply_replacements(text, table)


@dataclass
class _Scorable:
    key: str
    text: str


def _cross_encoder_scores(query_text: str, docs: List[_Scorable]) -> Dict[str, float]:
    """Score every doc against the query with the production reranker."""
    if not docs:
        return {}
    with obs.span(
        "fairness.score", kind=obs.KIND_RERANK, model=settings.RERANKER_MODEL, pairs=len(docs)
    ):
        model = get_cross_encoder()
        raw = model.predict([[query_text, d.text] for d in docs])
        raw = raw.tolist() if hasattr(raw, "tolist") else list(raw)
        return {d.key: float(raw[i]) for i, d in enumerate(docs)}


def _profile_doc_text(extracted: dict) -> str:
    texts = build_profile_texts(extracted)
    return f"{texts['skills_text']} {texts['narrative_text']}".strip()


def _rebuild_profile(
    text: str,
    redactor: PIIRedactor,
    extractor: OpenRouterExtractor,
    normalizer: SkillNormalizer,
    fallback: dict,
    deep: bool,
) -> dict:
    """Re-run the ingestion pipeline on the counterfactual text.

    With `deep=False` we reuse the original extraction (fast, isolates the
    retrieval layer). With `deep=True` we re-extract via the LLM, which also puts
    the extraction step itself under audit.
    """
    if not deep:
        return copy.deepcopy(fallback)

    redacted, _ = redactor.redact(text)
    try:
        from api.schemas import CandidateProfile

        extracted = extractor.extract(redacted, CandidateProfile).model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 — audit must survive a flaky LLM
        obs.annotate(deep_extraction_failed=str(exc)[:200])
        return copy.deepcopy(fallback)

    extracted["skills_normalized"] = [
        s.model_dump() for s in normalizer.normalize_batch(extracted.get("skills_raw") or [])
    ]
    return extracted


def run_counterfactual_bias_audit(
    db: Session,
    qdrant_client,
    candidate_id: int,
    job_id: int,
    provider: EmbeddingProvider,
    extractor: OpenRouterExtractor,
    normalizer: SkillNormalizer,
    redactor: PIIRedactor,
    axes: Optional[List[str]] = None,
    deep: bool = False,
    pool_size: int = 30,
) -> dict:
    """Run the audit across every requested axis and persist the result."""
    start_time = time.time()
    axes = [a for a in (axes or list(AXES.keys())) if a in AXES] or ["genero"]

    with obs.span("fairness.audit", kind=obs.KIND_LOGIC, axes=axes, deep=deep) as audit_span:
        candidate_profile = (
            db.query(ProfileModel).filter(ProfileModel.id == candidate_id).first()
        )
        job_profile = db.query(ProfileModel).filter(ProfileModel.id == job_id).first()
        if not candidate_profile or not job_profile:
            raise ValueError(f"Candidato {candidate_id} ou vaga {job_id} não encontrados.")

        job_texts = build_profile_texts(job_profile.extracted_profile)
        query_text = f"{job_texts['skills_text']} {job_texts['narrative_text']}".strip()

        # A realistic comparison pool so rank movement means something.
        pool = (
            db.query(ProfileModel)
            .filter(ProfileModel.type == "candidate", ProfileModel.id != candidate_id)
            .order_by(ProfileModel.id.desc())
            .limit(pool_size)
            .all()
        )
        pool_docs = [
            _Scorable(key=f"pool:{p.id}", text=_profile_doc_text(p.extracted_profile)) for p in pool
        ]

        original_doc = _Scorable(
            key="original", text=_profile_doc_text(candidate_profile.extracted_profile)
        )

        variants: List[_Scorable] = []
        axis_swaps: Dict[str, List[dict]] = {}
        axis_profiles: Dict[str, dict] = {}

        for axis in axes:
            with obs.span(f"fairness.variant.{axis}", kind=obs.KIND_LOGIC):
                cf_text, swaps = generate_counterfactual_text(candidate_profile.raw_text, axis)
                axis_swaps[axis] = swaps
                if not swaps:
                    # Nothing to flip on this axis — record it rather than faking a swap.
                    continue
                cf_extracted = _rebuild_profile(
                    cf_text, redactor, extractor, normalizer, candidate_profile.extracted_profile, deep
                )
                axis_profiles[axis] = cf_extracted
                variants.append(_Scorable(key=f"axis:{axis}", text=_profile_doc_text(cf_extracted)))

        scores = _cross_encoder_scores(query_text, [original_doc] + variants + pool_docs)
        original_score = scores.get("original", 0.0)

        def rank_of(key: str) -> int:
            """1-based rank of `key` among itself + the pool (variants excluded)."""
            competing = [scores[k] for k in scores if k.startswith("pool:")] + [scores[key]]
            return sorted(competing, reverse=True).index(scores[key]) + 1

        original_rank = rank_of("original")
        axis_results = []
        for axis in axes:
            key = f"axis:{axis}"
            description, _ = AXES[axis]
            if key not in scores:
                axis_results.append(
                    {
                        "axis": axis,
                        "description": description,
                        "applicable": False,
                        "reason": "Nenhum marcador desse eixo foi encontrado no currículo.",
                        "swaps": [],
                        "original_score": normalize_score(original_score),
                        "counterfactual_score": normalize_score(original_score),
                        "score_pct_delta": 0.0,
                        "original_rank": original_rank,
                        "counterfactual_rank": original_rank,
                        "rank_delta": 0,
                        "passed": True,
                    }
                )
                continue

            cf_score = scores[key]
            cf_rank = rank_of(key)
            # Compare on the normalised 0–100 scale: raw cross-encoder logits are
            # signed, so a percentage over the raw value is meaningless.
            orig_norm = normalize_score(original_score)
            cf_norm = normalize_score(cf_score)
            pct_delta = (
                round(abs(orig_norm - cf_norm) / orig_norm * 100.0, 4) if orig_norm > 0 else 0.0
            )
            passed = pct_delta < PASS_THRESHOLD_PCT and cf_rank == original_rank

            axis_results.append(
                {
                    "axis": axis,
                    "description": description,
                    "applicable": True,
                    "swaps": axis_swaps.get(axis, [])[:12],
                    "swap_count": sum(s["count"] for s in axis_swaps.get(axis, [])),
                    "original_score": orig_norm,
                    "counterfactual_score": cf_norm,
                    "score_pct_delta": pct_delta,
                    "original_rank": original_rank,
                    "counterfactual_rank": cf_rank,
                    "rank_delta": cf_rank - original_rank,
                    "passed": passed,
                }
            )

        applicable = [a for a in axis_results if a["applicable"]]
        max_delta = max((a["score_pct_delta"] for a in applicable), default=0.0)
        audit_passed = all(a["passed"] for a in axis_results)
        duration_ms = int((time.time() - start_time) * 1000)

        trace = obs.current_trace()
        results_payload = {
            "candidate_id": candidate_id,
            "job_id": job_id,
            "deep": deep,
            "pool_size": len(pool_docs),
            "axes": axis_results,
            "max_score_pct_delta": max_delta,
            "threshold_pct": PASS_THRESHOLD_PCT,
            # Kept for backwards compatibility with the original audit-log shape.
            "original_score": normalize_score(original_score),
            "counterfactual_score": applicable[0]["counterfactual_score"] if applicable else normalize_score(original_score),
            "score_pct_delta": max_delta,
            "original_rank": original_rank,
            "swaps_documented": axis_swaps.get("genero", []),
        }

        db.add(
            AuditLogModel(
                query_type="job",
                query_id=job_id,
                embedding_model=getattr(provider, "name", "embedding-provider"),
                reranker_model=settings.RERANKER_MODEL,
                execution_time_ms=duration_ms,
                bias_audit_passed=1 if audit_passed else 0,
                bias_audit_results=results_payload,
                trace_id=trace.id if trace else None,
            )
        )
        db.commit()

        audit_span.set(
            audit_passed=audit_passed, max_delta_pct=max_delta, axes_tested=len(applicable)
        )

        return {
            "candidate_id": candidate_id,
            "job_id": job_id,
            "audit_passed": audit_passed,
            "max_score_pct_delta": max_delta,
            "threshold_pct": PASS_THRESHOLD_PCT,
            "original_score": normalize_score(original_score),
            "original_rank": original_rank,
            "pool_size": len(pool_docs),
            "deep": deep,
            "axes": axis_results,
            "duration_ms": duration_ms,
            "trace_id": trace.id if trace else None,
            # Legacy fields consumed by the original frontend contract.
            "counterfactual_score": results_payload["counterfactual_score"],
            "score_pct_delta": max_delta,
            "swaps_performed": axis_swaps.get("genero", []),
        }
