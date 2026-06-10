"""
Module: AM Knowledge Twin -- frozen rule pack contracts (Rev 5 §4.1-§4.3)
Purpose: Typed models for versioned, hash-frozen standards rule packs and the
         inert placeholder catalog. A pack that fails these models fails loud.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032 (Data Validation), SWE-033, NASA-STD-8739.8B
Safety Critical: True

Design invariants:
- Every requirement carries its source location (section, page, source tag)
  back to the frozen source document; ``source_document_hash`` pins the exact
  PDF the pack was derived from (Rev 5 §4.3 rule-freeze gate).
- ``PlaceholderStandard`` is inert BY CONSTRUCTION: with extra="forbid" and
  no content-bearing fields, clause text/excerpts/mappings cannot even be
  represented on a placeholder (Rev 5 §4.1, Golden Test 16).
- Packs are UNVERIFIED until a human verifies them against the source; all
  derived output must be labeled provisional until then (Rev 5 §4.3).
"""

from __future__ import annotations

__version__ = "0.1.0"
__safety_critical__ = True

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from mira.knowledge_twins.am.am_models import DataClassification


class VerificationStatus(str, Enum):
    """Rule-pack verification state (Rev 5 §4.3)."""

    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class ClauseRef(BaseModel):
    """Pointer to a clause in a frozen source document."""

    model_config = ConfigDict(extra="forbid")

    standard_id: str
    section: Optional[str] = None
    requirement_tag: Optional[str] = None
    page: Optional[int] = None


class PackRequirement(BaseModel):
    """One binding requirement extracted from a standard.

    ``requirement_id`` is the canonical namespaced id used by crosswalk
    nodes: ``REQ:<standard_id>:<tag-or-sequence>``.
    """

    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    source_tag: str = ""
    section: str = ""
    shall_text: str
    subject: str = ""
    requirement: str = ""
    page: Optional[int] = None
    justification: str = ""
    keywords: list[str] = Field(default_factory=list)
    applies_to: list[str] = Field(default_factory=list)


class FrozenRulePack(BaseModel):
    """A versioned, hash-pinned rule pack (Rev 5 §4.3).

    The engine is deterministic against a frozen pack version; outputs cite
    ``rule_pack_id`` + requirement ids, and the pack cites the source PDF by
    SHA-256. Tampering with the pack file is detected by the content store
    against the corpus manifest before any rule is read.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["am_rulepack/v1"] = "am_rulepack/v1"
    rule_pack_id: str
    standard_id: str
    standard_title: str
    version: str
    freeze_date: str
    source_document: str
    source_document_hash: str
    source_pack: str
    source_pack_hash: str
    license_access_class: str
    data_classification: DataClassification
    shippable: bool
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    total_requirements: int
    requirements: list[PackRequirement]


class PlaceholderStandard(BaseModel):
    """Name-only placeholder for a controlled/licensed standard (Rev 5 §4.1).

    Inert by construction: no clause, excerpt, mapping, or retrieval fields
    exist on this model, and extra="forbid" rejects any attempt to add them.
    """

    model_config = ConfigDict(extra="forbid")

    standard_id: str
    title: str
    loaded: Literal[False] = False
    note: str = "not licensed / not loaded"


class PackManifestEntry(BaseModel):
    """Corpus-manifest row pinning a pack file by hash."""

    model_config = ConfigDict(extra="forbid")

    standard_id: str
    rule_pack_id: str
    file_name: str
    sha256: str
    license_access_class: str
    data_classification: DataClassification
    shippable: bool
    verification_status: VerificationStatus


class CorpusManifest(BaseModel):
    """Manifest of everything the content store may serve (Rev 5 §4.4, §5.3).

    Anything not listed here does not exist as far as retrieval is concerned;
    deny-by-default applies on top of this allowlist.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["am_corpus_manifest/v1"] = "am_corpus_manifest/v1"
    generated_at: str
    packs: list[PackManifestEntry] = Field(default_factory=list)
    placeholders: list[PlaceholderStandard] = Field(default_factory=list)
