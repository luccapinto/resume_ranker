# Proposta: Arquitetura de Matching Currículo ↔ Vaga (Estado da Arte)

> Complemento à `ARCHITECTURE_REVIEW.md`. Aqui o foco não é código, é o **desenho do motor de matching**: como transformar "busca por similaridade" em "avaliação de compatibilidade", bidirecional (vaga→talentos e candidato→vagas).

---

## 1. A tese central: matching não é similaridade

A arquitetura atual (e a maioria das propostas ingênuas) trata o problema como *information retrieval clássico*: "encontre documentos parecidos com a query". Mas compatibilidade candidato-vaga tem propriedades que similaridade semântica não captura:

1. **Assimetria direcional**: um candidato que *excede* o requisito (8 anos quando a vaga pede 5) é ótimo; um que *fica aquém* (3 anos) é problema. Cosseno não tem direção — os dois casos podem ter a mesma similaridade.
2. **Restrições duras vs. graduais**: "inglês fluente obrigatório" é um gate binário; "desejável Kubernetes" é um bônus gradual. Um único score escalar de embedding mistura os dois.
3. **Cobertura, não sobreposição**: o que importa é "quantos dos requisitos da vaga o candidato cobre", não "quão parecidos os textos são". Um currículo júnior de React é semanticamente *muito* similar a uma vaga sênior de React — e é um match ruim.
4. **A armadilha da senioridade**: cross-encoders treinados em relevância de busca web (MS MARCO e afins) medem "este documento responde esta query?" — eles não sabem que "estagiário com projetos em Python" não *qualifica* para "arquiteto Python sênior", apenas que os textos falam do mesmo assunto.

Conclusão: o estado da arte não é um pipeline de retrieval melhor — é um **funil onde retrieval é só o primeiro estágio**, seguido de um estágio de *compatibilidade estruturada* que entende cobertura e direção, e um estágio final de julgamento profundo.

---

## 2. Avaliação da arquitetura proposta (extração JSON → densa no JSON + esparsa em campos → CE no documento completo)

| Ideia | Veredito | Análise |
|-------|----------|---------|
| Extração LLM → JSON estruturado | ✅ Manter | Já existe no projeto e é a fundação correta. Falta extrair a distinção **must-have vs. nice-to-have** dos requisitos da vaga (hoje o schema trata tudo como uma lista plana de skills) — essa distinção é o insumo mais valioso de todo o pipeline. |
| Busca densa no "JSON todo" | ⚠️ Ajustar | Embeddar JSON serializado é subótimo: chaves, colchetes e aspas são ruído que dilui o sinal semântico, e modelos de embedding foram treinados em prosa, não em JSON. O ajuste é barato: **renderizar o JSON num "profile card" em linguagem natural** via template determinístico ("Profissional Sênior com 8 anos de experiência. Competências: Python, PostgreSQL, AWS. Trajetória: …") e embeddar isso. Mantém a informação estruturada, recupera a distribuição de texto que o modelo conhece. |
| Esparsa em campos selecionados (skills, tecnologias) | ✅ Manter, e ir além | Correto — léxico exato importa para termos técnicos. Mas para skills **normalizadas** existe algo mais forte que busca esparsa: **match exato de IDs ESCO no payload** do Qdrant. Se os dois lados foram normalizados para a mesma taxonomia, "React.js" e "ReactJS" já são o mesmo URI — é um filtro/boost estrutural, não uma busca textual. A esparsa fica para o que a taxonomia não cobre (certificações, ferramentas de nicho, siglas internas). |
| Cross-encoder no documento completo (não nos JSONs) | ✅ Instinto certo, com 3 caveats | (a) **Contexto**: currículo de 2-4 páginas + descrição completa da vaga estoura os 512 tokens dos CEs clássicos — o par seria truncado silenciosamente e o modelo veria só o cabeçalho de cada um. Precisa de reranker long-context (8k). (b) **Idioma**: precisa ser multilíngue treinado com PT-BR. (c) **Fairness**: rerankear o documento *bruto* injeta nome, gênero e endereço direto no modelo que decide o ranking — o par correto é **texto redigido do candidato × texto completo da vaga**. Isso transforma a redação de PII, que hoje só protege contra o LLM externo, em proteção estrutural do próprio ranking ("fairness by architecture"). |

O que falta na proposta — e é o que separa "bom RAG" de "sistema de matching": **nenhum estágio entende cobertura de requisitos nem direção de senioridade**. É o estágio 2 do funil abaixo.

---

## 3. Arquitetura proposta: funil de 4 estágios

```
                      base de talentos / base de vagas (10³–10⁶ perfis)
                                        │
  ┌─────────────────────────────────────▼────────────────────────────────────┐
  │ ESTÁGIO 0 · INGESTÃO (offline, por perfil)                               │
  │  PDF → redação PII → LLM extração (JSON c/ must-have vs nice-to-have)    │
  │  → normalização ESCO → render "profile card" → embeddings → Qdrant       │
  └─────────────────────────────────────┬────────────────────────────────────┘
                                        │
  ┌─────────────────────────────────────▼────────────────────────────────────┐
  │ ESTÁGIO 1 · RECALL (~200 perfis)                    custo: ~10ms         │
  │  filtros duros no payload (idioma, senioridade ±1, anos mínimos)         │
  │  + densa (profile card) + densa (narrativa) + esparsa aprendida          │
  │  + boost por interseção de IDs ESCO — fusão RRF nativa do Qdrant         │
  └─────────────────────────────────────┬────────────────────────────────────┘
                                        │
  ┌─────────────────────────────────────▼────────────────────────────────────┐
  │ ESTÁGIO 2 · COMPATIBILIDADE ESTRUTURADA (200 → 50)  custo: ~µs/par       │
  │  features determinísticas por par:                                       │
  │   · cobertura de must-haves (taxonomia-aware)   · delta de senioridade   │
  │   · cobertura de nice-to-haves                  · fit de anos (assimétrico)│
  │   · idiomas, certificações                      · scores do estágio 1    │
  │  combinação: pesos manuais → LambdaMART treinado nos qrels               │
  └─────────────────────────────────────┬────────────────────────────────────┘
                                        │
  ┌─────────────────────────────────────▼────────────────────────────────────┐
  │ ESTÁGIO 3 · RERANK PROFUNDO (50 → 20)               custo: ~1-2s         │
  │  cross-encoder long-context multilíngue                                  │
  │  par = texto REDIGIDO completo do candidato × texto completo da vaga     │
  └─────────────────────────────────────┬────────────────────────────────────┘
                                        │
  ┌─────────────────────────────────────▼────────────────────────────────────┐
  │ ESTÁGIO 4 · VEREDITO LLM (top 10-20, on-demand/async) custo: ~5-15s      │
  │  rubrica estruturada: cada must-have → atendido/parcial/não + citação    │
  │  verificada. Gera o score final calibrado E a explicação num passo só.   │
  └───────────────────────────────────────────────────────────────────────────┘
```

### Estágio 0 — Ingestão: o que muda

1. **Schema da vaga ganha estrutura de requisitos** (a mudança mais importante do documento):

```python
class Requirement(BaseModel):
    skill_raw: str
    esco_uri: Optional[str]          # preenchido pelo normalizer
    level: Literal["must", "nice"]   # extraído pelo LLM do texto da vaga
    min_years: Optional[float]       # "5+ anos de Python" → 5.0 no requisito, não só global

class JobRequirements(BaseModel):
    requirements: list[Requirement]  # substitui skills_raw plano
    ...
```

Sem essa distinção, todos os estágios seguintes tratam "obrigatório: inglês fluente" e "desejável: Grafana" com o mesmo peso — e nenhum threshold de score conserta isso depois.

2. **Profile card renderizado** (resolve o problema do "embeddar JSON"): template determinístico que serializa o perfil em prosa densa e curta. Duas variantes por perfil — uma otimizada como *documento* e outra como *query* — porque é isso que resolve a bidirecionalidade (ver §4).

3. **Modelo de embedding**: `BAAI/bge-m3` é o encaixe quase perfeito para este projeto — um único modelo produz **denso + esparso aprendido (com IDF real) + multi-vetor**, é multilíngue com PT-BR forte e aceita 8k tokens (elimina o truncamento silencioso da narrativa em 128 tokens). Substitui de uma vez o MiniLM e o pseudo-BM25 de hash MD5. Alternativa API: `voyage-3-large` / `text-embedding-3-large` para o denso + BM25 nativo do Qdrant para o esparso.

### Estágio 1 — Recall: maximizar recall@200, não precisão

- **Filtros duros primeiro** (payload do Qdrant, pré-ANN): idioma obrigatório, senioridade em banda (`vaga ±1 nível`, nunca match exato de string acentuada como hoje), anos mínimos. Filtro elimina; não rebaixa.
- **Expansão de skills via grafo ESCO**: a taxonomia real tem relações broader/narrower — uma vaga pedindo "PostgreSQL" deve recuperar candidatos fortes em "bancos relacionais". Expandir os URIs da query com vizinhos de 1 salto antes da busca compra recall que embedding sozinho perde.
- **Fusão RRF nativa** (`prefetch` + `FusionQuery`, Qdrant ≥1.10): uma chamada em vez de três + fusão manual em Python.
- **Métrica deste estágio**: recall@200 contra os qrels — se o candidato certo não entra aqui, nenhum estágio posterior o salva. Hoje o harness só mede o funil inteiro; medir por estágio é o que permite diagnosticar onde o ranking perde.

### Estágio 2 — Compatibilidade estruturada: o coração ausente

Para cada par (vaga, candidato) sobrevivente, computar features **determinísticas, baratas e interpretáveis**:

| Feature | Cálculo | Por que importa |
|---------|---------|-----------------|
| `must_coverage` | fração dos must-haves com match ESCO exato, vizinho no grafo (0.7) ou similaridade de embedding ≥0.8 (0.5) | O sinal nº 1 de compatibilidade real |
| `nice_coverage` | idem para nice-to-haves | Desempate entre qualificados |
| `seniority_delta` | níveis de distância, **assimétrico**: candidato abaixo penaliza 3× mais que acima | Codifica a direção que o cosseno não vê |
| `years_fit` | `min(anos_candidato / anos_vaga, 1.5)` — saturado para não premiar excesso infinito | Idem |
| `cert_match`, `lang_match` | interseção exata | Gates que viram feature |
| `dense_skills`, `dense_narrative`, `sparse`, `rrf` | herdados do estágio 1 | O sinal semântico continua no jogo |

Combinação em duas fases de maturidade: **(a)** score linear com pesos manuais — já supera o RRF puro e é 100% explicável ("cobriu 4/5 obrigatórios, senioridade exata"); **(b)** quando os qrels crescerem (~50+ queries), treinar **LambdaMART (LightGBM) otimizando NDCG** sobre essas features — é literalmente o que LinkedIn e Indeed fazem em produção, e o harness de avaliação do projeto vira o conjunto de treino/validação em vez de só relatório.

Bônus: o breakdown por feature **é** a explicação preliminar — a UI pode mostrar "cobertura de requisitos: 80%" por candidato sem custar um único token de LLM.

### Estágio 3 — Rerank profundo (a sua ideia, corrigida)

- **Modelo**: `BAAI/bge-reranker-v2-m3` — multilíngue, 8k de contexto, roda local. Resolve os três caveats do CE atual (inglês-only, 512 tokens, escala de logit não calibrada — aplicar sigmoid na saída).
- **Par de entrada**: `texto_redigido_do_candidato × texto_completo_da_vaga`. Documento completo, como você propôs — a extração JSON perde nuance (contexto de projetos, progressão de carreira) que o reranker consegue ler no texto corrido. Mas o lado candidato **sempre redigido**: o modelo que ordena pessoas não deve ver nome, gênero ou bairro. Isso torna o audit contrafactual quase-tautológico por construção — muito mais forte que auditar depois.
- **Score final do ranking** = combinação (ex.: `0.6·CE_sigmoid + 0.4·score_estágio_2`), não substituição — o CE entende texto, o estágio 2 entende requisitos; nenhum dos dois sozinho basta.

### Estágio 4 — Veredito LLM com rubrica (funde ranking fino + explicabilidade)

Para o top 10-20, on-demand ou assíncrono com cache por par `(candidate_id, job_id, version)`:

```json
{
  "verdict": "strong_match",
  "requirements_assessment": [
    {"requirement": "Python 5+ anos", "status": "met",
     "evidence": "…liderou o backend Python por 6 anos na…", "verified": true},
    {"requirement": "Inglês fluente", "status": "not_found", "evidence": null}
  ],
  "concerns": ["gap de 18 meses não explicado entre 2023-2024"],
  "score": 87
}
```

Cada `evidence` passa pelo guardrail de citação já existente (`verify_citation`). Isso **substitui** o `/matching/explain` atual por algo estritamente melhor: em vez de prosa livre + citações soltas, um julgamento requisito-a-requisito que é simultaneamente o refinamento final do score e a explicação auditável. O score de 0-100 calibrado pela rubrica é o número que um recrutador consegue comparar entre vagas — logit de cross-encoder não é.

---

## 4. Bidirecionalidade sem gambiarra

O requisito "vaga→talentos e candidato→vagas" fica elegante porque **o funil é simétrico por construção** — só o que troca é quem é query e quem é corpus:

1. **Duas collections espelhadas** (`candidates`, `jobs`) com o mesmo schema de vetores e payload — já é assim hoje, manter.
2. **Embeddings assimétricos por papel, não por entidade**: modelos modernos distinguem query de documento (prefixos `query:`/`passage:` no E5, instruções no bge). Cada perfil é indexado como *documento* e, quando dispara uma busca, é embeddado como *query* com a instrução da direção: "Represente esta vaga para encontrar candidatos compatíveis" vs. "Represente este candidato para encontrar vagas compatíveis". Custo: um embedding extra por busca. Ganho: o modelo sabe o que está fazendo.
3. **Estágio 2 com direção invertida automaticamente**: as features são definidas sobre o par ordenado (vaga, candidato) — na direção candidato→vagas, `must_coverage` responde "quantos requisitos *desta vaga* eu cubro" e o ranking ordena as vagas por isso. Mesma função, argumentos trocados.
4. **Um único code path**: `MatchingService.match(query_profile, target_collection, direction)` — elimina os ~190 linhas duplicadas dos dois endpoints atuais de matching como efeito colateral.

---

## 5. Sequência de adoção (cada passo é útil sozinho)

| Passo | Entrega | Esforço | Ganho esperado |
|-------|---------|---------|----------------|
| 1 | Schema `Requirement` com must/nice + prompt de extração | 1 dia | Fundação de tudo; melhora imediata da explicação |
| 2 | `bge-m3` (denso+esparso) + profile cards + fusão nativa Qdrant | 2-3 dias | Mata 4 problemas de uma vez (MiniLM 128 tokens, pseudo-BM25, CE… e o branch de mock) |
| 3 | Estágio 2 com pesos manuais + breakdown na UI | 2 dias | O maior salto de qualidade de ranking do roadmap inteiro |
| 4 | `bge-reranker-v2-m3` sobre texto redigido completo | 1 dia | Rerank que finalmente entende português — e fairness estrutural |
| 5 | Veredito LLM com rubrica substituindo `/matching/explain` | 2-3 dias | Score calibrado 0-100 + explicação auditável num passo |
| 6 | qrels ampliados + recall@200 por estágio + LambdaMART | 1-2 semanas | De "pesos escolhidos na tabela" para ranking aprendido com evidência |

Medir cada passo no harness antes de avançar ao próximo — o projeto já tem a infraestrutura de avaliação; ela vira o guard-rail da migração.
