"""Evidence-backed explanations for a candidate↔job match.

Two layers, deliberately separated:

* **deterministic** — skill overlap, seniority gap and experience delta are
  computed in Python from the ESCO-normalised profiles. These numbers are not
  negotiable and never come from a model.
* **generative** — the LLM writes the narrative, but every direct quote it
  produces is checked verbatim against the candidate's own text. Unverified
  quotes are kept and flagged rather than hidden, so a recruiter can see exactly
  where the model drifted.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from api import observability as obs
from api.llm import LLMClient, LLMNotConfigured, get_llm
from api.schemas import SENIORITY_ORDER, SeniorityEnum

FIT_LABELS = ("forte", "moderado", "baixo")


class ExplanationSchema(BaseModel):
    fit: str = Field(description="Aderência geral do candidato à vaga: 'forte', 'moderado' ou 'baixo'.")
    confidence: float = Field(description="Confiança da própria análise, de 0.0 a 1.0.")
    summary: str = Field(description="Veredito em uma única frase, direta, para o recrutador.")
    explanation: str = Field(
        description="Análise em 3 a 5 frases justificando o encaixe ou o descompasso, citando evidências concretas."
    )
    strengths: List[str] = Field(description="Pontos fortes do candidato para esta vaga (máx. 4).")
    gaps: List[str] = Field(description="Lacunas ou riscos em relação aos requisitos (máx. 4).")
    citations: List[str] = Field(
        description="Trechos LITERAIS e exatos do currículo que sustentam as afirmações. Copie palavra por palavra."
    )
    interview_questions: List[str] = Field(
        description="2 a 3 perguntas de entrevista que investigam justamente as lacunas identificadas."
    )


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _canonical(text: str) -> str:
    """Case-, accent- and whitespace-insensitive form used for quote matching."""
    return re.sub(r"\s+", " ", _strip_accents(text or "").strip().lower())


def verify_citation(citation: str, source_text: str) -> bool:
    """True when the quote appears verbatim in the source (ignoring case/accents/spacing)."""
    if not citation or not source_text:
        return False

    clean_citation = _canonical(citation)
    if len(clean_citation) > 2 and clean_citation[0] in ('"', "'", "“", "”") :
        clean_citation = clean_citation.strip("\"'“”").strip()
    if not clean_citation:
        return False

    return clean_citation in _canonical(source_text)


def _skill_labels(profile: dict) -> Dict[str, str]:
    """Map canonical label → display label for every mapped ESCO skill."""
    out: Dict[str, str] = {}
    for s in profile.get("skills_normalized") or []:
        label = s.get("preferred_label")
        if label:
            out[_canonical(label)] = label
    for raw in profile.get("skills_raw") or []:
        key = _canonical(raw)
        out.setdefault(key, raw)
    return out


def compute_match_signals(candidate_extracted: dict, job_extracted: dict) -> Dict[str, Any]:
    """Deterministic comparison of a candidate against a job's requirements."""
    cand_skills = _skill_labels(candidate_extracted)
    job_skills = _skill_labels(job_extracted)

    matched = [job_skills[k] for k in job_skills if k in cand_skills]
    missing = [job_skills[k] for k in job_skills if k not in cand_skills]
    extra = [cand_skills[k] for k in cand_skills if k not in job_skills]

    must_have = [s for s in (job_extracted.get("must_have_skills") or [])]
    must_have_missing = [s for s in must_have if _canonical(s) not in cand_skills]
    must_have_matched = [s for s in must_have if _canonical(s) in cand_skills]

    cand_years = float(candidate_extracted.get("experience_years") or 0.0)
    job_years = float(job_extracted.get("experience_years") or 0.0)

    def seniority_index(value) -> Optional[int]:
        try:
            return SENIORITY_ORDER[SeniorityEnum(value)]
        except (ValueError, KeyError):
            return None

    cand_sen = seniority_index(candidate_extracted.get("seniority"))
    job_sen = seniority_index(job_extracted.get("seniority"))

    coverage = round(len(matched) / len(job_skills), 3) if job_skills else 0.0
    must_have_coverage = (
        round(len(must_have_matched) / len(must_have), 3) if must_have else None
    )

    return {
        "matched_skills": sorted(matched),
        "missing_skills": sorted(missing),
        "extra_skills": sorted(extra)[:15],
        "must_have_matched": must_have_matched,
        "must_have_missing": must_have_missing,
        "must_have_coverage": must_have_coverage,
        "skill_coverage": coverage,
        "candidate_experience_years": cand_years,
        "job_experience_years": job_years,
        "experience_delta_years": round(cand_years - job_years, 1),
        "meets_experience": cand_years >= job_years if job_years else True,
        "candidate_seniority": candidate_extracted.get("seniority"),
        "job_seniority": job_extracted.get("seniority"),
        "seniority_gap": (cand_sen - job_sen) if (cand_sen is not None and job_sen is not None) else None,
        "candidate_certifications": candidate_extracted.get("certifications") or [],
        "job_certifications": job_extracted.get("certifications") or [],
    }


SYSTEM_PROMPT = (
    "Você é um analista de recrutamento técnico. Sua função é explicar, com transparência e "
    "evidências, por que um candidato é ou não adequado a uma vaga.\n\n"
    "Regras obrigatórias:\n"
    "1. O campo 'citations' deve conter apenas trechos LITERAIS, copiados palavra por palavra do "
    "texto do currículo fornecido. Nunca parafraseie, resuma ou invente uma citação. Se não houver "
    "trecho literal que sustente um ponto, não cite nada para ele.\n"
    "2. Baseie-se nos sinais determinísticos fornecidos (cobertura de skills, anos de experiência, "
    "senioridade). Eles foram calculados por código e são a verdade; não os contradiga.\n"
    "3. Nunca comente, infira ou mencione gênero, idade, origem, estado civil, aparência ou "
    "qualquer característica protegida. Se o texto contiver tokens como [NOME_REDACT_1], trate-os "
    "como identificadores neutros.\n"
    "4. Escreva em português do Brasil, de forma objetiva e sem floreios."
)


def _mock_explanation(
    candidate_extracted: dict,
    job_extracted: dict,
    candidate_raw_text: str,
    candidate_redacted_text: str,
    signals: Dict[str, Any],
    reason: str,
) -> Dict[str, Any]:
    """Deterministic fallback used when no LLM is configured or the call fails."""
    matched = signals["matched_skills"]
    missing = signals["missing_skills"]
    coverage_pct = round(signals["skill_coverage"] * 100)

    fit = "forte" if coverage_pct >= 70 else "moderado" if coverage_pct >= 40 else "baixo"
    summary = (
        f"Cobre {coverage_pct}% das competências da vaga "
        f"({len(matched)} de {len(matched) + len(missing)}) com "
        f"{signals['candidate_experience_years']:.0f} anos de experiência."
    )
    explanation = summary
    if matched:
        explanation += " Competências em comum: " + ", ".join(matched[:6]) + "."
    if missing:
        explanation += " Lacunas: " + ", ".join(missing[:6]) + "."

    quote = (candidate_extracted.get("narrative_experience") or candidate_redacted_text or "")[:120]
    citations = [
        {
            "text": quote,
            "verified": verify_citation(quote, candidate_raw_text)
            or verify_citation(quote, candidate_redacted_text),
        }
    ] if quote else []

    return {
        "fit": fit,
        "confidence": 0.4,
        "summary": summary,
        "explanation": explanation,
        "strengths": matched[:4],
        "gaps": missing[:4],
        "citations": citations,
        "interview_questions": [
            f"Conte sobre um projeto em que você usou {missing[0]}." if missing else
            "Descreva o projeto mais complexo que você entregou nos últimos 12 meses."
        ],
        "signals": signals,
        "generated_by": "fallback-deterministico",
        "fallback_reason": reason,
        "hallucination_check": {"total": len(citations), "verified": sum(1 for c in citations if c["verified"])},
    }


def generate_match_explanation(
    candidate_raw_text: str,
    candidate_redacted_text: str,
    job_raw_text: str,
    candidate_extracted: dict,
    job_extracted: dict,
    api_key: Optional[str] = None,
    client: Optional[LLMClient] = None,
) -> dict:
    """Produce a verified, evidence-backed explanation of one match."""
    with obs.span("explain.match", kind=obs.KIND_LOGIC) as sp:
        signals = compute_match_signals(candidate_extracted, job_extracted)
        sp.set(
            skill_coverage=signals["skill_coverage"],
            matched=len(signals["matched_skills"]),
            missing=len(signals["missing_skills"]),
        )

        llm = client or (LLMClient(api_key=api_key) if api_key else get_llm("explanation"))
        if not llm.is_configured:
            sp.set(mode="fallback")
            return _mock_explanation(
                candidate_extracted,
                job_extracted,
                candidate_raw_text,
                candidate_redacted_text,
                signals,
                "OPENROUTER_API_KEY não configurada",
            )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "SINAIS DETERMINÍSTICOS (calculados por código, são a verdade):\n"
                    f"{json.dumps(signals, ensure_ascii=False, indent=2)}\n\n"
                    "PERFIL EXTRAÍDO DO CANDIDATO:\n"
                    f"{json.dumps(candidate_extracted, ensure_ascii=False)}\n\n"
                    "TEXTO DO CURRÍCULO (anonimizado — cite literalmente daqui):\n"
                    f"{candidate_redacted_text[:8000]}\n\n"
                    "REQUISITOS EXTRAÍDOS DA VAGA:\n"
                    f"{json.dumps(job_extracted, ensure_ascii=False)}\n\n"
                    "DESCRIÇÃO DA VAGA:\n"
                    f"{job_raw_text[:4000]}\n\n"
                    "Produza a análise estruturada."
                ),
            },
        ]

        try:
            result = llm.structured(
                messages, ExplanationSchema, span_name="llm.explain", temperature=0.2
            )
        except (LLMNotConfigured, Exception) as exc:  # noqa: BLE001 — never fail the request
            sp.set(mode="fallback", llm_error=str(exc)[:300])
            return _mock_explanation(
                candidate_extracted,
                job_extracted,
                candidate_raw_text,
                candidate_redacted_text,
                signals,
                f"Falha na chamada ao LLM: {str(exc)[:200]}",
            )

        # Citation guardrail — the whole point of the module.
        verified_citations = []
        for quote in result.citations:
            verified = verify_citation(quote, candidate_raw_text) or verify_citation(
                quote, candidate_redacted_text
            )
            verified_citations.append({"text": quote, "verified": verified})

        verified_count = sum(1 for c in verified_citations if c["verified"])
        total = len(verified_citations)
        sp.set(
            mode="llm",
            citations_total=total,
            citations_verified=verified_count,
            hallucination_rate=round(1 - (verified_count / total), 3) if total else 0.0,
        )

        fit = result.fit.strip().lower()
        if fit not in FIT_LABELS:
            fit = "moderado"

        return {
            "fit": fit,
            "confidence": max(0.0, min(1.0, float(result.confidence))),
            "summary": result.summary,
            "explanation": result.explanation,
            "strengths": result.strengths[:4],
            "gaps": result.gaps[:4],
            "citations": verified_citations,
            "interview_questions": result.interview_questions[:3],
            "signals": signals,
            "generated_by": llm.model,
            "hallucination_check": {
                "total": total,
                "verified": verified_count,
                "unverified": total - verified_count,
                "rate": round(1 - (verified_count / total), 3) if total else 0.0,
            },
        }
