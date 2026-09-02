"""Structured extraction of resumes and job descriptions.

Input is always the *redacted* text — the extractor is the first component that
talks to an external model, and the PII boundary sits immediately before it.
"""

from __future__ import annotations

from typing import Optional, Type, TypeVar

from pydantic import BaseModel

from api import observability as obs
from api.llm import LLMClient, get_llm

T = TypeVar("T", bound=BaseModel)

SYSTEM_PROMPT = (
    "Você é um assistente de IA especialista em recrutamento e seleção de talentos técnicos. "
    "Sua tarefa é analisar o texto de um currículo ou de uma vaga de emprego (previamente "
    "higienizado e anonimizado) e extrair de forma estruturada as informações necessárias "
    "para preencher o perfil padronizado.\n\n"
    "Instruções críticas:\n"
    "1. Mapeie a senioridade para uma das categorias do enum: 'Estágio', 'Júnior', 'Pleno', "
    "'Sênior' ou 'Especialista/Lead'.\n"
    "2. Mantenha os nomes das competências (skills_raw) fiéis ao que está escrito no texto "
    "(ex: 'JS', 'ReactJS', 'Python 3', 'Kubernetes'). Não normalize nem traduza agora.\n"
    "3. Calcule com precisão os anos totais de experiência profissional a partir dos períodos "
    "de cada cargo. Não conte em dobro períodos sobrepostos. Sem experiência clara, retorne 0.0.\n"
    "4. Consolide responsabilidades e escopo de atuação em `narrative_experience`: um parágrafo "
    "longo e rico com a história profissional do candidato ou o contexto da vaga.\n"
    "5. Se o texto contiver tokens de anonimização (ex: [NOME_REDACT_1], [LOCALIZACAO_REDACT_2]), "
    "mantenha-os exatamente como estão. Nunca tente desanonimizá-los ou inferir os dados reais."
)


class OpenRouterExtractor:
    """Thin, traced wrapper that turns redacted text into a validated profile."""

    def __init__(self, api_key: Optional[str] = None, default_model: Optional[str] = None):
        self.client = (
            LLMClient(api_key=api_key, model=default_model)
            if (api_key or default_model)
            else get_llm("extraction")
        )

    @property
    def model(self) -> str:
        return self.client.model

    def extract(self, text: str, schema_class: Type[T]) -> T:
        with obs.span(
            f"extract.{schema_class.__name__}", kind=obs.KIND_LOGIC, chars=len(text or "")
        ) as sp:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Analise e extraia as informações estruturadas do texto a seguir:\n\n"
                        f"---\n{text}\n---"
                    ),
                },
            ]
            profile = self.client.structured(
                messages, schema_class, span_name="llm.extract", temperature=0.1
            )
            sp.set(
                seniority=getattr(profile, "seniority", None),
                skills_found=len(getattr(profile, "skills_raw", []) or []),
                experience_years=getattr(profile, "experience_years", None),
            )
            return profile
