"""Conversational interface to the ATS."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api import observability as obs
from api.copilot import TOOLS, run_copilot
from api.database import get_db
from api.llm import LLMNotConfigured
from api.schemas import ChatRequest

router = APIRouter(prefix="/copilot", tags=["copiloto"])

SUGGESTIONS = [
    "Quais são os 5 candidatos mais aderentes à vaga de Engenheiro de Dados?",
    "Me mostra o resumo do pipeline de contratações.",
    "Busque candidatos com experiência em Kubernetes e observabilidade.",
    "Explique por que o primeiro colocado se encaixa na vaga.",
    "Rode a auditoria de viés do candidato 1 na vaga 1.",
]


@router.post("/chat")
def chat(body: ChatRequest, db: Session = Depends(get_db)):
    """One turn of conversation. May execute ATS tools and return UI cards."""
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Mensagem vazia.")

    with obs.trace("copilot.chat", job_id=body.job_id, message_chars=len(body.message)):
        try:
            return run_copilot(
                db,
                message=body.message,
                history=[m.model_dump() for m in body.history],
                job_id=body.job_id,
            )
        except LLMNotConfigured as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Falha no copiloto: {e}") from e


@router.get("/tools")
def list_tools():
    """Expose the tool catalogue so the UI can show what the copilot can do."""
    return {
        "tools": [
            {
                "name": t["function"]["name"],
                "description": t["function"]["description"],
                "parameters": list((t["function"]["parameters"].get("properties") or {}).keys()),
            }
            for t in TOOLS
        ],
        "suggestions": SUGGESTIONS,
    }
