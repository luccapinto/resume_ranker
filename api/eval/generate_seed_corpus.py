"""One-off generator for the demo corpus.

Produces realistic Brazilian résumés and job descriptions with an LLM and writes
them to `api/data/seed/`. The generated files are committed, so seeding the ATS
is deterministic and reproducible without spending tokens again.

    python -m api.eval.generate_seed_corpus            # only missing files
    python -m api.eval.generate_seed_corpus --force    # regenerate everything
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Tuple

from api.llm import get_llm

# Progress must reach a redirected log immediately; block buffering makes these
# scripts look frozen for the twenty minutes they take to run.
sys.stdout.reconfigure(line_buffering=True)

SEED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "seed")

JOBS: List[Dict] = [
    {
        "slug": "engenheiro-dados-senior",
        "title": "Engenheiro(a) de Dados Sênior",
        "department": "Dados & Analytics",
        "location": "São Paulo, SP",
        "work_model": "Híbrido",
        "employment_type": "CLT",
        "seniority": "Sênior",
        "salary_min": 14000,
        "salary_max": 19000,
        "headcount": 2,
        "owner": "Camila Ferreira",
        "brief": (
            "Plataforma de dados de um marketplace. Stack: Python, Apache Kafka, Apache Airflow, "
            "Apache Spark, dbt, Snowflake e AWS. Precisa de alguém que já operou pipelines de "
            "streaming em produção, domina modelagem dimensional e tem senso de data quality. "
            "Desejável: Terraform, observabilidade de pipelines, mentoria de juniores."
        ),
    },
    {
        "slug": "fullstack-pleno",
        "title": "Desenvolvedor(a) Full Stack Pleno",
        "department": "Engenharia de Produto",
        "location": "Remoto (Brasil)",
        "work_model": "Remoto",
        "employment_type": "CLT",
        "seniority": "Pleno",
        "salary_min": 9000,
        "salary_max": 13000,
        "headcount": 3,
        "owner": "Rodrigo Alencar",
        "brief": (
            "Produto SaaS B2B. Stack: TypeScript, React, Next.js, Node.js, NestJS, PostgreSQL, "
            "Docker e AWS. Espera-se autonomia para entregar features de ponta a ponta, escrever "
            "testes automatizados e participar de code review. Desejável: GraphQL, Tailwind CSS, "
            "design system."
        ),
    },
    {
        "slug": "ml-engineer-senior",
        "title": "Engenheiro(a) de Machine Learning Sênior",
        "department": "Inteligência Artificial",
        "location": "São Paulo, SP",
        "work_model": "Híbrido",
        "employment_type": "CLT",
        "seniority": "Sênior",
        "salary_min": 16000,
        "salary_max": 24000,
        "headcount": 1,
        "owner": "Camila Ferreira",
        "brief": (
            "Time de IA aplicada. Stack: Python, PyTorch, Hugging Face, LLMs, RAG, bancos vetoriais "
            "(Qdrant/pgvector), MLflow e Kubernetes. Foco em colocar modelos em produção com "
            "avaliação quantitativa, guardrails e monitoramento. Desejável: engenharia de prompt, "
            "fine-tuning, experiência com avaliação de RAG."
        ),
    },
    {
        "slug": "analista-dados-junior",
        "title": "Analista de Dados Júnior",
        "department": "Business Intelligence",
        "location": "Belo Horizonte, MG",
        "work_model": "Presencial",
        "employment_type": "CLT",
        "seniority": "Júnior",
        "salary_min": 4500,
        "salary_max": 6500,
        "headcount": 2,
        "owner": "Marina Duarte",
        "brief": (
            "Área de BI. Stack: SQL, Power BI, Excel avançado e Python (pandas). Vai construir "
            "dashboards, apurar métricas de negócio e apoiar áreas comerciais. Desejável: dbt, "
            "BigQuery, noções de estatística."
        ),
    },
    {
        "slug": "sre-platform-pleno",
        "title": "Site Reliability Engineer Pleno",
        "department": "Plataforma",
        "location": "Remoto (Brasil)",
        "work_model": "Remoto",
        "employment_type": "PJ",
        "seniority": "Pleno",
        "salary_min": 12000,
        "salary_max": 16000,
        "headcount": 1,
        "owner": "Rodrigo Alencar",
        "brief": (
            "Time de plataforma. Stack: Kubernetes, Terraform, AWS, GitOps (ArgoCD), Prometheus, "
            "Grafana e OpenTelemetry. Responsável por SLOs, error budget, automação de CI/CD e "
            "resposta a incidentes. Desejável: Go, service mesh, FinOps."
        ),
    },
    {
        "slug": "product-manager-pleno",
        "title": "Product Manager Pleno",
        "department": "Produto",
        "location": "São Paulo, SP",
        "work_model": "Híbrido",
        "employment_type": "CLT",
        "seniority": "Pleno",
        "salary_min": 11000,
        "salary_max": 15000,
        "headcount": 1,
        "owner": "Marina Duarte",
        "brief": (
            "Produto de pagamentos. Espera-se domínio de discovery, priorização (RICE), OKR, "
            "métricas de produto (Amplitude/Mixpanel), testes A/B e trabalho próximo a engenharia "
            "e design. Desejável: SQL para análise própria, experiência em fintech."
        ),
    },
]

# (archetype, target job slug, intended fit) — the mix is deliberate so the
# ranking has something to actually discriminate between.
CANDIDATES: List[Dict] = [
    {"slug": "ana-kafka", "archetype": "Engenheira de dados sênior, 8 anos, especialista em Kafka, Spark, Airflow, dbt, Snowflake e AWS; liderou migração de batch para streaming", "job": "engenheiro-dados-senior", "fit": "forte"},
    {"slug": "bruno-airflow", "archetype": "Engenheiro de dados pleno, 5 anos, Airflow, Python, SQL, dbt e BigQuery; sem experiência com streaming", "job": "engenheiro-dados-senior", "fit": "moderado"},
    {"slug": "carla-analytics-eng", "archetype": "Analytics engineer sênior, 7 anos, dbt, Snowflake, SQL avançado, modelagem dimensional; pouca experiência com Spark", "job": "engenheiro-dados-senior", "fit": "moderado"},
    {"slug": "diego-dba", "archetype": "DBA Oracle e SQL Server sênior, 12 anos, tuning e alta disponibilidade; migrando de carreira para dados", "job": "engenheiro-dados-senior", "fit": "baixo"},
    {"slug": "eduarda-streaming", "archetype": "Engenheira de dados sênior, 9 anos, Kafka Streams, Flink, Spark Structured Streaming, Kubernetes, Terraform", "job": "engenheiro-dados-senior", "fit": "forte"},

    {"slug": "felipe-fullstack", "archetype": "Desenvolvedor full stack pleno, 5 anos, TypeScript, React, Next.js, Node.js, NestJS, PostgreSQL, Docker e AWS", "job": "fullstack-pleno", "fit": "forte"},
    {"slug": "gabriela-frontend", "archetype": "Desenvolvedora frontend pleno, 4 anos, React, Next.js, Tailwind, design system e acessibilidade; backend limitado", "job": "fullstack-pleno", "fit": "moderado"},
    {"slug": "henrique-backend-java", "archetype": "Desenvolvedor backend pleno, 6 anos, Java, Spring Boot, PostgreSQL, Kafka; sem experiência com React", "job": "fullstack-pleno", "fit": "moderado"},
    {"slug": "isabela-fullstack-junior", "archetype": "Desenvolvedora full stack júnior, 2 anos, JavaScript, React, Node.js, MongoDB; bootcamp e projetos pessoais", "job": "fullstack-pleno", "fit": "baixo"},
    {"slug": "joao-fullstack-senior", "archetype": "Desenvolvedor full stack sênior, 9 anos, TypeScript, React, Node.js, GraphQL, PostgreSQL, AWS, liderança técnica", "job": "fullstack-pleno", "fit": "forte"},

    {"slug": "karina-llm", "archetype": "Engenheira de ML sênior, 7 anos, PyTorch, Hugging Face, LLMs, RAG, Qdrant, MLflow e Kubernetes; publicou avaliações de RAG", "job": "ml-engineer-senior", "fit": "forte"},
    {"slug": "leonardo-cv", "archetype": "Engenheiro de ML sênior, 8 anos, visão computacional, PyTorch, OpenCV, deploy em edge; pouca exposição a LLMs", "job": "ml-engineer-senior", "fit": "moderado"},
    {"slug": "mariana-mlops", "archetype": "Engenheira de MLOps pleno, 5 anos, MLflow, Kubernetes, Airflow, monitoramento de modelos, AWS SageMaker", "job": "ml-engineer-senior", "fit": "moderado"},
    {"slug": "nicolas-cientista", "archetype": "Cientista de dados pleno, 5 anos, scikit-learn, estatística, pandas, experimentação A/B; nunca colocou modelo em produção", "job": "ml-engineer-senior", "fit": "baixo"},

    {"slug": "olivia-bi-junior", "archetype": "Analista de dados júnior, 1,5 ano, SQL, Power BI, Excel avançado e pandas; estágio em BI concluído", "job": "analista-dados-junior", "fit": "forte"},
    {"slug": "paulo-estagio-bi", "archetype": "Recém-formado em Estatística, estágio de 1 ano com SQL, Power BI e Python", "job": "analista-dados-junior", "fit": "forte"},
    {"slug": "renata-comercial", "archetype": "Analista comercial pleno, 4 anos, Excel avançado, CRM Salesforce e relatórios; SQL básico", "job": "analista-dados-junior", "fit": "moderado"},
    {"slug": "sergio-financeiro", "archetype": "Analista financeiro pleno, 6 anos, controladoria, Excel, Power BI e SAP; sem programação", "job": "analista-dados-junior", "fit": "baixo"},

    {"slug": "tatiana-sre", "archetype": "SRE pleno, 6 anos, Kubernetes, Terraform, AWS, ArgoCD, Prometheus, Grafana, OpenTelemetry, SLO e on-call", "job": "sre-platform-pleno", "fit": "forte"},
    {"slug": "ulisses-devops", "archetype": "Engenheiro DevOps pleno, 5 anos, Docker, Jenkins, Ansible, AWS EC2; começando com Kubernetes", "job": "sre-platform-pleno", "fit": "moderado"},
    {"slug": "vanessa-platform", "archetype": "Platform engineer sênior, 8 anos, Kubernetes, Go, Terraform, service mesh Istio, GitOps e FinOps", "job": "sre-platform-pleno", "fit": "forte"},
    {"slug": "wagner-infra", "archetype": "Analista de infraestrutura sênior, 11 anos, VMware, Windows Server, redes e Active Directory; pouca nuvem", "job": "sre-platform-pleno", "fit": "baixo"},

    {"slug": "xavier-pm-fintech", "archetype": "Product manager pleno, 5 anos em fintech de pagamentos, discovery, RICE, OKR, Amplitude, testes A/B e SQL", "job": "product-manager-pleno", "fit": "forte"},
    {"slug": "yara-po", "archetype": "Product owner pleno, 4 anos, Scrum, refinamento de backlog, Jira; pouca prática de discovery e métricas", "job": "product-manager-pleno", "fit": "moderado"},
    {"slug": "zeca-ux", "archetype": "Product designer sênior, 7 anos, Figma, design system, pesquisa com usuários; transição para produto", "job": "product-manager-pleno", "fit": "moderado"},
    {"slug": "amanda-marketing", "archetype": "Coordenadora de marketing digital, 6 anos, growth, mídia paga, Google Ads e CRM", "job": "product-manager-pleno", "fit": "baixo"},

    # Deliberate outliers: the ranking should push these to the bottom everywhere.
    {"slug": "beatriz-juridico", "archetype": "Advogada trabalhista sênior, 10 anos, contencioso, contratos e compliance", "job": None, "fit": "baixo"},
    {"slug": "caio-logistica", "archetype": "Coordenador de logística pleno, 7 anos, supply chain, lean, roteirização e gestão de frota", "job": None, "fit": "baixo"},
]

RESUME_PROMPT = """Escreva um currículo brasileiro realista, em português do Brasil, em texto puro \
(sem markdown, sem asteriscos, sem cabeçalhos com #).

Perfil a retratar: {archetype}

Regras obrigatórias:
1. Comece com o nome completo da pessoa na primeira linha, sozinho.
2. Na segunda linha, inclua dados de contato fictícios porém plausíveis: e-mail, telefone celular \
brasileiro com DDD e cidade/estado. Inclua também um CPF fictício no formato 000.000.000-00.
3. Depois, as seções: RESUMO PROFISSIONAL, EXPERIÊNCIA PROFISSIONAL, FORMAÇÃO ACADÊMICA, \
CERTIFICAÇÕES, COMPETÊNCIAS TÉCNICAS e IDIOMAS.
4. Em EXPERIÊNCIA PROFISSIONAL, liste de 2 a 4 cargos com empresa fictícia, período no formato \
"Mês/Ano - Mês/Ano" e de 3 a 5 bullets cada, com resultados quantificados (percentuais, volumes, \
latências, economia).
5. O total deve ter entre 2500 e 3500 caracteres.
6. Use nomes de empresas e instituições brasileiras fictícias, mas plausíveis.
7. Não invente tecnologias que não existem. Seja específico com as ferramentas reais do perfil.
8. Não escreva nenhum comentário seu — devolva apenas o texto do currículo.
"""

JOB_PROMPT = """Escreva uma descrição de vaga brasileira realista, em português do Brasil, em texto \
puro (sem markdown).

Cargo: {title}
Senioridade: {seniority}
Local: {location} — {work_model}
Contrato: {employment_type}
Contexto e stack: {brief}

Regras obrigatórias:
1. Comece com o título da vaga na primeira linha.
2. Inclua as seções: SOBRE A VAGA, RESPONSABILIDADES, REQUISITOS OBRIGATÓRIOS, \
DIFERENCIAIS e BENEFÍCIOS.
3. Em REQUISITOS OBRIGATÓRIOS liste de 5 a 8 itens objetivos, incluindo anos de experiência \
esperados e as tecnologias centrais.
4. Em DIFERENCIAIS liste de 3 a 5 itens.
5. O total deve ter entre 1800 e 2600 caracteres.
6. Não escreva nenhum comentário seu — devolva apenas o texto da vaga.
"""


MIN_CHARS = 600


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")


def _complete_nonempty(llm, prompt: str, span_name: str, temperature: float, max_tokens: int) -> str:
    """Reasoning models occasionally return an empty `content` — retry until real text arrives."""
    for attempt in range(4):
        response = llm.complete(
            [{"role": "user", "content": prompt}],
            span_name=span_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = (response.content or "").strip()
        if len(text) >= MIN_CHARS:
            return text
        print(f"   resposta curta ({len(text)} chars) na tentativa {attempt + 1}; repetindo…")
    raise RuntimeError(f"O modelo não devolveu conteúdo utilizável para {span_name}.")


def _is_complete(path: str) -> bool:
    return os.path.exists(path) and os.path.getsize(path) >= MIN_CHARS


def generate(force: bool = False, workers: int = 6) -> None:
    llm = get_llm()
    if not llm.is_configured:
        print("OPENROUTER_API_KEY não configurada — nada a gerar.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.join(SEED_DIR, "jobs"), exist_ok=True)
    os.makedirs(os.path.join(SEED_DIR, "candidates"), exist_ok=True)

    tasks: List[Tuple[str, str, Callable[[], str]]] = []

    for job in JOBS:
        path = os.path.join(SEED_DIR, "jobs", f"{job['slug']}.txt")
        if _is_complete(path) and not force:
            continue
        prompt = JOB_PROMPT.format(**job)
        tasks.append(
            (f"vaga {job['slug']}", path, lambda p=prompt: _complete_nonempty(llm, p, "seed.job", 0.8, 2400))
        )

    for candidate in CANDIDATES:
        path = os.path.join(SEED_DIR, "candidates", f"{candidate['slug']}.txt")
        if _is_complete(path) and not force:
            continue
        prompt = RESUME_PROMPT.format(archetype=candidate["archetype"])
        tasks.append(
            (
                f"currículo {candidate['slug']}",
                path,
                lambda p=prompt: _complete_nonempty(llm, p, "seed.resume", 0.9, 3000),
            )
        )

    if not tasks:
        print("Corpus já está completo.")
    else:
        print(f"Gerando {len(tasks)} documentos com {workers} chamadas em paralelo…")
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fn): (label, path) for label, path, fn in tasks}
            for future in as_completed(futures):
                label, path = futures[future]
                done += 1
                try:
                    _write(path, future.result())
                    print(f"  [{done}/{len(tasks)}] ✓ {label}")
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{done}/{len(tasks)}] ✗ {label}: {exc}", file=sys.stderr)

    manifest = {
        "jobs": [{k: v for k, v in j.items() if k != "brief"} for j in JOBS],
        "candidates": CANDIDATES,
    }
    with open(os.path.join(SEED_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\nCorpus escrito em {SEED_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Regenera arquivos já existentes")
    parser.add_argument("--workers", type=int, default=6, help="Chamadas simultâneas ao modelo")
    args = parser.parse_args()
    generate(force=args.force, workers=args.workers)
