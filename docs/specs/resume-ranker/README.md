# Entregável: Resume Ranker (Plataforma de Matching Candidato-Vaga com IA)

> Especificações SDD (Spec Driven Development). Leia este README antes de iniciar qualquer card.

## Proposta de Valor
A triagem de candidatos e vagas no mercado atual falha ao escolher entre duas abordagens extremas: a busca lexical pura (que ignora sinônimos e contexto semântico) ou a busca semântica pura (que pode falhar em requisitos rígidos e certificações obrigatórias). O **Resume Ranker** resolve essa dor combinando recuperação híbrida (vetores densos e esparso com filtros determinísticos) e garantindo governança (remoção de PII antes de envio para APIs externas) e explicabilidade de ponta a ponta.

## Estado Atual & Stack (Contexto)
Este é um projeto novo. A estrutura inicial será criada no formato monorepo sob a raiz:
- `/api/` contendo a aplicação backend em FastAPI, processadores e pipelines de dados.
- `/web/` contendo a aplicação frontend em Next.js com Tailwind e shadcn/ui.
- Banco de dados relacional: PostgreSQL.
- Banco de dados vetorial: Qdrant.

## Convenções de Desenvolvimento (IA)
- **Status**: Atualize o status no README e no card para `[/] Em Progresso` ao começar e para `[x] Concluído` ao finalizar.
- **Testes**: Todo card de código exige testes automatizados criados, executados e passando localmente antes da finalização.
- **Branch**: `feature/slug-curto` ou `fix/slug-curto`.

## Índice de Milestones

| Milestone | Card | Tag | Status | Arquivo |
|---|---|---|---|---|
| 1. Infraestrutura e Anonimização | 1.1 Setup da Infraestrutura Docker e Esqueleto Monorepo | 🤖 | [x] | [1.1-setup-monorepo.md](milestone-1-infra-pii/1.1-setup-monorepo.md) |
| 1. Infraestrutura e Anonimização | 1.2 Implementação do `PIIRedactor` e Reconhecedores BR | 🤖 | [x] | [1.2-pii-redactor.md](milestone-1-infra-pii/1.2-pii-redactor.md) |
| 2. Extração e Normalização | 2.1 Parser de PDF e Extração Estruturada via LLM | 🧑 | [/] | [2.1-pdf-parser-llm.md](milestone-2-parser-esco/2.1-pdf-parser-llm.md) |
| 2. Extração e Normalização | 2.2 Implementação do `SkillNormalizer` com Taxonomia ESCO | 🤖 | [/] | [2.2-skill-normalizer-esco.md](milestone-2-parser-esco/2.2-skill-normalizer-esco.md) |
| 3. Vetores e Busca Híbrida | 3.1 Abstração de `EmbeddingProvider` e Ingestão Qdrant | 🤖 | [ ] | [3.1-embedding-provider-qdrant.md](milestone-3-embeddings-busca/3.1-embedding-provider-qdrant.md) |
| 3. Vetores e Busca Híbrida | 3.2 Busca Híbrida Bidirecional e Reranking com Cross-Encoder | 🤖 | [ ] | [3.2-hybrid-search-reranker.md](milestone-3-embeddings-busca/3.2-hybrid-search-reranker.md) |
| 4. Explicabilidade e Fairness | 4.1 Explicabilidade LLM e Auditoria de Viés Contraditório | 🧑 | [ ] | [4.1-explainability-bias-audit.md](milestone-4-fairness-evaluation/4.1-explainability-bias-audit.md) |
| 4. Explicabilidade e Fairness | 4.2 Harness de Avaliação de Retrieval e Seed Data | 🤖 | [ ] | [4.2-evaluation-harness-seed.md](milestone-4-fairness-evaluation/4.2-evaluation-harness-seed.md) |
| 5. Frontend e UI | 5.1 Interface Web Premium Next.js | 🧑 | [ ] | [5.1-frontend-nextjs.md](milestone-5-frontend/5.1-frontend-nextjs.md) |
