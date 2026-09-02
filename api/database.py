import threading

from qdrant_client import QdrantClient
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from api.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

_qdrant_client = None
_qdrant_lock = threading.Lock()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_qdrant() -> QdrantClient:
    """Process-wide Qdrant client — reconnecting per request was wasteful."""
    global _qdrant_client
    if _qdrant_client is None:
        with _qdrant_lock:
            if _qdrant_client is None:
                _qdrant_client = QdrantClient(
                    host=settings.QDRANT_HOST, port=settings.QDRANT_PORT, timeout=30
                )
    return _qdrant_client
