from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

class SeniorityEnum(str, Enum):
    ESTAGIO = "Estágio"
    JUNIOR = "Júnior"
    PLENO = "Pleno"
    SENIOR = "Sênior"
    ESPECIALISTA_LEAD = "Especialista/Lead"

class EducationEntry(BaseModel):
    degree: str = Field(description="Grau acadêmico obtido ou em andamento (ex: Bacharelado, Mestrado, Técnico).")
    field: str = Field(description="Área ou curso de estudo (ex: Ciência da Computação, Engenharia Civil).")
    year: Optional[int] = Field(None, description="Ano de conclusão ou previsão de conclusão (4 dígitos).")

class BaseProfile(BaseModel):
    seniority: SeniorityEnum = Field(
        description="Nível de senioridade inferido com base na experiência descrita."
    )
    skills_raw: List[str] = Field(
        description="Lista de competências técnicas (linguagens, frameworks, ferramentas) e comportamentais (soft skills) encontradas no texto bruto."
    )
    experience_years: float = Field(
        description="Anos totais de experiência profissional acumulada. Deve ser inferido a partir dos períodos de atuação nos cargos descritos."
    )
    education: List[EducationEntry] = Field(
        description="Lista de entradas educacionais/formação acadêmica."
    )
    certifications: List[str] = Field(
        description="Lista de certificações mencionadas (ex: AWS Certified Cloud Practitioner, Scrum Master)."
    )
    languages: List[str] = Field(
        description="Lista de idiomas de domínio mencionados no texto."
    )
    narrative_experience: str = Field(
        description="Um texto consolidado, corrido e detalhado descrevendo a trajetória profissional, responsabilidades, projetos marcantes e contextos das experiências anteriores. Este texto será a base para geração do vetor semântico principal."
    )

class CandidateProfile(BaseProfile):
    pass

class JobRequirements(BaseProfile):
    pass
