from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.config import settings
from api.database import get_db, get_qdrant
from api.llm import get_llm
from api.embeddings import get_embedding_provider

router = APIRouter(tags=["sistema"])


@router.get("/health")
def healthcheck(db: Session = Depends(get_db)):
    """Liveness probe covering both storage backends."""
    try:
        db.execute(text("SELECT 1"))
        postgres_status = "connected"
    except Exception as e:  # noqa: BLE001
        postgres_status = f"error: {e}"

    try:
        get_qdrant().get_collections()
        qdrant_status = "connected"
    except Exception as e:  # noqa: BLE001
        qdrant_status = f"error: {e}"

    body = {
        "status": "ok" if postgres_status == "connected" and qdrant_status == "connected" else "unhealthy",
        "postgres": postgres_status,
        "qdrant": qdrant_status,
    }
    if body["status"] != "ok":
        raise HTTPException(status_code=500, detail=body)
    return body


@router.get("/config")
def runtime_config():
    """What the running stack is actually using — surfaced in the UI footer."""
    llm = get_llm()
    return {
        "llm_model": llm.model,
        "llm_configured": llm.is_configured,
        # Tasks differ in what they need from a model; see api/llm.py:get_llm.
        "llm_models_by_task": {
            "extraction": get_llm("extraction").model,
            "explanation": get_llm("explanation").model,
            "copilot": get_llm("copilot").model,
        },
        "embedding_provider": settings.EMBEDDING_PROVIDER,
        "embedding_model": get_embedding_provider().name,
        "reranker_model": settings.RERANKER_MODEL,
        "vector_store": f"qdrant://{settings.QDRANT_HOST}:{settings.QDRANT_PORT}",
    }
