"""Shared, expensive singletons.

The PII redactor loads a spaCy model and the normalizer loads the ESCO taxonomy;
both are process-wide and thread-safe for read access, so they are built once
here and imported wherever needed. Keeping them out of `main` also avoids a
circular import between the routers and the copilot.
"""

from __future__ import annotations

import threading
from typing import Optional

from api.ats import IngestionService
from api.extractor import OpenRouterExtractor
from api.normalizer import SkillNormalizer
from api.redactor import PIIRedactor

# Reentrant: get_ingestion() acquires the lock and then calls the other getters.
_lock = threading.RLock()
_redactor: Optional[PIIRedactor] = None
_normalizer: Optional[SkillNormalizer] = None
_extractor: Optional[OpenRouterExtractor] = None
_ingestion: Optional[IngestionService] = None


def get_redactor() -> PIIRedactor:
    global _redactor
    if _redactor is None:
        with _lock:
            if _redactor is None:
                _redactor = PIIRedactor()
    return _redactor


def get_normalizer() -> SkillNormalizer:
    global _normalizer
    if _normalizer is None:
        with _lock:
            if _normalizer is None:
                _normalizer = SkillNormalizer()
    return _normalizer


def get_extractor() -> OpenRouterExtractor:
    global _extractor
    if _extractor is None:
        with _lock:
            if _extractor is None:
                _extractor = OpenRouterExtractor()
    return _extractor


def get_ingestion() -> IngestionService:
    global _ingestion
    if _ingestion is None:
        with _lock:
            if _ingestion is None:
                _ingestion = IngestionService(get_redactor(), get_extractor(), get_normalizer())
    return _ingestion


def warmup() -> None:
    """Pay the model-loading cost at startup instead of on the first request."""
    get_redactor()
    get_normalizer()
    get_extractor()
