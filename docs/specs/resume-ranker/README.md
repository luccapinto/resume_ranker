# Entregável: Resume Ranker (Plataforma de Matching Candidato-Vaga com IA)

> Especificações SDD (Spec Driven Development). Leia este README antes de iniciar qualquer card.

## Proposta de Valor
A triagem de candidatos e vagas no mercado atual falha ao escolher entre duas abordagens extremas: a busca lexical pura (que ignora sinônimos e contexto semântico) ou a busca semântica pura (que pode falhar em requisitos rígidos e certificações obrigatórias). O **Resume Ranker** resolve essa dor combinando recuperação híbrida (vetores densos e esparso com filtros determinísticos) e garantindo governança (remoção de PII antes de envio para APIs externas) e explicabilidade de ponta a ponta.

## Estado Atual & Stack (Contexto)
Monorepo sob a raiz:
- `/api/` — backend FastAPI: pipelines de ingestão, motor de busca híbrida, explicabilidade, equidade, copiloto e camada de observabilidade.
- `/web/` — frontend Next.js (App Router) com Tailwind CSS v4 e componentes próprios.
- Banco relacional: PostgreSQL. Banco vetorial: Qdrant.

Os milestones 1 a 5 entregaram o motor de busca e uma interface de inspeção. Os milestones 6 e 7 transformaram o motor em um produto — um ATS conversacional com o funil de contratação completo e rastreabilidade de ponta a ponta de tudo que a IA faz.

## Convenções de Desenvolvimento (IA)
- **Status**: Atualize o status no README e no card para `[/] Em Progresso` ao começar e para `[x] Concluído` ao finalizar.
- **Testes**: Todo card de código exige testes automatizados criados, executados e passando localmente antes da finalização.
- **Branch**: `feature/slug-curto` ou `fix/slug-curto`.

## Índice de Milestones

| Milestone | Card | Tag | Status | Arquivo |
|---|---|---|---|---|
| 1. Infraestrutura e Anonimização | 1.1 Setup da Infraestrutura Docker e Esqueleto Monorepo | 🤖 | [x] | [1.1-setup-monorepo.md](milestone-1-infra-pii/1.1-setup-monorepo.md) |
| 1. Infraestrutura e Anonimização | 1.2 Implementação do `PIIRedactor` e Reconhecedores BR | 🤖 | [x] | [1.2-pii-redactor.md](milestone-1-infra-pii/1.2-pii-redactor.md) |
| 2. Extração e Normalização | 2.1 Parser de PDF e Extração Estruturada via LLM | 🧑 | [x] | [2.1-pdf-parser-llm.md](milestone-2-parser-esco/2.1-pdf-parser-llm.md) |
| 2. Extração e Normalização | 2.2 Implementação do `SkillNormalizer` com Taxonomia ESCO | 🤖 | [x] | [2.2-skill-normalizer-esco.md](milestone-2-parser-esco/2.2-skill-normalizer-esco.md) |
| 3. Vetores e Busca Híbrida | 3.1 Abstração de `EmbeddingProvider` e Ingestão Qdrant | 🤖 | [x] | [3.1-embedding-provider-qdrant.md](milestone-3-embeddings-busca/3.1-embedding-provider-qdrant.md) |
| 3. Vetores e Busca Híbrida | 3.2 Busca Híbrida Bidirecional e Reranking com Cross-Encoder | 🤖 | [x] | [3.2-hybrid-search-reranker.md](milestone-3-embeddings-busca/3.2-hybrid-search-reranker.md) |
| 4. Explicabilidade e Fairness | 4.1 Explicabilidade LLM e Auditoria de Viés Contraditório | 🧑 | [x] | [4.1-explainability-bias-audit.md](milestone-4-fairness-evaluation/4.1-explainability-bias-audit.md) |
| 4. Explicabilidade e Fairness | 4.2 Harness de Avaliação de Retrieval e Seed Data | 🤖 | [x] | [4.2-evaluation-harness-seed.md](milestone-4-fairness-evaluation/4.2-evaluation-harness-seed.md) |
| 5. Frontend e UI | 5.1 Interface Web Premium Next.js | 🧑 | [x] | [5.1-frontend-nextjs.md](milestone-5-frontend/5.1-frontend-nextjs.md) |
| 6. ATS e Copiloto | 6.1 Domínio de ATS: vagas, candidatos, candidaturas e funil | 🤖 | [x] | [6.1-ats-domain.md](milestone-6-ats-copilot/6.1-ats-domain.md) |
| 6. ATS e Copiloto | 6.2 Copiloto conversacional com ferramentas sobre o ATS | 🧑 | [x] | [6.2-copilot-conversacional.md](milestone-6-ats-copilot/6.2-copilot-conversacional.md) |
| 7. Observabilidade | 7.1 Observabilidade de IA fim a fim | 🤖 | [x] | [7.1-tracing-ia.md](milestone-7-observabilidade/7.1-tracing-ia.md) |
