#!/usr/bin/env python3
"""
Runtime wiring for the Unified Intelligence Compiler surface inside MIRA.
"""

from __future__ import annotations

import os
from functools import lru_cache

from fastapi import APIRouter

from unified.audit.integrity import AuditIntegrityService
from unified.canonical_store import CanonicalStore
from unified.chat.context import SourceAwareModuleContextManager
from unified.chat.routes import create_router
from unified.compiler import ICCompiler
from unified.evidence.doc_provider import DocumentEvidenceProvider
from unified.pipeline.pipeline import UnifiedPipeline


def _canonical_store_url() -> str:
    return os.getenv("IC_CANONICAL_DB_URL", "sqlite:////tmp/boundstate_ic.db").strip()


@lru_cache(maxsize=1)
def build_ic_router() -> APIRouter:
    store = CanonicalStore(db_url=_canonical_store_url())
    context_manager = SourceAwareModuleContextManager()
    context_manager.register_module(
        "default",
        description="Default IC workspace for document and hybrid reasoning.",
    )
    pipeline = UnifiedPipeline(doc_provider=DocumentEvidenceProvider(store=store))
    compiler = ICCompiler(store=store)
    audit_service = AuditIntegrityService()
    return create_router(
        pipeline=pipeline,
        compiler=compiler,
        context_manager=context_manager,
        audit_service=audit_service,
        store=store,
    )
