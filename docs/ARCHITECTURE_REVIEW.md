# Revisão Arquitetural Profunda — Resume Ranker

> **Autor**: Revisão automatizada de arquitetura (exploração livre, escopo aberto)
> **Data**: 2026-07-02
> **Escopo**: Todo o repositório — `api/` (FastAPI), `web/` (Next.js), `docs/`, infraestrutura e processos de engenharia.

---

## Sumário Executivo

O Resume Ranker é um projeto de portfólio conceitualmente forte: a combinação de busca híbrida multi-vetor + RRF + cross-encoder, governança de PII e auditoria contrafactual de viés é uma proposta acima da média. A modularização do backend (`redactor`, `extractor`, `normalizer`, `search`, `fairness`, `explain`) é limpa em nível de arquivos, e a existência de um harness de avaliação com NDCG/MRR demonstra maturidade rara em projetos desse porte.

Porém, entre a **promessa do README e a implementação real existe uma lacuna significativa**, e é exatamente nela que este documento se concentra. Os problemas se agrupam em cinco famílias:

| # | Família | Gravidade | Resumo |
|---|---------|-----------|--------|
| 1 | **Integridade / honestidade técnica** | 🔴 Crítica | UI exibe rankings fabricados com `Math.random()`; README anuncia BM25 e E5 que não existem; auditoria de viés degenera em "teatro de fairness" sem API key |
| 2 | **Segurança & privacidade** | 🔴 Crítica | O paradoxo central: a API que anonimiza PII para o LLM **vaza todo o PII** (raw_text + redaction_map) em endpoints públicos sem autenticação, com CORS `*` |
| 3 | **Corretude funcional** | 🟠 Alta | Bug de contrato citations (`text` vs `citation`) quebra a explicabilidade; cross-encoder inglês avaliando texto português; delta percentual sobre logits |
| 4 | **Arquitetura & performance** | 🟠 Alta | Modelo de embeddings recarregado a cada request; LLM síncrono de 60s+ no caminho da requisição; `main.py` monolítico com duplicação massiva; código de produção detectando mocks de teste |
| 5 | **Engenharia de processo** | 🟡 Média | Zero CI, zero migrations, dependências sem lock, Makefile Windows-only, binários SQLite commitados no git |

O projeto está a uma distância razoável do "estado da arte" que o README promete — mas o caminho é claro e está mapeado abaixo, com um roadmap priorizado ao final.

---

## 1. Integridade e Honestidade Técnica 🔴

Num projeto cuja tese é *explicabilidade e auditabilidade*, qualquer dado fabricado é o defeito mais grave possível. Encontrei três casos.

### 1.1. Rankings fabricados na aba "Didactic" (`web/src/app/page.tsx:306-308`)

```tsx
skillsRank: Math.floor(Math.random() * 5) + 1,
narrativeRank: Math.floor(Math.random() * 8) + 1,
lexicalRank: Math.floor(Math.random() * 10) + 1,
```

A aba didática — que existe justamente para *ensinar como o ranking multi-vetor funciona* — exibe posições de ranking **aleatórias** para os vetores de skills, narrativa e léxico. Logo abaixo (`page.tsx:317`), um `rrfScore: 0.005` é hardcoded quando o candidato não está no top-K. Um recrutador ou avaliador do portfólio que inspecione esses números estaria vendo ficção.

**Correção**: expor um endpoint `/matching/debug` no backend que retorne os rankings reais por estratégia (a informação já existe dentro de `hybrid_search_and_rerank` — `ranking_skills`, `ranking_narrative`, `ranking_lexical` são descartados após o RRF). O frontend deve consumir esse dado real ou remover a feature.

### 1.2. README anuncia modelos e algoritmos que não existem

- **"Dense E5"** (diagrama Mermaid e seção de arquitetura): o modelo real é `paraphrase-multilingual-MiniLM-L12-v2` (`config.py:15`). Detalhe relevante: modelos E5 exigem prefixos `query:`/`passage:` para funcionar corretamente — se um dia o E5 for adotado, o código atual o usaria errado.
- **"Sparse BM25 nativo no Qdrant"**: o que existe é um *bag-of-words com hash MD5 e TF logarítmico* (`embeddings.py:27-47`). Não há IDF, não há saturação de termo, não há normalização por comprimento de documento — ou seja, **não é BM25**. Sem IDF e sem remoção de stopwords, palavras funcionais do português ("com", "para", "anos") dominam o score léxico tanto quanto "Kubernetes".
- **"PostgreSQL 15"** com badge: a API não tem fallback SQLite (só o harness tem), e não há nenhuma migration — ver §5.

**Correção**: ou alinhar o README à realidade, ou (melhor) alinhar a realidade ao README: adotar `intfloat/multilingual-e5-base` com prefixos corretos e BM25 real via `fastembed`/`Qdrant sparse BM25` (suportado nativamente desde qdrant-client 1.10 com `models.Document` + `bm25`).

### 1.3. Auditoria de viés que "sempre passa" (`fairness.py:121-127`)

```python
try:
    cf_extracted = extractor.extract(cf_redacted_text, CandidateProfile).model_dump()
except Exception:
    cf_extracted = copy.deepcopy(candidate_profile.extracted_profile)
```

Sem `OPENROUTER_API_KEY` (ou em qualquer falha do LLM), o perfil contrafactual é **uma cópia idêntica do original**. Os dois perfis geram vetores idênticos, o delta de score é ~0% e a auditoria **passa garantidamente** — registrando no `AuditLogModel` um "aprovado" que não mediu nada. Isso é anti-padrão de compliance: um log de auditoria que atesta algo que não aconteceu.

**Correção**: em caso de falha na extração, o audit deve **falhar explicitamente** (status `inconclusive`), nunca degradar silenciosamente. O campo `bias_audit_results` deveria registrar o modo de execução (real vs. degraded).

---

## 2. Segurança & Privacidade 🔴

### 2.1. O paradoxo do PII: anonimiza para o LLM, vaza para o mundo

Toda a narrativa de governança do projeto é "PII nunca sai para APIs externas". Mas observe o que **qualquer requisição HTTP anônima** recebe:

- `GET /profiles/candidates` (`main.py:324-346`) retorna, para **todos** os candidatos: `raw_text` (currículo bruto com CPF, RG, telefone, nome), `redacted_text` **e** `redaction_map` — o dicionário que mapeia cada placeholder de volta ao valor original. Ou seja, a API entrega o texto anonimizado **e a chave para desanonimizá-lo**, juntos, no mesmo payload.
- O mesmo vale para `/profiles/{id}`, `/profiles/jobs`, e os resultados de `/matching/*` (que embutem o `profile` completo com `raw_text` e `redaction_map` — `main.py:518-532`).
- `GET /profiles/{id}/pdf` serve o currículo original em PDF para qualquer um.

Combinado com:

- **Zero autenticação/autorização** em qualquer endpoint.
- **CORS `allow_origins=["*"]` + `allow_credentials=True`** (`main.py:31-37`) — combinação inclusive inválida pela spec do Fetch (navegadores rejeitam credenciais com wildcard), sinal de configuração copiada sem análise.
- `redaction_map` persistido **em plaintext** no banco (`models.py:12`).

Para um sistema que processa dados de candidatos (dados pessoais sob LGPD, e o projeto é explicitamente brasileiro — CPF/RG recognizers), isso inverte a proposta de valor: a proteção existe apenas contra o OpenRouter, não contra qualquer outro ator.

**Correções (em ordem)**:
1. Separar DTOs de resposta: endpoints de listagem/matching devem retornar apenas dados anonimizados/extraídos; `raw_text` e `redaction_map` só em endpoint privilegiado.
2. Introduzir autenticação (mesmo que API key simples num projeto de portfólio — demonstra o conceito) e RBAC mínimo (recruiter vs. admin/auditor).
3. Criptografar `redaction_map` at-rest (ex.: Fernet com chave em env) ou, no mínimo, movê-lo para tabela separada com acesso restrito.
4. CORS com origem explícita (`http://localhost:3000`) e sem `allow_credentials` desnecessário.

### 2.2. Vazamento de detalhes internos em erros

O padrão `raise HTTPException(status_code=500, detail=f"...: {str(e)}")` aparece em ~10 endpoints. Exceções de infraestrutura (connection strings, paths, traces do Qdrant) são serializadas diretamente para o cliente. **Correção**: exception handler global que loga o stack trace e retorna mensagem genérica + correlation ID.

### 2.3. Superfícies menores

- `POST /profiles/*` aceita PDF de tamanho ilimitado — sem limite de upload, um PDF de centenas de MB trava o worker (parse síncrono do PyMuPDF). Adicionar limite de bytes e de páginas.
- Arquivos PDF salvos em `api/data/pdfs` relativo ao **CWD do processo** (`main.py:181`) — o path muda conforme de onde o uvicorn é iniciado; usar path absoluto ancorado em settings.
- Credenciais default (`postgrespassword`) no `docker-compose.yml` e `config.py` — aceitável para dev, mas deveria vir de `.env` com `.env.example` versionado (hoje não há `.env.example`).

---

## 3. Corretude Funcional 🟠

### 3.1. Bug de contrato: a explicabilidade está quebrada no frontend

O backend retorna citações como `{"text": ..., "verified": ...}` (`explain.py:135-138`). O frontend declara e consome `{citation: string, verified: boolean}` (`page.tsx:61-64`, `page.tsx:480`):

```tsx
.filter(c => c.citation && c.citation.trim().length > 3)  // c.citation é sempre undefined
```

Resultado: o filtro descarta **todas** as citações e o recurso de *highlight de evidências* — o guardrail de alucinação que é um dos quatro diferenciais anunciados — **nunca renderiza**. A ironia: o projeto gera tipos TypeScript a partir do OpenAPI (`web/src/types/api.ts`, 714 linhas), mas o `page.tsx` **não os importa** — todas as interfaces foram redigitadas à mão, e é exatamente esse drift manual que causou o bug. Agrava o problema o fato de que os endpoints usam `response_model=dict`/`List[dict]` (§3.4), tornando os tipos gerados vazios e inúteis.

### 3.2. Cross-encoder em inglês julgando currículos em português

`cross-encoder/ms-marco-MiniLM-L-6-v2` (`search.py:33`) foi treinado no MS MARCO, corpus **exclusivamente em inglês**. Ele é a etapa final e decisiva do ranking — o score dele sobrescreve o RRF — mas está avaliando pares query/documento em português, domínio no qual seus scores são pouco mais que ruído estruturado. Alternativas diretas: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (mMARCO multilíngue, inclui PT-BR) ou `BAAI/bge-reranker-v2-m3`.

### 3.3. Matemática do audit de viés

Três problemas compostos em `fairness.py:185-190`:

1. **Score do cross-encoder é um logit**, não uma probabilidade — pode ser negativo ou próximo de zero. `score_pct_delta = delta / orig_score * 100` sobre logits produz percentuais sem significado (divisão por valores próximos de zero explode; base negativa inverte o sinal). O threshold "delta < 1%" do README opera sobre uma escala não calibrada. Aplicar sigmoid antes, ou comparar por *rank*, não por score.
2. **O ranking inclui todos os outros candidatos da collection**: os perfis temporários (IDs `9999999`/`8888888`) competem com a base inteira no top-10. Se qualquer um dos dois cair fora do top-10, seu score vira `0.0` e o delta é lixo. A comparação deveria ser feita **pareada e isolada** (scorar os dois perfis diretamente contra a vaga, sem retrieval).
3. **Escrita na collection de produção sem try/finally**: se `hybrid_search_and_rerank` lançar exceção, os pontos temporários **vazam permanentemente** na collection `candidates` e passam a aparecer em buscas reais de usuários. No mínimo `try/finally` no delete; idealmente, usar uma collection efêmera ou scoring direto sem ingestão.

Adicional: o swap contrafactual é unidirecional (masculino→feminino) e contém a entrada no-op `"especialista": "especialista"`. Currículos já femininos não são testados na direção oposta.

### 3.4. `response_model=dict` destrói o contrato OpenAPI

Todos os endpoints declaram `response_model=dict` ou `List[dict]`. Consequências em cascata: Swagger sem schema de resposta → `openapi-typescript` gera tipos vazios → frontend redigita tipos à mão → bug §3.1. Os schemas Pydantic já existem (`schemas.py`); falta criar os DTOs de resposta (`ProfileResponse`, `MatchResult`, `ExplanationResponse`, `AuditResponse`) e usá-los. Isso também resolveria §2.1 por design (campos sensíveis fora do DTO público).

### 3.5. Redactor: falsos positivos estruturais

- `RGRecognizer` inclui `Pattern(r"\b\d{7,10}\b", score=0.5)` (`redactor.py:70`) e o `redact()` **não filtra por score** — qualquer sequência de 7 a 10 dígitos (número de matrícula, ID de projeto, orçamento "R$ 1500000") é redigida como RG.
- `CPFRecognizer` com `\b\d{11}\b` (score 0.7) colide com celulares de 11 dígitos sem máscara; o CPF tem validação de dígito verificador (bom!), mas telefone válido pode coincidir.
- **Sem tratamento de spans sobrepostos**: se dois recognizers marcam trechos que se intersectam (CPF e RG sobre os mesmos dígitos), a substituição right-to-left (`redactor.py:240`) aplica os dois placeholders sobre offsets conflitantes e **corrompe o texto**. O Presidio tem o `AnonymizerEngine` exatamente para resolver conflitos de span — o projeto instala `presidio-anonymizer` (está no requirements) mas reimplementa a substituição à mão sem a resolução de conflitos.
- A `PII_WHITELIST` com ~150 palavras hardcoded (incluindo stopwords como "com", "para", "de") é uma correção sintomática da baixa precisão do NER; cada palavra adicionada é um vazamento potencial (um candidato chamado "Cloud" ou sobrenome "Lead" nunca seria redigido).

### 3.6. Miudezas de corretude

- `has_pdf: True` hardcoded em **todas** as respostas (`main.py:212, 343, 389`), mesmo quando nenhum PDF existe — o frontend exibe botão de PDF que cai no fallback de geração dinâmica silenciosamente.
- Rollback incompleto: se a ingestão no Qdrant falha, a linha do Postgres é deletada (`main.py:199-200`) mas **o PDF salvo em disco não é removido** — arquivos órfãos acumulam.
- `Content-Disposition: inline; filename={filename}` sem sanitização/quoting do filename (nome de arquivo com `"` ou caracteres não-ASCII gera header inválido; usar `filename*=` RFC 5987).
- Extractor faz retry inclusive em erros 4xx não-retryáveis (chave inválida → 3 tentativas com sleep, `extractor.py:69-93`).
- `weights` como string CSV via query param (`"1,1,0.5"`) sem validação de tamanho — passar 2 pesos silenciosamente aplica peso 1.0 ao terceiro ranking (`search.py:150`).

---

## 4. Arquitetura & Performance 🟠

### 4.1. O bug de performance mais caro: modelo recarregado a cada request

Cada endpoint faz `provider = get_embedding_provider()` (`main.py:196, 482, 578, 677`), que retorna um **novo** `LocalEmbeddingProvider` com `_model = None`. Na primeira chamada de embedding, `SentenceTransformer(model_name)` reconstrói o modelo **do disco, a cada requisição** — segundos de latência e centenas de MB de RAM churn por request. O mesmo padrão se repete com `QdrantClient` (nova conexão TCP por request, inclusive no `/health`).

O contraste é revelador: `search.py:25-34` implementa corretamente o singleton lazy para o CrossEncoder, e `normalizer.py` faz lazy-load do modelo de fallback. A solução já está no próprio codebase — falta aplicá-la ao provider e ao client, idealmente via **lifespan do FastAPI + injeção de dependência** (`Depends(get_provider)`), o que também eliminaria os singletons globais de import-time (§4.3).

### 4.2. LLM síncrono de até 3 minutos no caminho da requisição

`POST /profiles/candidate` executa, sincronamente, dentro do request: parse de PDF → Presidio/spaCy → **chamada LLM com timeout de 60s e até 3 retries com sleep** (`extractor.py:66-93`, pior caso ~186s) → normalização → 2 embeddings densos → upsert no Qdrant. Endpoints `def` rodam no threadpool do Starlette (default ~40 threads), então poucas ingestões simultâneas esgotam o pool e derrubam a latência de **toda** a API, incluindo `/health`.

**Correção estrutural**: ingestão assíncrona — o endpoint aceita o upload, persiste com status `processing` e retorna `202 + id`; um worker (FastAPI `BackgroundTasks` para o porte atual; arq/Celery se crescer) executa o pipeline e atualiza o status. O frontend já tem polling de listas; encaixaria naturalmente.

### 4.3. `main.py` monolítico e a duplicação candidate/job

`main.py` tem 725 linhas contendo: rotas, lógica de negócio, geração de PDF, serialização manual e bootstrapping. Os pares de endpoints são clones quase perfeitos:

- `create_candidate_profile` vs `create_job_profile`: ~110 linhas duplicadas cada, diferindo em 3 strings (`"candidate"`/`"job"`, schema, prefixo do arquivo).
- `match_candidates_for_job` vs `match_jobs_for_candidate`: ~95 linhas duplicadas.
- O dict de serialização de perfil (9 campos) é copiado **6 vezes** no arquivo.
- A lógica "montar skills_text com fallback para skills_raw" aparece em `main.py` (2×), `search.py`, `fairness.py` e `run_harness.py` — **5 cópias** da mesma regra de negócio.

**Estrutura alvo** (sem overengineering, mantendo o espírito do projeto):

```
api/
├── routers/          # profiles.py, matching.py, audit.py, health.py (APIRouter)
├── services/         # ingestion.py (pipeline único parametrizado por type), matching.py
├── schemas/          # requests.py, responses.py (DTOs — resolve §3.4 e §2.1)
├── core/             # config.py, deps.py (lifespan: provider, qdrant, cross-encoder)
└── ...
```

Um único `IngestionService.ingest(text, profile_type)` elimina ~200 linhas duplicadas e dá um ponto único para o fix de rollback (§3.6).

### 4.4. Código de produção ciente dos testes

```python
# search.py:208
is_mock = type(client).__name__ in ("MagicMock", "Mock")
if hasattr(client, "query_points") and not is_mock:
```

Produção inspecionando se está sob mock é uma inversão grave: o teste deveria se moldar ao código, nunca o contrário. Isso existe porque o `conftest.py` usa `MagicMock` (que responde `hasattr` a tudo). **Correção**: fixar a versão mínima do qdrant-client que garante `query_points` e remover o branch legado `client.search` inteiro (código morto duplicado de ~30 linhas), ou usar `spec=QdrantClient` no mock.

### 4.5. Startup frágil e observabilidade zero

- `@app.on_event("startup")` está **deprecado** (FastAPI ≥0.93); usar lifespan context manager.
- O startup engole exceções com `print` (`main.py:68-69`): a API sobe "saudável" com banco não inicializado e falha só no primeiro request.
- **Não existe uma única chamada de `logging`** no `main.py` — tudo é `print`. Sem níveis, sem timestamps, sem correlação. Para um projeto que fala de auditoria, a ausência de logs estruturados (ex.: `structlog` + request ID) é uma lacuna temática.
- Nenhuma métrica (latência por etapa do pipeline, tempo de rerank, tokens LLM) — o `AuditLogModel` até tem `execution_time_ms`, mas só para o audit de viés.

### 4.6. Qualidade de retrieval — oportunidades de estado da arte

Além dos itens §1.2 (BM25 real, E5 com prefixos) e §3.2 (reranker multilíngue):

1. **Truncamento silencioso**: MiniLM-L12 trunca em 128 tokens; o `narrative_experience` ("parágrafo longo e rico", como pede o prompt) é cortado sem aviso. Chunking com mean-pooling, ou modelo long-context (`bge-m3`, 8k tokens).
2. **Vetor zero para texto vazio** (`embeddings.py:66-67`): cosine contra vetor nulo é indefinido; Qdrant devolve scores sem significado que ainda assim entram no RRF. Melhor: pular a estratégia quando o texto é vazio.
3. **Qdrant tem fusão RRF nativa** (Query API com `prefetch` + `FusionQuery(fusion=Fusion.RRF)` desde v1.10): 3 round-trips + fusão manual em Python poderiam virar **1 chamada** — menos código, menos latência. Manter a implementação própria só se o objetivo didático justificar (nesse caso, documentar a escolha).
4. **Filtro de senioridade é match exato de string** com acentos ("Sênior"): um perfil extraído como "Senior" (o LLM pode variar) nunca casa. Normalizar o enum na ingestão.
5. O harness avalia apenas 3 configurações fixas de pesos; um grid search pequeno + intervalo de confiança (bootstrap sobre queries) daria respaldo real à frase "pesos empíricos" do README.

### 4.7. Frontend: o componente-deus

`page.tsx` tem **2.275 linhas num único client component** com ~35 `useState`. Problemas concretos:

- **Impossível de testar**: nenhum teste de frontend existe, e nesta forma nenhum é viável.
- `API_BASE = "http://localhost:8000"` hardcoded (`page.tsx:23`) — sem `NEXT_PUBLIC_API_URL`, qualquer deploy quebra.
- Tipos manuais dessincronizados do backend (causa raiz do bug §3.1).
- `alert()` para erros (`page.tsx:278, 282, 422`) num produto que se descreve como "premium glassmorphic".
- Nenhum uso de Server Components apesar do App Router — a página inteira é client-side, anulando o principal benefício do Next.js 16.

**Estrutura alvo**: `lib/api-client.ts` (fetch tipado consumindo `types/api.ts` gerado), hooks por domínio (`useProfiles`, `useMatching`) ou TanStack Query, componentes por feature (`UploadModal`, `SearchPanel`, `ResultCard`, `AuditPanel`, `PdfViewer`), toasts em vez de alerts.

---

## 5. Engenharia de Processo & DevEx 🟡

| Achado | Evidência | Impacto |
|--------|-----------|---------|
| **Zero CI/CD** | Não existe `.github/` | Nenhum teste roda automaticamente; o lint do frontend e o pytest dependem de disciplina manual |
| **Sem migrations** | `Base.metadata.create_all` no startup | Qualquer mudança de schema em dados existentes exige intervenção manual; adotar Alembic |
| **Dependências duplicadas e sem lock** | `requirements.txt` + `pyproject.toml` (Poetry) coexistem, sem `poetry.lock`; versões `>=` abertas | Builds não reproduzíveis; os dois manifestos já podem divergir. Consolidar em **um** (sugestão: `uv` + `pyproject.toml` + lockfile) |
| **Makefile Windows-only** | `\.venv\Scripts\pytest` (`Makefile:10`) | `make test` quebra em Linux/macOS/CI; usar detecção de OS ou apenas `pytest` (venv ativo) |
| **Binários commitados** | `api/eval/resume_ranker_eval.db` (156K), `qdrant_storage/*.sqlite` (744K), arquivos `.lock` | Ruído em diffs, conflitos garantidos, crescimento do repo; adicionar ao `.gitignore` e remover do índice |
| **Sem lint/format/types no Python** | Nenhum ruff/black/mypy configurado | Frontend tem ESLint; backend não tem nada. Adicionar `ruff` (lint+format) e `mypy` gradual |
| **Sem `.env.example`** | README cita `.env` mas não há template | Onboarding por adivinhação |
| **Sem Dockerfile para api/web** | compose só sobe infra | O "run" do projeto é multi-terminal manual; um compose completo com healthchecks (e sem o `version: '3.8'` deprecado) daria `docker compose up` fim-a-fim |
| **ESCO com 50 skills** | `esco_skills.csv` tem 51 linhas | A taxonomia real tem ~13.9k skills; com 50, quase tudo cai no fallback de embedding ou fica `unmapped`. Documentar como amostra ou fazer download da base real no setup |
| **Testes nomeados por milestone** | `test_milestone_2.py` etc. | Organização por cronologia, não por módulo; dificulta localizar cobertura. Renomear por domínio (`test_search.py`, `test_extractor.py`) |
| **Cobertura assimétrica** | 23 testes, bons em unidades puras (RRF, NDCG, CPF); zero testes para `explain.py`, endpoints de matching e2e, fluxo de erro | O guardrail de citação — feature bandeira — não tem teste |

Nota positiva: o uso de Spec-Driven Development em `docs/specs/` com milestones é um diferencial real de processo — poucos projetos de portfólio documentam intenção antes do código. Vale manter e referenciar as specs nos PRs.

---

## 6. Roadmap Priorizado

### Fase 1 — Estancar o sangramento (1-2 dias)
1. **Remover os `Math.random()`** da aba didática (expor rankings reais ou remover a feature) — §1.1
2. **Corrigir o bug `citation` vs `text`** e passar a importar os tipos gerados — §3.1
3. **Criar DTOs de resposta Pydantic** e remover `raw_text`/`redaction_map` das respostas públicas — §3.4 + §2.1
4. **Singleton do embedding provider e do QdrantClient via lifespan** — §4.1
5. `try/finally` no cleanup dos pontos temporários do audit — §3.3.3
6. `.gitignore` para os binários de eval; remover do índice — §5

### Fase 2 — Fundação de engenharia (3-5 dias)
7. CI no GitHub Actions: pytest + ruff + mypy no backend; lint + build no frontend
8. Consolidar dependências (um manifesto + lockfile); `.env.example`; Makefile cross-platform
9. Refatorar `main.py` em routers + `IngestionService` único — §4.3
10. Exception handler global + logging estruturado com request ID — §2.2 + §4.5
11. Alembic para migrations
12. Autenticação mínima (API key) + CORS restrito — §2.1

### Fase 3 — Estado da arte em retrieval e fairness (1-2 semanas)
13. BM25 real (fastembed/Qdrant nativo) + reranker multilíngue (`bge-reranker-v2-m3` ou mMARCO) — §1.2 + §3.2
14. Fusão RRF nativa do Qdrant (Query API) eliminando o branch de mock — §4.6.3 + §4.4
15. Audit de viés: scoring pareado isolado (sem retrieval), sigmoid/rank-based delta, swaps bidirecionais, modo `inconclusive` — §1.3 + §3.3
16. Ingestão assíncrona com status de processamento — §4.2
17. Redactor: filtro por score, resolução de spans sobrepostos via `presidio-anonymizer` — §3.5
18. Decompor `page.tsx` em features + api-client tipado + TanStack Query — §4.7
19. Harness: grid search de pesos com bootstrap CI; ESCO real ou documentada como amostra

---

## Conclusão

O Resume Ranker tem uma **tese arquitetural acima da média** e módulos individualmente bem pensados (o pipeline de 3 fases do normalizer, a validação de dígito do CPF, o harness NDCG/MRR são exemplos de qualidade genuína). O que o separa do estado da arte não é falta de ambição — é o descompasso entre a narrativa e a execução: dados fabricados na UI, a feature de explicabilidade quebrada por drift de tipos, o PII vazando pela porta da frente enquanto é trancado pela dos fundos, e o modelo de embeddings sendo recarregado a cada requisição.

A boa notícia: nenhum desses problemas exige redesign. A Fase 1 inteira cabe em dois dias de trabalho e elimina os três achados críticos. As Fases 2 e 3 transformam o projeto naquilo que o README já diz que ele é.
