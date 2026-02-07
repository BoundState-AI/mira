#!/usr/bin/env python3
"""
Module: Security
Purpose: ATHENA Security Models.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Role(str, Enum):
    """User roles."""
    ADMIN = "admin"          # Full access
    OPERATOR = "operator"    # Process batches, view results
    REVIEWER = "reviewer"    # Review extractions, approve entities
    VIEWER = "viewer"        # Read-only
    AUDITOR = "auditor"      # Audit logs only


class Permission(str, Enum):
    """System permissions."""
    BATCH_CREATE = "batch:create"
    BATCH_PROCESS = "batch:process"
    DOCUMENT_VIEW = "document:view"
    DOCUMENT_EXPORT = "document:export"
    ENTITY_APPROVE = "entity:approve"
    ENTITY_REJECT = "entity:reject"
    CONFIG_MODIFY = "config:modify"
    AUDIT_VIEW = "audit:view"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: set(Permission),
    Role.OPERATOR: {
        Permission.BATCH_CREATE, Permission.BATCH_PROCESS,
        Permission.DOCUMENT_VIEW, Permission.DOCUMENT_EXPORT
    },
    Role.REVIEWER: {
        Permission.DOCUMENT_VIEW, Permission.ENTITY_APPROVE,
        Permission.ENTITY_REJECT
    },
    Role.VIEWER: {Permission.DOCUMENT_VIEW},
    Role.AUDITOR: {Permission.AUDIT_VIEW}
}


class AuditEvent(BaseModel):
    """Immutable audit log entry.

    Audit logs are:
    - Written to append-only table (no UPDATE/DELETE)
    - Retained per compliance requirements (7 years default)
    """
    event_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    tenant_id: str
    user_id: str
    action: str                      # e.g., "document.extract"
    resource_type: str               # e.g., "document"
    resource_id: str
    details: dict[str, Any] = Field(default_factory=dict)
    ip_address: str
    user_agent: str
    outcome: str                     # "success" | "failure" | "denied"
