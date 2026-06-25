# Resume Ranker 🤖💼

> Plataforma de Matching Candidato-Vaga com IA, Busca Semântica Híbrida, Governança de Viés e Explicabilidade de Ponta a Ponta.

Este é um projeto de portfólio profissional de arquitetura aberta que resolve as limitações das ferramentas tradicionais de triagem de talentos. Em vez de depender apenas de busca lexical (palavras-chave rígidas) ou busca semântica pura (que pode ignorar requisitos duros), o **Resume Ranker** combina o melhor dos dois mundos em um sistema híbrido robusto e auditável.

---

## 🚀 Diferenciais da Plataforma

1. **Busca Híbrida Semântica & Lexical (Bidirecional)**:
   - **Vetor Denso (Skills)**: Mapeamento semântico de competências técnicas normalizadas contra a base europeia oficial **ESCO**.
   - **Vetor Denso (Narrativa)**: Similaridade de cosseno sobre a trajetória livre e experiências descritas.
   - **Vetor Esparso (Léxico)**: Termos técnicos exatos e certificações indexados nativamente no Qdrant.
   - **RRF (Reciprocal Rank Fusion)**: Fusão matemática dos múltiplos rankings antes do refino.
   - **Reranker Cross-Encoder**: Processamento profundo sobre o top-K do ranking final usando modelo local leve.

2. **Módulo de Explicabilidade Baseada em Evidências**:
   - Justificativa textual gerada por LLM contendo evidências explícitas do match.
   - **Guardrail de Alucinação (Validação de Citação)**: Validação automática de substring no backend para certificar que as citações trazidas pelo modelo existem 100% textualmente no currículo bruto original.

3. **Módulo de Governança & Auditoria de Viés (Fairness)**:
   - **PII Redactor**: Anonimização local obrigatória (Microsoft Presidio + spaCy pt-BR) de dados como CPF, RG, telefones, nomes e e-mails antes de qualquer envio a APIs de LLM externas.
   - **Auditoria de Viés Contraditório (Counterfactual Audit)**: Teste contraditório automatizado que clona o currículo, realiza swaps de gênero (ele/ela, programador/programadora) e nomes fictícios comuns e afere a variação (delta) do score de similaridade, que deve ser menor que 1% para aprovação.

4. **Harness de Avaliação Quantitativa**:
   - Avaliação quantitativa de Information Retrieval calculando **NDCG@5**, **NDCG@10** e **MRR** contra um gabarito rotulado (`qrels.json`) para determinar os melhores pesos empíricos de busca.

---

## 🛠️ Stack Tecnológica

### Backend (`/api`)
- **FastAPI**: Endpoints rápidos e auto-documentados via Swagger/OpenAPI.
- **SQLAlchemy & SQLite/PostgreSQL**: Persistência relacional para perfis brutos, anonimizados, metadados extraídos e logs de auditoria.
- **Qdrant**: Banco de dados vetorial de alta performance para armazenamento de múltiplos vetores nomeados (`skills_vector`, `narrative_vector` e `lexical_vector`).
- **Sentence-Transformers**: Execução local de modelos de embedding (E5) e Cross-Encoder.
- **Microsoft Presidio + spaCy**: Reconhecimento e higienização local de PII.

### Frontend (`/web`)
- **Next.js 16 (App Router)** & **React 19**: Estrutura moderna para SPA.
- **TailwindCSS v4**: Estilização fluida e de última geração.
- **Design System Premium (Glassmorphic Dark Mode)**: Interface translúcida com efeitos de desfoque, gradientes dinâmicos de luz e custom scrollbars.
- **TypeScript & openapi-typescript**: Tipagem 100% segura gerada diretamente a partir do endpoint de documentação do backend.
- **Lucide-React**: Coleção moderna de ícones vetoriais.

---

## 📁 Estrutura de Diretórios

```text
resume_ranker/
├── api/                  # Código do Backend (FastAPI)
│   ├── data/             # Base de dados offline ESCO
│   ├── eval/             # Scripts de Seed e Avaliação (NDCG/MRR)
│   ├── tests/            # Suíte de testes unitários e de integração
│   ├── main.py           # Configuração de rotas e startup da API
│   ├── search.py         # Motor de busca híbrida no Qdrant + RRF + Reranker
│   ├── fairness.py       # Auditoria de viés contraditório e swaps
│   └── explain.py        # Geração de explicações e guardrails de citação
├── web/                  # Código do Frontend (Next.js)
│   ├── src/
│   │   ├── app/          # Páginas e estilo global (page.tsx, globals.css)
│   │   └── types/        # Tipagem TypeScript auto-gerada
│   └── package.json      # Dependências do Next.js
└── docs/                 # Especificações do Spec Driven Development (SDD)
```

---

## 🔧 Como Executar o Projeto Localmente

### Passo 1: Executar o Backend (`/api`)

1. Navegue até a pasta do backend:
   ```bash
   cd api
   ```

2. Crie e ative um ambiente virtual Python:
   ```bash
   python -m venv .venv
   # No Windows (PowerShell):
   .venv\Scripts\Activate.ps1
   # No Linux/Mac:
   source .venv/bin/activate
   ```

3. Instale as dependências necessárias:
   ```bash
   pip install -r requirements.txt
   ```

4. Baixe o modelo de idioma do spaCy para anonimização em português:
   ```bash
   python -m spacy download pt_core_news_lg
   ```

5. Crie ou configure seu arquivo `.env` (ou utilize as variáveis padrão integradas):
   ```env
   OPENROUTER_API_KEY=sua_chave_aqui
   EMBEDDING_PROVIDER=local  # Opções: local, voyage, openai
   ```
   *Nota: O sistema possui fallback automático local (SQLite em disco e armazenamento persistido do Qdrant na pasta `api/eval/qdrant_storage`) dispensando setup complexo de Docker se preferir rodar de forma isolada.*

6. Inicie o servidor FastAPI:
   ```bash
   uvicorn api.main:app --reload --port 8000
   ```

### Passo 2: Executar o Frontend (`/web`)

1. Abra um terminal separado na pasta do frontend:
   ```bash
   cd web
   ```

2. Instale os pacotes npm:
   ```bash
   npm install
   ```

3. Com a API do backend em execução na porta 8000, você pode gerar/atualizar os tipos de tipos estáticos do TypeScript:
   ```bash
   npx openapi-typescript ../api/openapi.json -o src/types/api.ts
   ```

4. Inicie o servidor de desenvolvimento:
   ```bash
   npm run dev
   ```
   Acesse a interface premium no navegador em: `http://localhost:3000`.

---

## 🧪 Suíte de Testes e Validação

### Testes Automatizados do Backend
A plataforma possui testes unitários matemáticos para as métricas de recuperação, testes de fluxo de anonimização (PII Redactor) e testes de integração simulando a busca vetorial complexa.

Execute a suíte com o ambiente virtual ativo a partir da raiz ou pasta `/api`:
```bash
# Executado a partir da pasta /api
.venv\Scripts\python -m pytest
```

### Build e Lint do Frontend
Para garantir a qualidade e corretude estática do código no frontend:
```bash
# Executado a partir da pasta /web
npm run lint
npm run build
```

---

## 📊 Rodando o Benchmarking de Pesos (Information Retrieval)

Você pode simular e avaliar a eficácia do algoritmo de busca híbrida com diferentes configurações de pesos de vetores denso/esparso rodando o script de avaliação nativo:
```bash
# Executado a partir da pasta /api com venv ativo
python -m api.eval.run_harness
```
Este script calculará e imprimirá em formato tabular os ganhos de **NDCG@5**, **NDCG@10** e **MRR** sob variadas composições de peso vetorial, garantindo embasamento empírico na escolha da parametrização de busca.
