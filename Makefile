.PHONY: help up down logs install seed corpus dev-api dev-web test test-cov lint eval calibrate build clean

help:
	@echo "Resume Ranker — comandos disponíveis"
	@echo ""
	@echo "  make up          Sobe Postgres e Qdrant (Docker)"
	@echo "  make down        Derruba a infraestrutura"
	@echo "  make install     Instala dependências de backend e frontend"
	@echo "  make seed        Popula o ATS com o corpus de demonstração e analisa os shortlists"
	@echo "  make dev-api     Sobe a API em http://localhost:8000"
	@echo "  make dev-web     Sobe o frontend em http://localhost:3100"
	@echo "  make test        Roda a suíte de testes do backend"
	@echo "  make lint        Lint + typecheck do frontend"
	@echo "  make eval        Avaliação de recuperação (NDCG@5/@10, MRR)"
	@echo "  make calibrate   Recalibra a escala de score do reranker"

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

install:
	cd api && python -m venv .venv || true
	cd api && .venv/bin/pip install -r requirements.txt
	cd api && .venv/bin/python -m spacy download pt_core_news_lg
	cd web && npm install

corpus:
	cd $(CURDIR) && api/.venv/bin/python -m api.eval.generate_seed_corpus

seed:
	cd $(CURDIR) && api/.venv/bin/python -m api.eval.seed_ats --reset
	cd $(CURDIR) && api/.venv/bin/python -m api.eval.explain_shortlists --top 3

dev-api:
	cd $(CURDIR) && api/.venv/bin/uvicorn api.main:app --reload --port 8000

dev-web:
	cd web && npm run dev

test:
	cd $(CURDIR) && api/.venv/bin/python -m pytest api/tests -q

test-cov:
	cd $(CURDIR) && api/.venv/bin/python -m pytest api/tests --cov=api --cov-report=term-missing

lint:
	cd web && npm run lint && npx tsc --noEmit

build:
	cd web && npm run build

# Screenshots come from a production build so the dev overlay never shows up.
screenshots:
	cd web && npm run build && (npm run start &) && sleep 8 && npm run screenshots

eval:
	cd $(CURDIR) && api/.venv/bin/python -m api.eval.run_harness --readme

calibrate:
	cd $(CURDIR) && api/.venv/bin/python -m api.eval.calibrate_scores

clean:
	rm -rf api/.venv web/node_modules web/.next api/data/pdfs
