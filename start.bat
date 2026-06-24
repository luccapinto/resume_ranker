@echo off
echo Starting Resume Ranker local infrastructure (Postgres + Qdrant)...
docker-compose up -d
echo Infrastructure is running!
echo To run backend tests: make test
echo To run backend: make dev-backend
echo To run frontend: make dev-frontend
