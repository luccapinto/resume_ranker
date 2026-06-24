import os
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from qdrant_client import QdrantClient

from api.database import get_db, Base, engine
from api.config import settings

app = FastAPI(
    title="Resume Ranker API",
    description="Backend API for Resume Ranker platform",
    version="0.1.0"
)

# Initialize database tables on startup
# In a production app, we would use Alembic migrations, but for the MVP, Base.metadata.create_all is perfect.
@app.on_event("startup")
def on_startup():
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        print(f"Error creating database tables: {e}")

@app.get("/health")
def healthcheck(db: Session = Depends(get_db)):
    postgres_status = "disconnected"
    qdrant_status = "disconnected"
    
    # Check Postgres
    try:
        db.execute(text("SELECT 1"))
        postgres_status = "connected"
    except Exception as e:
        postgres_status = f"error: {str(e)}"
        
    # Check Qdrant
    try:
        qdrant_client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        # Try getting collections to verify connection
        qdrant_client.get_collections()
        qdrant_status = "connected"
    except Exception as e:
        qdrant_status = f"error: {str(e)}"
        
    is_healthy = postgres_status == "connected" and qdrant_status == "connected"
    
    status_code = 200 if is_healthy else 500
    
    # For testing/deployment purposes, if there is a connection issue, return 500
    # but still return the details in the JSON body
    response_body = {
        "status": "ok" if is_healthy else "unhealthy",
        "postgres": postgres_status,
        "qdrant": qdrant_status
    }
    
    if not is_healthy:
        raise HTTPException(status_code=status_code, detail=response_body)
        
    return response_body

@app.get("/openapi.json")
def get_openapi():
    return app.openapi()
