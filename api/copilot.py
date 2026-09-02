"""The recruiting copilot: a tool-calling agent over the ATS.

The model never touches the database directly. It picks a tool, we execute it in
Python with the recruiter's own session, and hand back a compact digest. Each
tool also emits a *card* — a structured payload the frontend renders as a ranked
list, a funnel, a fairness report — so the conversation produces real UI, not
walls of text.

Every turn, every tool call and every model round-trip lands in the trace, which
is what makes the copilot debuggable instead of magic.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from api import ats
from api import observability as obs
from api.database import get_qdrant
from api.embeddings import get_embedding_provider
from api.explain import generate_match_explanation
from api.llm import LLMClient, LLMNotConfigured, get_llm
from api.models import STAGE_LABELS, STAGES, CandidateModel, JobModel
from api.search import hybrid_search_and_rerank

MAX_TOOL_ROUNDS = 5

SYSTEM_PROMPT = """Você é o Copiloto do Resume Ranker, um ATS com ranqueamento de candidatos por IA.
Você conversa com recrutadores em português do Brasil.

Como você trabalha:
- Use as ferramentas disponíveis para consultar dados reais. NUNCA invente candidatos, vagas, \
scores ou números — se não tiver o dado, chame a ferramenta ou diga que não sabe.
- Ao apresentar um ranking, a interface JÁ RENDERIZA a lista completa com nome, score, aderência \
e competências logo abaixo da sua resposta. Não escreva tabelas markdown nem repita a lista: \
comente em 2 a 4 frases apenas os primeiros colocados, com o motivo objetivo (cobertura de \
skills, anos de experiência, lacunas concretas).
- Quando o recrutador pedir uma ação (mover alguém de etapa, ranquear, auditar viés), execute \
com a ferramenta correspondente e confirme o que foi feito.
- Nunca comente gênero, idade, aparência, origem ou qualquer característica protegida de um \
candidato. Se for perguntado sobre isso, explique que o sistema é desenhado para não usar esses \
sinais e ofereça a auditoria de viés.
- Seja direto. Respostas curtas, com bullets quando ajudar. Sem preâmbulos do tipo "claro!".
"""

TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "listar_vagas",
            "description": "Lista as vagas cadastradas no ATS com o funil de candidaturas de cada uma.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filtra por status: 'open', 'paused' ou 'closed'. Omita para trazer todas.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ranquear_candidatos",
            "description": (
                "Executa a busca híbrida + reranking e devolve os candidatos mais aderentes a uma vaga, "
                "já ordenados, com score, cobertura de skills e lacunas."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "integer", "description": "ID da vaga."},
                    "top_n": {"type": "integer", "description": "Quantidade de candidatos a retornar (padrão 8)."},
                    "min_experience_years": {
                        "type": "number",
                        "description": "Filtro rígido: anos mínimos de experiência.",
                    },
                    "seniorities": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filtro rígido por senioridade: Estágio, Júnior, Pleno, Sênior, Especialista/Lead.",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_candidatos",
            "description": "Busca semântica livre no banco de talentos a partir de uma descrição em linguagem natural.",
            "parameters": {
                "type": "object",
                "properties": {
                    "consulta": {
                        "type": "string",
                        "description": "Descrição do perfil desejado, ex: 'engenheiro de dados com Kafka e Airflow'.",
                    },
                    "top_n": {"type": "integer", "description": "Quantidade de resultados (padrão 8)."},
                },
                "required": ["consulta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detalhar_candidato",
            "description": "Traz o perfil completo de um candidato: skills, experiência, formação, certificações e candidaturas.",
            "parameters": {
                "type": "object",
                "properties": {"candidate_id": {"type": "integer"}},
                "required": ["candidate_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explicar_match",
            "description": (
                "Gera a análise detalhada de aderência entre um candidato e uma vaga, com evidências "
                "citadas literalmente do currículo e perguntas de entrevista sugeridas."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "integer"},
                    "job_id": {"type": "integer"},
                },
                "required": ["candidate_id", "job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mover_candidatura",
            "description": "Move uma candidatura para outra etapa do funil.",
            "parameters": {
                "type": "object",
                "properties": {
                    "application_id": {"type": "integer"},
                    "stage": {
                        "type": "string",
                        "description": "Etapa destino: sourced, screening, interview, offer, hired ou rejected.",
                    },
                    "nota": {"type": "string", "description": "Observação opcional registrada na timeline."},
                },
                "required": ["application_id", "stage"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resumo_pipeline",
            "description": "Números gerais do ATS: vagas abertas, candidatos, distribuição por etapa e score médio.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "auditar_vies",
            "description": (
                "Roda a auditoria contrafactual de viés para um par candidato/vaga, medindo quanto o score "
                "muda ao trocar marcadores de gênero, nome, idade e instituição de ensino."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "integer"},
                    "job_id": {"type": "integer"},
                },
                "required": ["candidate_id", "job_id"],
            },
        },
    },
]


class ToolExecutionError(RuntimeError):
    pass


class CopilotTools:
    """Executes the tools against the real ATS, returning (digest, card)."""

    def __init__(self, db: Session):
        self.db = db

    # ── helpers ─────────────────────────────────────────────────────────
    def _candidate_row(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        cand = entry["candidate"]
        signals = entry.get("signals", {})
        return {
            "rank": entry["rank"],
            "candidate_id": cand["id"],
            "application_id": entry.get("application_id"),
            "name": cand["display_name"],
            "headline": cand["headline"],
            "seniority": cand["seniority"],
            "experience_years": cand["experience_years"],
            "score": entry["score_normalized"],
            "fit": entry["fit"],
            "stage": entry.get("stage"),
            "matched_skills": signals.get("matched_skills", [])[:8],
            "missing_skills": signals.get("missing_skills", [])[:6],
            "skill_coverage": signals.get("skill_coverage"),
        }

    # ── tools ───────────────────────────────────────────────────────────
    def listar_vagas(self, status: Optional[str] = None) -> Dict[str, Any]:
        q = self.db.query(JobModel)
        if status:
            q = q.filter(JobModel.status == status)
        jobs = [ats.serialize_job(j, self.db) for j in q.order_by(JobModel.id).all()]
        digest = [
            {
                "job_id": j["id"],
                "title": j["title"],
                "seniority": j["seniority"],
                "location": j["location"],
                "status": j["status"],
                "candidaturas": j["applications_count"],
            }
            for j in jobs
        ]
        return {"digest": digest, "card": {"type": "jobs", "jobs": jobs}}

    def ranquear_candidatos(
        self,
        job_id: int,
        top_n: int = 8,
        min_experience_years: Optional[float] = None,
        seniorities: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        outcome = ats.rank_job(
            self.db,
            job_id=job_id,
            top_n=max(1, min(int(top_n or 8), 20)),
            min_experience_years=min_experience_years,
            seniorities=seniorities,
        )
        rows = [self._candidate_row(e) for e in outcome["results"]]
        return {
            "digest": {"vaga": outcome["job"]["title"], "total": len(rows), "candidatos": rows},
            "card": {
                "type": "ranking",
                "job": outcome["job"],
                "results": outcome["results"],
                "trace_id": outcome["trace_id"],
            },
        }

    def buscar_candidatos(self, consulta: str, top_n: int = 8) -> Dict[str, Any]:
        results = hybrid_search_and_rerank(
            client=get_qdrant(),
            collection="candidates",
            query_text=consulta,
            skills_text=consulta,
            provider=get_embedding_provider(),
            top_k_hybrid=25,
            top_n_final=max(1, min(int(top_n or 8), 20)),
        )
        profile_ids = [r["id"] for r in results]
        candidates = {
            c.profile_id: c
            for c in self.db.query(CandidateModel).filter(CandidateModel.profile_id.in_(profile_ids)).all()
        }
        rows, cards = [], []
        for r in results:
            cand = candidates.get(r["id"])
            if not cand:
                continue
            serialized = ats.serialize_candidate(cand)
            cards.append({**serialized, "score": r["score_normalized"], "rank": r["rank"]})
            rows.append(
                {
                    "rank": r["rank"],
                    "candidate_id": cand.id,
                    "name": cand.display_name,
                    "headline": serialized["headline"],
                    "score": r["score_normalized"],
                    "skills": serialized["skills"][:8],
                }
            )
        return {
            "digest": {"consulta": consulta, "encontrados": len(rows), "candidatos": rows},
            "card": {"type": "candidates", "query": consulta, "candidates": cards},
        }

    def detalhar_candidato(self, candidate_id: int) -> Dict[str, Any]:
        cand = self.db.query(CandidateModel).filter(CandidateModel.id == candidate_id).first()
        if not cand:
            raise ToolExecutionError(f"Candidato {candidate_id} não encontrado.")
        serialized = ats.serialize_candidate(cand, include_profile=True)
        extracted = (cand.profile.extracted_profile if cand.profile else {}) or {}
        applications = [
            {
                "application_id": a.id,
                "job_id": a.job_id,
                "job_title": a.job.title if a.job else None,
                "stage": a.stage,
                "stage_label": STAGE_LABELS.get(a.stage, a.stage),
                "ai_score": a.ai_score,
                "ai_fit": a.ai_fit,
            }
            for a in cand.applications
        ]
        digest = {
            "candidate_id": cand.id,
            "nome": cand.display_name,
            "headline": serialized["headline"],
            "senioridade": serialized["seniority"],
            "anos_experiencia": serialized["experience_years"],
            "skills": serialized["skills"],
            "certificacoes": serialized["certifications"],
            "idiomas": serialized["languages"],
            "destaques": extracted.get("highlights") or [],
            "candidaturas": applications,
        }
        return {
            "digest": digest,
            "card": {"type": "candidate", "candidate": serialized, "applications": applications},
        }

    def explicar_match(self, candidate_id: int, job_id: int) -> Dict[str, Any]:
        cand = self.db.query(CandidateModel).filter(CandidateModel.id == candidate_id).first()
        job = self.db.query(JobModel).filter(JobModel.id == job_id).first()
        if not cand or not job:
            raise ToolExecutionError("Candidato ou vaga não encontrados.")

        explanation = generate_match_explanation(
            candidate_raw_text=cand.profile.raw_text,
            candidate_redacted_text=cand.profile.redacted_text,
            job_raw_text=job.profile.raw_text,
            candidate_extracted=cand.profile.extracted_profile,
            job_extracted=job.profile.extracted_profile,
        )
        digest = {
            "candidato": cand.display_name,
            "vaga": job.title,
            "aderencia": explanation["fit"],
            "resumo": explanation["summary"],
            "pontos_fortes": explanation["strengths"],
            "lacunas": explanation["gaps"],
            "citacoes_verificadas": explanation["hallucination_check"],
        }
        return {
            "digest": digest,
            "card": {
                "type": "explanation",
                "candidate": ats.serialize_candidate(cand),
                "job": ats.serialize_job(job),
                "explanation": explanation,
            },
        }

    def mover_candidatura(self, application_id: int, stage: str, nota: Optional[str] = None) -> Dict[str, Any]:
        if stage not in STAGES:
            raise ToolExecutionError(
                f"Etapa '{stage}' inválida. Use uma de: {', '.join(STAGES)}."
            )
        app = ats.move_application(self.db, application_id, stage, actor="Copiloto IA", note=nota)
        serialized = ats.serialize_application(app)
        return {
            "digest": {
                "application_id": app.id,
                "candidato": app.candidate.display_name if app.candidate else None,
                "vaga": app.job.title if app.job else None,
                "nova_etapa": STAGE_LABELS.get(stage, stage),
            },
            "card": {"type": "application", "application": serialized},
        }

    def resumo_pipeline(self) -> Dict[str, Any]:
        overview = ats.pipeline_overview(self.db)
        return {"digest": overview, "card": {"type": "overview", "overview": overview}}

    def auditar_vies(self, candidate_id: int, job_id: int) -> Dict[str, Any]:
        from api.fairness import run_counterfactual_bias_audit
        from api.services import get_extractor, get_normalizer, get_redactor

        cand = self.db.query(CandidateModel).filter(CandidateModel.id == candidate_id).first()
        job = self.db.query(JobModel).filter(JobModel.id == job_id).first()
        if not cand or not job:
            raise ToolExecutionError("Candidato ou vaga não encontrados.")

        result = run_counterfactual_bias_audit(
            db=self.db,
            qdrant_client=get_qdrant(),
            candidate_id=cand.profile_id,
            job_id=job.profile_id,
            provider=get_embedding_provider(),
            extractor=get_extractor(),
            normalizer=get_normalizer(),
            redactor=get_redactor(),
        )
        digest = {
            "candidato": cand.display_name,
            "vaga": job.title,
            "aprovado": result["audit_passed"],
            "maior_variacao_pct": result["max_score_pct_delta"],
            "limite_pct": result["threshold_pct"],
            "eixos": [
                {"eixo": a["axis"], "variacao_pct": a["score_pct_delta"], "passou": a["passed"]}
                for a in result["axes"]
            ],
        }
        return {
            "digest": digest,
            "card": {
                "type": "fairness",
                "candidate": ats.serialize_candidate(cand),
                "job": ats.serialize_job(job),
                "audit": result,
            },
        }


def _tool_registry(tools: CopilotTools) -> Dict[str, Callable[..., Dict[str, Any]]]:
    return {
        "listar_vagas": tools.listar_vagas,
        "ranquear_candidatos": tools.ranquear_candidatos,
        "buscar_candidatos": tools.buscar_candidatos,
        "detalhar_candidato": tools.detalhar_candidato,
        "explicar_match": tools.explicar_match,
        "mover_candidatura": tools.mover_candidatura,
        "resumo_pipeline": tools.resumo_pipeline,
        "auditar_vies": tools.auditar_vies,
    }


def _context_preamble(db: Session, job_id: Optional[int]) -> str:
    """Give the model the lay of the land so it doesn't have to ask for IDs."""
    jobs = db.query(JobModel).order_by(JobModel.id).all()
    lines = [
        f"- vaga {j.id}: {j.title} ({j.seniority or 'n/d'}, {j.location or 'n/d'}, status {j.status})"
        for j in jobs[:25]
    ]
    total_candidates = db.query(CandidateModel).count()
    context = (
        f"Contexto atual do ATS — {len(jobs)} vagas e {total_candidates} candidatos no banco de talentos.\n"
        + ("Vagas:\n" + "\n".join(lines) if lines else "Nenhuma vaga cadastrada ainda.")
    )
    if job_id:
        context += f"\n\nO recrutador está com a vaga {job_id} aberta na tela. Assuma essa vaga quando ele não especificar outra."
    return context


def run_copilot(
    db: Session,
    message: str,
    history: Optional[List[Dict[str, str]]] = None,
    job_id: Optional[int] = None,
    client: Optional[LLMClient] = None,
) -> Dict[str, Any]:
    """One conversational turn: reason, call tools, answer."""
    llm = client or get_llm()
    tools = CopilotTools(db)
    registry = _tool_registry(tools)

    with obs.span("copilot.turn", kind=obs.KIND_LOGIC, job_id=job_id) as turn_span:
        turn_span.record_input(message)

        if not llm.is_configured:
            raise LLMNotConfigured(
                "O copiloto precisa da OPENROUTER_API_KEY configurada em api/.env."
            )

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": _context_preamble(db, job_id)},
        ]
        for turn in (history or [])[-10:]:
            role = turn.get("role")
            if role in ("user", "assistant") and turn.get("content"):
                messages.append({"role": role, "content": turn["content"]})
        messages.append({"role": "user", "content": message})

        cards: List[Dict[str, Any]] = []
        executed: List[Dict[str, Any]] = []

        for round_index in range(MAX_TOOL_ROUNDS):
            response = llm.complete(
                messages,
                span_name=f"llm.copilot.round{round_index + 1}",
                tools=TOOLS,
                temperature=0.3,
            )

            if not response.tool_calls:
                turn_span.set(rounds=round_index + 1, tools_used=[t["name"] for t in executed])
                turn_span.record_output(response.content)
                trace = obs.current_trace()
                return {
                    "reply": response.content or "Não consegui formular uma resposta.",
                    "cards": cards,
                    "tool_calls": executed,
                    "model": response.model,
                    "trace_id": trace.id if trace else None,
                }

            messages.append(
                {
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": response.tool_calls,
                }
            )

            for call in response.tool_calls:
                fn = (call.get("function") or {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}

                with obs.span(f"tool.{name}", kind=obs.KIND_TOOL) as tool_span:
                    tool_span.record_input(args)
                    handler = registry.get(name)
                    if handler is None:
                        result = {"erro": f"Ferramenta '{name}' não existe."}
                        tool_span.set(unknown_tool=True)
                    else:
                        try:
                            outcome = handler(**args)
                            result = outcome["digest"]
                            if outcome.get("card"):
                                cards.append(outcome["card"])
                        except Exception as exc:  # noqa: BLE001 — reported back to the model
                            result = {"erro": str(exc)[:400]}
                            tool_span.set(tool_error=str(exc)[:300])
                    tool_span.record_output(result)

                executed.append({"name": name, "arguments": args, "ok": "erro" not in (result or {})})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", name),
                        "name": name,
                        "content": json.dumps(result, ensure_ascii=False, default=str)[:12000],
                    }
                )

        # Ran out of rounds — ask for a final answer without tools.
        final = llm.complete(
            messages + [{"role": "user", "content": "Responda agora ao recrutador com o que você já apurou."}],
            span_name="llm.copilot.final",
            temperature=0.3,
        )
        trace = obs.current_trace()
        turn_span.set(rounds=MAX_TOOL_ROUNDS, exhausted=True)
        return {
            "reply": final.content or "Não consegui concluir a análise.",
            "cards": cards,
            "tool_calls": executed,
            "model": final.model,
            "trace_id": trace.id if trace else None,
        }
