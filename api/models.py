from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from api.database import Base


# ─────────────────────────────────────────────────────────────────────────────
# AI artefacts — the raw document plus everything the pipeline derived from it
# ─────────────────────────────────────────────────────────────────────────────
class ProfileModel(Base):
    """An ingested document (resume or job description) and its extraction.

    `raw_text` never leaves this table; only `redacted_text` is sent to an LLM.
    `redaction_map` is the reverse index that lets the UI show a recruiter the
    real name while proving the model only ever saw a placeholder.
    """

    __tablename__ = "profiles"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, nullable=False, index=True)  # 'candidate' | 'job'
    file_name = Column(String, nullable=True)
    raw_text = Column(Text, nullable=False)
    redacted_text = Column(Text, nullable=False)
    redaction_map = Column(JSON, nullable=False, default=dict)
    extracted_profile = Column(JSON, nullable=False)
    has_pdf = Column(Boolean, nullable=False, default=False)
    trace_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class AuditLogModel(Base):
    """One counterfactual fairness audit run."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    query_type = Column(String, nullable=False)
    query_id = Column(Integer, nullable=False)
    embedding_model = Column(String, nullable=False)
    reranker_model = Column(String, nullable=False)
    execution_time_ms = Column(Integer, nullable=False)
    bias_audit_passed = Column(Integer, nullable=False)
    bias_audit_results = Column(JSON, nullable=False, default=dict)
    trace_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


# ─────────────────────────────────────────────────────────────────────────────
# ATS domain
# ─────────────────────────────────────────────────────────────────────────────
STAGES = [
    "sourced",
    "screening",
    "interview",
    "offer",
    "hired",
    "rejected",
]

STAGE_LABELS = {
    "sourced": "Triagem inicial",
    "screening": "Entrevista RH",
    "interview": "Entrevista técnica",
    "offer": "Proposta",
    "hired": "Contratado",
    "rejected": "Reprovado",
}


class JobModel(Base):
    """A job opening as a recruiter sees it."""

    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    department = Column(String, nullable=True)
    location = Column(String, nullable=True)
    work_model = Column(String, nullable=True)       # remoto | híbrido | presencial
    employment_type = Column(String, nullable=True)  # CLT | PJ | Estágio
    seniority = Column(String, nullable=True)
    salary_min = Column(Integer, nullable=True)
    salary_max = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="open", index=True)  # open | paused | closed
    headcount = Column(Integer, nullable=False, default=1)
    owner = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    profile = relationship("ProfileModel", foreign_keys=[profile_id])
    applications = relationship("ApplicationModel", back_populates="job", cascade="all, delete-orphan")


class CandidateModel(Base):
    """A person in the talent pool.

    Identity fields live here and *only* here — the ranking pipeline reads from
    `ProfileModel.redacted_text`, so none of these columns ever reach a model.
    """

    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    display_name = Column(String, nullable=False)
    headline = Column(String, nullable=True)
    location = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    source = Column(String, nullable=True)  # LinkedIn | Indicação | Site | Banco de talentos
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    profile = relationship("ProfileModel", foreign_keys=[profile_id])
    applications = relationship("ApplicationModel", back_populates="candidate", cascade="all, delete-orphan")


class ApplicationModel(Base):
    """A candidate moving through the funnel of one job."""

    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    stage = Column(String, nullable=False, default="sourced", index=True)

    # AI ranking snapshot — refreshed whenever the job is re-ranked
    ai_score = Column(Float, nullable=True)
    ai_rank = Column(Integer, nullable=True)
    ai_rrf_score = Column(Float, nullable=True)
    ai_fit = Column(String, nullable=True)  # forte | moderado | baixo
    ai_summary = Column(Text, nullable=True)
    ai_matched_skills = Column(JSON, nullable=False, default=list)
    ai_missing_skills = Column(JSON, nullable=False, default=list)
    ai_signals = Column(JSON, nullable=False, default=dict)
    ranked_at = Column(DateTime, nullable=True)
    trace_id = Column(String, nullable=True, index=True)

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    candidate = relationship("CandidateModel", back_populates="applications")
    job = relationship("JobModel", back_populates="applications")
    activities = relationship(
        "ActivityModel", back_populates="application", cascade="all, delete-orphan"
    )


class ActivityModel(Base):
    """Timeline entry for an application (stage moves, notes, AI events)."""

    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(
        Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type = Column(String, nullable=False)  # stage_change | note | ai_rank | ai_explain | bias_audit
    actor = Column(String, nullable=False, default="Sistema")
    content = Column(Text, nullable=True)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    application = relationship("ApplicationModel", back_populates="activities")


# ─────────────────────────────────────────────────────────────────────────────
# Observability
# ─────────────────────────────────────────────────────────────────────────────
class TraceModel(Base):
    __tablename__ = "traces"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, index=True)
    duration_ms = Column(Float, nullable=False)
    total_tokens = Column(Integer, nullable=False, default=0)
    total_cost_usd = Column(Float, nullable=False, default=0.0)
    llm_calls = Column(Integer, nullable=False, default=0)
    span_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    trace_metadata = Column("metadata", JSON, nullable=False, default=dict)
    started_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    spans = relationship("SpanModel", back_populates="trace", cascade="all, delete-orphan")


Index("ix_traces_started_status", TraceModel.started_at, TraceModel.status)


class SpanModel(Base):
    __tablename__ = "spans"

    id = Column(String, primary_key=True)
    trace_id = Column(String, ForeignKey("traces.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id = Column(String, nullable=True)
    name = Column(String, nullable=False, index=True)
    kind = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, index=True)
    depth = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Float, nullable=False)
    started_at_offset_ms = Column(Float, nullable=False, default=0.0)
    model = Column(String, nullable=True)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=False, default=0.0)
    error_type = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    input_preview = Column(Text, nullable=True)
    output_preview = Column(Text, nullable=True)
    attributes = Column(JSON, nullable=False, default=dict)

    trace = relationship("TraceModel", back_populates="spans")
