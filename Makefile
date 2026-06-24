.PHONY: up down test test-cov dev-backend dev-frontend

up:
	docker-compose up -d

down:
	docker-compose down

test:
	cd api && .venv\Scripts\pytest -v

dev-backend:
	cd api && .venv\Scripts\uvicorn api.main:app --reload

dev-frontend:
	cd web && npm run dev
