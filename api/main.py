"""Resume Ranker ATS — application entrypoint."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

import api.models  # noqa: F401 — registers the SQLAlchemy metadata
from api import telemetry
from api.config import settings
from api.database import Base, engine, get_qdrant
from api.embeddings import get_embedding_provider
from api.search import init_qdrant_collections

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("resume_ranker")


@asynccontextmanager
async def lifespan(app: FastAPI):
    telemetry.install()
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Tabelas do banco inicializadas.")
    except Exception:
        logger.exception("Falha ao criar as tabelas do banco")

    try:
        init_qdrant_collections(get_qdrant(), get_embedding_provider().dimension)
        logger.info("Coleções do Qdrant prontas.")
    except Exception:
        logger.exception("Falha ao inicializar o Qdrant")

    yield


app = FastAPI(
    title="Resume Ranker ATS API",
    description=(
        "ATS com ranqueamento de candidatos por IA: busca híbrida (denso + esparso), "
        "reranking por cross-encoder, explicabilidade com citações verificadas, "
        "auditoria contrafactual de viés e observabilidade fim a fim."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    """Expose server-side latency so the UI can show it without a round trip."""
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Response-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.2f}"
    return response


from api.routers import ats, copilot, health, matching, observability, profiles  # noqa: E402

app.include_router(health.router)
app.include_router(profiles.router)
app.include_router(matching.router)
app.include_router(ats.router)
app.include_router(copilot.router)
app.include_router(observability.router)


@app.get("/openapi.json", include_in_schema=False)
def get_openapi():
    return app.openapi()
