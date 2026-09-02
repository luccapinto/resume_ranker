"""Document ingestion and retrieval — the AI-artefact side of the platform."""

from __future__ import annotations

import os
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from api import ats
from api import observability as obs
from api.config import settings
from api.database import get_db
from api.models import ProfileModel
from api.services import get_ingestion, get_normalizer

router = APIRouter(tags=["perfis"])


def _generate_pdf_from_text(text: str) -> bytes:
    """Render plain text into a simple A4 PDF, for profiles ingested as text."""
    import fitz

    doc = fitz.open()
    max_chars_per_page = 2500
    chunks = [text[i : i + max_chars_per_page] for i in range(0, len(text), max_chars_per_page)] or [""]
    for chunk in chunks:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(50, 50, 545, 792), chunk, fontsize=10.5, fontname="helv")
    return doc.write()


def _ingest(
    db: Session,
    profile_type: str,
    file: Optional[UploadFile],
    text_content: Optional[str],
) -> ProfileModel:
    if not file and not text_content:
        raise HTTPException(status_code=400, detail="Informe um arquivo PDF ou text_content.")

    file_bytes = None
    file_name = None
    if file:
        file_name = file.filename or "upload.pdf"
        if not file_name.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Apenas arquivos PDF são suportados.")
        file_bytes = file.file.read()

    ingestion = get_ingestion()
    with obs.trace(f"ingest.{profile_type}", file_name=file_name, source="pdf" if file_bytes else "texto"):
        try:
            raw_text = ingestion.read_source(file_bytes, file_name, text_content)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"Falha ao ler o PDF: {e}") from e

        if not raw_text or not raw_text.strip():
            raise HTTPException(status_code=400, detail="Nenhum texto legível encontrado no documento.")

        try:
            return ingestion.build_profile(
                db, raw_text, profile_type, file_name=file_name, file_bytes=file_bytes
            )
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Falha no pipeline de ingestão: {e}") from e


@router.post("/profiles/candidate", response_model=dict)
def create_candidate_profile(
    file: Optional[UploadFile] = File(None),
    text_content: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Ingest a résumé: redact PII, extract structure, normalise skills, index."""
    return ats.serialize_profile(_ingest(db, "candidate", file, text_content))


@router.post("/profiles/job", response_model=dict)
def create_job_profile(
    file: Optional[UploadFile] = File(None),
    text_content: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Ingest a job description through the same pipeline."""
    return ats.serialize_profile(_ingest(db, "job", file, text_content))


@router.get("/profiles/candidates", response_model=List[dict])
def list_candidate_profiles(db: Session = Depends(get_db)):
    rows = (
        db.query(ProfileModel)
        .filter(ProfileModel.type == "candidate")
        .order_by(ProfileModel.created_at.desc())
        .all()
    )
    return [ats.serialize_profile(p) for p in rows]


@router.get("/profiles/jobs", response_model=List[dict])
def list_job_profiles(db: Session = Depends(get_db)):
    rows = (
        db.query(ProfileModel)
        .filter(ProfileModel.type == "job")
        .order_by(ProfileModel.created_at.desc())
        .all()
    )
    return [ats.serialize_profile(p) for p in rows]


@router.get("/profiles/{profile_id}", response_model=dict)
def get_profile(profile_id: int, db: Session = Depends(get_db)):
    profile = db.query(ProfileModel).filter(ProfileModel.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Perfil não encontrado.")
    return ats.serialize_profile(profile)


@router.get("/profiles/{profile_id}/pdf")
def get_profile_pdf(profile_id: int, db: Session = Depends(get_db)):
    """Serve the original upload when there is one, else render the text."""
    profile = db.query(ProfileModel).filter(ProfileModel.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Perfil não encontrado.")

    path = os.path.join(settings.pdf_dir, f"{profile.type}_{profile_id}.pdf")
    filename = profile.file_name or f"{profile.type}_{profile_id}.pdf"
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"

    if profile.has_pdf and os.path.exists(path):
        with open(path, "rb") as f:
            pdf_bytes = f.read()
    else:
        try:
            pdf_bytes = _generate_pdf_from_text(profile.raw_text)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Erro ao gerar PDF: {e}") from e

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/skills/normalize", response_model=List[dict])
def normalize_skills_list(skills: List[str]):
    """Ad-hoc ESCO normalisation, handy for debugging the taxonomy coverage."""
    try:
        return [s.model_dump() for s in get_normalizer().normalize_batch(skills)]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Falha ao normalizar competências: {e}") from e
