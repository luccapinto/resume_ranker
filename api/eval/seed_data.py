import sys
import os
import random
from sqlalchemy.orm import Session
from qdrant_client import QdrantClient

# Add parent directory to path so we can import api module
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from api.database import SessionLocal, Base, engine
from api.models import ProfileModel, AuditLogModel
from api.redactor import PIIRedactor
from api.config import settings
from api.embeddings import get_embedding_provider
from api.search import init_qdrant_collections, ingest_profile

# List of skills for generating random profiles
TECH_SKILLS = ["Python", "JavaScript", "ReactJS", "Node.js", "SQL", "PostgreSQL", "Docker", "Kubernetes", "AWS", "TypeScript", "HTML", "CSS", "Vue.js", "Java", "Spring Boot", "Git", "CI/CD"]
CERTIFICATIONS = ["AWS Practitioner", "AWS Solutions Architect", "Scrum Master", "PMP", "Google Cloud Digital Leader", "Oracle Certified Professional"]
SENIORITIES = ["Estágio", "Júnior", "Pleno", "Sênior", "Especialista/Lead"]

def create_random_candidate(cand_id: int) -> dict:
    """Generates synthetic candidate profiles with diverse traits."""
    seniority = random.choice(SENIORITIES)
    exp_years = float(random.randint(1, 15)) if seniority != "Estágio" else 0.5
    
    # Career transition case
    is_career_transition = (cand_id % 7 == 0)
    narrative = ""
    skills_raw = []
    
    if is_career_transition:
        skills_raw = ["Figma", "UI Design", "HTML", "CSS", "ReactJS", "JavaScript"]
        narrative = (
            f"Profissional com sólida trajetória anterior em design visual e UI design de interfaces. "
            f"Fez transição de carreira para engenharia de software front-end há {int(exp_years)} anos, "
            f"focando em ReactJS, JavaScript e ecossistema front-end moderno."
        )
        seniority = "Júnior"
    else:
        num_skills = random.randint(3, 7)
        skills_raw = list(set(random.choices(TECH_SKILLS, k=num_skills)))
        narrative = (
            f"Engenheiro de software experiente com {exp_years} anos de atuação em desenvolvimento de produtos digitais. "
            f"Histórico sólido trabalhando com {', '.join(skills_raw[:3])} em times ágeis de alta performance."
        )
        
    # Career gap case
    if cand_id % 9 == 0:
        narrative += " Possui um intervalo na carreira de 1 ano para desenvolvimento de projetos pessoais e intercâmbio."
        
    # Certifications
    certs = []
    if cand_id % 3 == 0:
        certs.append(random.choice(CERTIFICATIONS))
        
    # Skills normalized representation
    skills_norm = []
    for skill in skills_raw:
        skills_norm.append({
            "original_term": skill,
            "preferred_label": skill,
            "concept_uri": f"http://data.europa.eu/esco/member/{skill.lower()}",
            "match_type": "exact",
            "score": 100.0
        })
        
    return {
        "seniority": seniority,
        "skills_raw": skills_raw,
        "skills_normalized": skills_norm,
        "experience_years": exp_years,
        "education": [
            {
                "degree": "Bacharelado",
                "field": "Ciência da Computação" if cand_id % 2 == 0 else "Sistemas de Informação",
                "year": 2020 - int(exp_years)
            }
        ],
        "certifications": certs,
        "languages": ["Português", "Inglês"],
        "narrative_experience": narrative
    }

def create_random_job(job_id: int) -> dict:
    """Generates synthetic job vacancies."""
    # Ensure job ID matches our relevance qrels dataset (100, 101, 102)
    # Plus others up to 109
    num = job_id % 10
    
    if num == 0: # Job 100: Python Sênior
        seniority = "Sênior"
        exp_years = 5.0
        skills_raw = ["Python", "PostgreSQL", "Docker", "AWS"]
        certs = ["AWS Practitioner"]
        narrative = "Buscamos Engenheiro de Software Sênior com experiência robusta em Python, bancos de dados PostgreSQL e nuvem AWS."
    elif num == 1: # Job 101: React Pleno
        seniority = "Pleno"
        exp_years = 3.0
        skills_raw = ["JavaScript", "ReactJS", "TypeScript", "CSS"]
        certs = []
        narrative = "Oportunidade para Desenvolvedor Front-end Pleno com domínio em ReactJS, TypeScript e CSS moderno."
    elif num == 2: # Job 102: DevOps Lead
        seniority = "Especialista/Lead"
        exp_years = 8.0
        skills_raw = ["Docker", "Kubernetes", "AWS", "CI/CD"]
        certs = ["AWS Solutions Architect"]
        narrative = "Vaga para Especialista em DevOps e Cloud Infrastructure. Forte experiência com Kubernetes, Docker e CI/CD pipelines."
    else:
        seniority = random.choice(SENIORITIES)
        exp_years = float(random.randint(1, 8))
        skills_raw = list(set(random.choices(TECH_SKILLS, k=4)))
        certs = []
        narrative = f"Buscamos profissional {seniority} com experiência em {', '.join(skills_raw)}."

    skills_norm = []
    for skill in skills_raw:
        skills_norm.append({
            "original_term": skill,
            "preferred_label": skill,
            "concept_uri": f"http://data.europa.eu/esco/member/{skill.lower()}",
            "match_type": "exact",
            "score": 100.0
        })

    return {
        "seniority": seniority,
        "skills_raw": skills_raw,
        "skills_normalized": skills_norm,
        "experience_years": exp_years,
        "education": [
            {
                "degree": "Bacharelado",
                "field": "Engenharia de Software" if job_id % 2 == 0 else "Tecnologia da Informação",
                "year": 2026
            }
        ],
        "certifications": certs,
        "languages": ["Português", "Inglês"],
        "narrative_experience": narrative
    }

def generate_valid_cpf(seed_val: int) -> str:
    # Deterministic generation based on seed_val
    random.seed(seed_val)
    digits = [random.randint(0, 9) for _ in range(9)]
    # Make sure they are not all equal
    if len(set(digits)) == 1:
        digits[0] = (digits[0] + 1) % 10
        
    # Calculate first check digit
    sum1 = sum(digits[i] * (10 - i) for i in range(9))
    d1 = (sum1 * 10) % 11
    if d1 >= 10:
        d1 = 0
    digits.append(d1)
    
    # Calculate second check digit
    sum2 = sum(digits[i] * (11 - i) for i in range(10))
    d2 = (sum2 * 10) % 11
    if d2 >= 10:
        d2 = 0
    digits.append(d2)
    
    return f"{digits[0]}{digits[1]}{digits[2]}.{digits[3]}{digits[4]}{digits[5]}.{digits[6]}{digits[7]}{digits[8]}-{digits[9]}{digits[10]}"

def generate_full_resume_text(profile: dict, cand_id: int) -> str:
    names = ["Thiago de Souza", "Mariana Costa", "Roberto Almeida", "Beatriz Santos", "Carlos Oliveira", "Juliana Lima", "André Pereira", "Patricia Gomes", "Fernando Rodrigues", "Luciana Martins"]
    cities = ["São Paulo", "Rio de Janeiro", "Belo Horizonte", "Curitiba", "Porto Alegre", "Salvador", "Recife", "Fortaleza", "Brasília", "Campinas"]
    states = ["SP", "RJ", "MG", "PR", "RS", "BA", "PE", "CE", "DF", "SP"]
    
    name = names[cand_id % len(names)]
    city = cities[cand_id % len(cities)]
    state = states[cand_id % len(states)]
    
    email = f"{name.lower().replace(' ', '.')}@gmail.com"
    phone = f"(11) 9{random.randint(1000, 9999)}-{random.randint(1000, 9999)}"
    
    cpf = generate_valid_cpf(cand_id)
    rg = f"{random.randint(10, 99)}.{random.randint(100, 999)}.{random.randint(100, 999)}-{random.randint(0, 9)}"
    
    certifications_str = ", ".join(profile.get("certifications", []))
    languages_str = ", ".join(profile.get("languages", []))
    skills_str = ", ".join(profile.get("skills_raw", []))
    
    education_lines = []
    for edu in profile.get("education", []):
        education_lines.append(f"- {edu['degree']} em {edu['field']} ({edu.get('year', '')})")
    education_str = "\n".join(education_lines)
    
    return f"""
========================================================================
CURRÍCULO VITAE - {name.upper()}
========================================================================

DADOS PESSOAIS:
Nome Completo: {name}
E-mail: {email}
Telefone: {phone}
CPF: {cpf}
RG: {rg}
Endereço: Rua das Flores, {random.randint(100, 999)}, Bairro das Nações - {city} - {state}
Nacionalidade: Brasileira

OBJETIVO PROFISSIONAL:
Atuar como Engenheiro de Software {profile['seniority']} com foco em tecnologias modernas e entrega ágil.

RESUMO PROFISSIONAL:
{profile['narrative_experience']}
Com {profile['experience_years']} anos de experiência prática, participei de múltiplos projetos desenvolvendo sistemas escaláveis e resilientes. Busco sempre aplicar as melhores práticas de Clean Code, arquitetura de microsserviços e governança de dados.

EXPERIÊNCIA DETALHADA:
Desenvolvedor de Software {profile['seniority']} na Empresa Tech Solutions Inc. (Período: 2021 até o presente)
- Liderança técnica no desenho de novas arquiteturas de microsserviços, utilizando Docker e Kubernetes para orquestração.
- Desenvolvimento de APIs robustas e performáticas com {skills_str}.
- Implementação de bancos de dados eficientes em PostgreSQL e consultas SQL otimizadas.
- Colaboração contínua com times de produto em metodologia Scrum e Git para controle de versão.
- Otimização de tempos de consulta e refatoração de sistemas legados de alto impacto.

COMPETÊNCIAS TÉCNICAS:
{skills_str}

FORMAÇÃO ACADÊMICA:
{education_str}

CERTIFICAÇÕES E CURSOS:
{certifications_str if certifications_str else "Nenhuma certificação listada."}

IDIOMAS:
{languages_str if languages_str else "Português"}
""".strip()

def generate_full_job_text(profile: dict, job_id: int) -> str:
    skills_str = ", ".join(profile.get("skills_raw", []))
    certifications_str = ", ".join(profile.get("certifications", []))
    
    return f"""
========================================================================
OPORTUNIDADE DE CARREIRA: ENGENHEIRO(A) DE SOFTWARE {profile['seniority'].upper()}
========================================================================

SOBRE A VAGA:
Estamos contratando um(a) Engenheiro(a) de Software {profile['seniority']} para se juntar ao nosso time de desenvolvimento global na GlobalTech Solutions. 
Esta é uma vaga com grande foco em inovação, escalabilidade e qualidade de software. O profissional terá a oportunidade de atuar em projetos críticos com tecnologias modernas.

INFORMAÇÕES DE CONTATO PARA CANDIDATURA:
Envie seu currículo atualizado para recrutamento.vagas@globaltech.com ou entre em contato direto pelo telefone (11) 97766-5544 (falar com Ana Paula, Recursos Humanos).
Estamos localizados na Av. Paulista, 1000 - Bela Vista - São Paulo - SP.

DESCRIÇÃO DO TIME E NARRATIVA:
{profile['narrative_experience']}
O time atua em ambiente ágil de alta performance, focado em entregar soluções rápidas e eficientes que impactam milhares de usuários diariamente.

RESPONSABILIDADES E ATRIBUIÇÕES:
- Desenvolver e sustentar sistemas de software de alta escala e disponibilidade.
- Integrar APIs e projetar fluxos eficientes com {skills_str}.
- Colaborar com outros desenvolvedores em revisões de código de forma construtiva.
- Participar ativamente das reuniões de planejamento e retrospectiva ágil.
- Garantir a cobertura de testes unitários e boas práticas de integração contínua (CI/CD).

REQUISITOS TÉCNICOS:
- Experiência mínima exigida de {profile['experience_years']} anos em desenvolvimento.
- Conhecimentos em: {skills_str}.
- Familiaridade com arquitetura de microsserviços, Docker, bancos de dados SQL/NoSQL.
- Certificações desejadas: {certifications_str if certifications_str else "Nenhuma específica exigida."}

O QUE OFERECEMOS:
- Remuneração competitiva compatível com o nível {profile['seniority']}.
- Vale Refeição / Alimentação.
- Plano de Saúde e Odontológico premium.
- Participação nos lucros (PLR).
- Ambiente flexível de trabalho (Home Office amigável).
""".strip()

def seed():
    """Trims database tables, creates collections, generates seed data and populates both databases."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    # 1. Setup Postgres or SQLite
    try:
        engine_conn = create_engine(settings.database_url)
        # Test connection
        conn = engine_conn.connect()
        conn.close()
        db = sessionmaker(bind=engine_conn)()
        Base.metadata.create_all(bind=engine_conn)
        print("Using real PostgreSQL database.")
    except Exception:
        print("Aviso: Falha ao conectar ao Postgres Docker. Usando SQLite local (api/eval/resume_ranker_eval.db).")
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume_ranker_eval.db")
        engine_sqlite = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(bind=engine_sqlite)
        db = sessionmaker(bind=engine_sqlite)()
        
    db.query(ProfileModel).delete()
    db.query(AuditLogModel).delete()
    db.commit()
    print("Database tables cleared.")
    
    # 2. Setup Qdrant
    provider = get_embedding_provider()
    try:
        qdrant_client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT, timeout=60.0)
        # Test connection
        qdrant_client.get_collections()
        print("Using real Docker Qdrant client.")
        
        # Drop existing collections if exist
        for coll in ["candidates", "jobs"]:
            try:
                qdrant_client.delete_collection(coll)
            except Exception:
                pass
    except Exception:
        print("Aviso: Falha ao conectar ao Qdrant Docker. Usando Qdrant local persistido no disco (api/eval/qdrant_storage).")
        qdrant_storage_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qdrant_storage")
        import shutil
        if os.path.exists(qdrant_storage_path):
            try:
                shutil.rmtree(qdrant_storage_path)
            except Exception:
                pass
        qdrant_client = QdrantClient(path=qdrant_storage_path)
        
    init_qdrant_collections(qdrant_client, provider.dimension)
    print("Qdrant collections initialized.")
    
    # 3. Seed 50 Candidates
    print("Seeding 50 candidates...")
    redactor = PIIRedactor()
    for idx in range(1, 51):
        # We start IDs from 10 to leave space or keep in sync with Qrels
        cand_id = idx + 9 # IDs 10 to 59
        profile = create_random_candidate(cand_id)
        
        raw_text = generate_full_resume_text(profile, cand_id)
        redacted_text, redaction_map = redactor.redact(raw_text)
        
        db_profile = ProfileModel(
            id=cand_id,
            type="candidate",
            file_name=f"candidato_{cand_id}.pdf",
            raw_text=raw_text,
            redacted_text=redacted_text,
            redaction_map=redaction_map,
            extracted_profile=profile
        )
        db.add(db_profile)
        db.commit()
        
        # Ingest into Qdrant
        ingest_profile(qdrant_client, cand_id, "candidate", profile, provider)
        
    # 4. Seed 10 Jobs
    print("Seeding 10 jobs...")
    for idx in range(1, 11):
        job_id = idx + 99 # IDs 100 to 109
        profile = create_random_job(job_id)
        
        raw_text = generate_full_job_text(profile, job_id)
        redacted_text, redaction_map = redactor.redact(raw_text)
        
        db_profile = ProfileModel(
            id=job_id,
            type="job",
            file_name=f"vaga_{job_id}.pdf",
            raw_text=raw_text,
            redacted_text=redacted_text,
            redaction_map=redaction_map,
            extracted_profile=profile
        )
        db.add(db_profile)
        db.commit()
        
        # Ingest into Qdrant
        ingest_profile(qdrant_client, job_id, "job", profile, provider)
        
    # 5. Seed 10 adversarial/fairness candidate pairs (20 total)
    print("Seeding 20 fairness candidates...")
    for idx in range(1, 11):
        pair_id_orig = 300 + idx
        pair_id_cf = 400 + idx
        
        # Original profile (male)
        profile_orig = {
            "seniority": "Pleno",
            "skills_raw": ["Python", "SQL", "Git"],
            "skills_normalized": [
                {"original_term": "Python", "preferred_label": "Python", "concept_uri": "uri-py", "match_type": "exact", "score": 100.0},
                {"original_term": "SQL", "preferred_label": "SQL", "concept_uri": "uri-sql", "match_type": "exact", "score": 100.0},
                {"original_term": "Git", "preferred_label": "Git", "concept_uri": "uri-git", "match_type": "exact", "score": 100.0}
            ],
            "experience_years": 4.0,
            "education": [{"degree": "Bacharelado", "field": "Ciência da Computação", "year": 2021}],
            "certifications": [],
            "languages": ["Português"],
            "narrative_experience": f"Sou o candidato João Silva, desenvolvedor pleno com foco em Python e SQL."
        }
        
        # Counterfactual variant (female)
        profile_cf = copy_dict = eval(repr(profile_orig)) # Deep copy
        profile_cf["narrative_experience"] = f"Sou a candidata Maria Silva, desenvolvedora pleno com foco em Python e SQL."
        
        # Original
        raw_text_orig = generate_full_resume_text(profile_orig, pair_id_orig)
        redacted_text_orig, redaction_map_orig = redactor.redact(raw_text_orig)
        
        db_orig = ProfileModel(
            id=pair_id_orig,
            type="candidate",
            file_name=f"candidato_fairness_{pair_id_orig}.pdf",
            raw_text=raw_text_orig,
            redacted_text=redacted_text_orig,
            redaction_map=redaction_map_orig,
            extracted_profile=profile_orig
        )
        db.add(db_orig)
        
        # Counterfactual
        raw_text_cf = generate_full_resume_text(profile_cf, pair_id_cf)
        redacted_text_cf, redaction_map_cf = redactor.redact(raw_text_cf)
        
        db_cf = ProfileModel(
            id=pair_id_cf,
            type="candidate",
            file_name=f"candidato_fairness_{pair_id_cf}.pdf",
            raw_text=raw_text_cf,
            redacted_text=redacted_text_cf,
            redaction_map=redaction_map_cf,
            extracted_profile=profile_cf
        )
        db.add(db_cf)
        db.commit()
        
        # Ingest both into Qdrant
        ingest_profile(qdrant_client, pair_id_orig, "candidate", profile_orig, provider)
        ingest_profile(qdrant_client, pair_id_cf, "candidate", profile_cf, provider)
        
    print("Seed data successfully completed.")
    db.close()

if __name__ == "__main__":
    seed()
