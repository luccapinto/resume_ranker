from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, func
from api.database import Base

class ProfileModel(Base):
    __tablename__ = "profiles"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, nullable=False)  # 'candidate' or 'job'
    file_name = Column(String, nullable=True)
    raw_text = Column(Text, nullable=False)
    redacted_text = Column(Text, nullable=False)
    redaction_map = Column(JSON, nullable=False, default=dict)
    extracted_profile = Column(JSON, nullable=False)  # Store the JSON matching CandidateProfile/JobRequirements
    created_at = Column(DateTime, nullable=False, server_default=func.now())

class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    query_type = Column(String, nullable=False)  # 'candidate' or 'job'
    query_id = Column(Integer, nullable=False)
    embedding_model = Column(String, nullable=False)
    reranker_model = Column(String, nullable=False)
    execution_time_ms = Column(Integer, nullable=False)
    bias_audit_passed = Column(Integer, nullable=False)  # 1 for True, 0 for False
    bias_audit_results = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
