from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class SeniorityEnum(str, Enum):
    ESTAGIO = "Estágio"
    JUNIOR = "Júnior"
    PLENO = "Pleno"
    SENIOR = "Sênior"
    ESPECIALISTA_LEAD = "Especialista/Lead"


SENIORITY_ORDER = {
    SeniorityEnum.ESTAGIO: 0,
    SeniorityEnum.JUNIOR: 1,
    SeniorityEnum.PLENO: 2,
    SeniorityEnum.SENIOR: 3,
    SeniorityEnum.ESPECIALISTA_LEAD: 4,
}


class EducationEntry(BaseModel):
    degree: str = Field(description="Grau acadêmico obtido ou em andamento (ex: Bacharelado, Mestrado, Técnico).")
    field: str = Field(description="Área ou curso de estudo (ex: Ciência da Computação, Engenharia Civil).")
    year: Optional[int] = Field(None, description="Ano de conclusão ou previsão de conclusão (4 dígitos).")


class BaseProfile(BaseModel):
    seniority: SeniorityEnum = Field(
        description="Nível de senioridade inferido com base na experiência descrita."
    )
    skills_raw: List[str] = Field(
        description="Competências técnicas (linguagens, frameworks, ferramentas) e comportamentais encontradas no texto."
    )
    experience_years: float = Field(
        description="Anos totais de experiência profissional acumulada, inferidos dos períodos de atuação."
    )
    education: List[EducationEntry] = Field(description="Entradas de formação acadêmica.")
    certifications: List[str] = Field(
        description="Certificações mencionadas (ex: AWS Certified Cloud Practitioner, Scrum Master)."
    )
    languages: List[str] = Field(description="Idiomas de domínio mencionados no texto.")
    narrative_experience: str = Field(
        description=(
            "Texto corrido e detalhado descrevendo a trajetória profissional, responsabilidades, "
            "projetos marcantes e contextos. Base para o vetor semântico principal."
        )
    )


class CandidateProfile(BaseProfile):
    headline: str = Field(
        description="Resumo de uma linha do posicionamento profissional (ex: 'Engenheiro de Dados Sênior com foco em streaming')."
    )
    current_title: str = Field(description="Cargo atual ou mais recente do candidato.")
    highlights: List[str] = Field(
        description="3 a 5 conquistas objetivas e mensuráveis da carreira, cada uma em uma frase curta."
    )


class JobRequirements(BaseProfile):
    role_title: str = Field(description="Título do cargo da vaga.")
    must_have_skills: List[str] = Field(
        description="Competências obrigatórias — a ausência delas desqualifica o candidato."
    )
    nice_to_have_skills: List[str] = Field(
        description="Competências desejáveis, que somam pontos mas não são eliminatórias."
    )
    responsibilities: List[str] = Field(description="Principais responsabilidades do cargo.")


# ── API payloads ────────────────────────────────────────────────────────────
class CandidateCreateMeta(BaseModel):
    display_name: Optional[str] = None
    headline: Optional[str] = None
    location: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    job_id: Optional[int] = Field(None, description="Se informado, cria a candidatura já na vaga.")


class JobCreateMeta(BaseModel):
    title: Optional[str] = None
    department: Optional[str] = None
    location: Optional[str] = None
    work_model: Optional[str] = None
    employment_type: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    headcount: Optional[int] = 1
    owner: Optional[str] = None


class StageUpdate(BaseModel):
    stage: str
    note: Optional[str] = None
    actor: str = "Recrutador"


class NoteCreate(BaseModel):
    content: str
    actor: str = "Recrutador"


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = Field(default_factory=list)
    job_id: Optional[int] = None


class RankRequest(BaseModel):
    job_id: int
    top_n: int = 10
    rerank: bool = True
    weights: Optional[List[float]] = None
    min_experience_years: Optional[float] = None
    seniorities: Optional[List[str]] = None
    required_certifications: Optional[List[str]] = None
    explain_top: int = Field(0, description="Gera explicação por IA para os N primeiros colocados.")
