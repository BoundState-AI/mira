"""
Module: AM Knowledge Twin -- governed content store (Rev 5 §4.4, §5.3, §8)
Purpose: The ONLY retrieval path for AM rule packs and the placeholder
         catalog. Deny-by-default against an AccessContext; integrity-checked
         against the corpus manifest before any rule is read.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032 (Data Validation), SWE-033, NASA-STD-8739.8B
Safety Critical: True

Enforcement invariants:
- No AccessContext -> no retrieval. None is never treated as "demo mode".
- A pack is served only when (a) it is listed in the corpus manifest,
  (b) its on-disk SHA-256 matches the manifest, (c) its license/access class
  is in the caller's permitted_source_classes, and (d) its data
  classification is within the caller's boundary. Anything else raises.
- Placeholder standards are never retrievable as packs; asking for one
  raises PlaceholderInertError naming the [Rev 5 §4.1] rule.
- Hash mismatch is a SafetyCriticalError (tampering / corruption), logged
  at CRITICAL, never silently re-read.

Demo Track storage note: the store root defaults to ``data/am_content_store``
under the repo root (public 6030/6033 content only) and is overridable via
``AM_CONTENT_STORE_DIR``. Packaging tests assert store content never ships
inside the ``mira`` package itself (Rev 5 §4.4 external-store rule; the
Product Track moves the root outside the repo entirely).
"""

from __future__ import annotations

__version__ = "0.1.0"
__safety_critical__ = True

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from mira.core.models import SafetyCriticalError
from mira.knowledge_twins.am.am_models import AccessContext, DataClassification
from mira.knowledge_twins.am.rule_pack_models import (
    CorpusManifest,
    FrozenRulePack,
    PackManifestEntry,
    PlaceholderStandard,
)

LOGGER = logging.getLogger(__name__)

MANIFEST_FILE_NAME = "manifest.json"
_ENV_STORE_DIR = "AM_CONTENT_STORE_DIR"

# Rev 5 §4.5: a single ordered ladder is NOT an adequate control by itself,
# but "exceeds the boundary" is still well-defined and must reject. The
# demo additionally refuses every non-PUBLIC regime outright because the
# per-regime ClassificationPolicy evaluator is Product Track work.
_CLASSIFICATION_ORDER: tuple[DataClassification, ...] = (
    DataClassification.PUBLIC,
    DataClassification.CUI,
    DataClassification.EAR,
    DataClassification.ITAR,
)
_DEMO_SERVABLE_CLASSIFICATIONS = frozenset({DataClassification.PUBLIC})


def _classification_rank(value: DataClassification) -> int:
    return _CLASSIFICATION_ORDER.index(value)


class AccessDeniedError(PermissionError):
    """Retrieval denied by the deny-by-default access policy."""


class PlaceholderInertError(PermissionError):
    """Attempted retrieval against an inert placeholder standard (Rev 5 §4.1)."""


class UnknownStandardError(KeyError):
    """Requested standard is not in the corpus manifest."""


def default_store_dir() -> Path:
    """Resolve the content-store root: env override, else repo data dir."""
    env_value = os.environ.get(_ENV_STORE_DIR)
    if env_value:
        return Path(env_value)
    # mira/knowledge_twins/am/content_store.py -> repo root is parents[3]
    return Path(__file__).resolve().parents[3] / "data" / "am_content_store"


def sha256_of_file(path: Path) -> str:
    """SHA-256 of a file, streamed (sources may be multi-MB PDFs)."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class AMContentStore:
    """Manifest-governed, access-gated reader for frozen AM rule packs."""

    def __init__(self, store_dir: Optional[Path] = None) -> None:
        self._store_dir = Path(store_dir) if store_dir else default_store_dir()

    @property
    def store_dir(self) -> Path:
        return self._store_dir

    def load_manifest(self) -> CorpusManifest:
        """Load and validate the corpus manifest. Missing/invalid -> raise."""
        manifest_path = self._store_dir / MANIFEST_FILE_NAME
        if not manifest_path.is_file():
            raise FileNotFoundError(
                f"[AM content store] No corpus manifest at {manifest_path}. "
                "Run mira.knowledge_twins.am.freeze to populate the store."
            )
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            return CorpusManifest.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            LOGGER.critical("[AM content store] Corrupt corpus manifest: %s", exc)
            raise SafetyCriticalError(
                f"Corpus manifest at {manifest_path} is corrupt or does not "
                f"match am_corpus_manifest/v1: {exc}"
            ) from exc

    # -- access policy ------------------------------------------------------

    def _require_access(self, access: Optional[AccessContext]) -> AccessContext:
        if access is None:
            raise AccessDeniedError(
                "[AM content store] Retrieval denied: no AccessContext supplied. "
                "Access is deny-by-default (Rev 5 §4.5); absence of a context "
                "is not demo mode."
            )
        return access

    def _check_entry_access(
        self, entry: PackManifestEntry, access: AccessContext
    ) -> None:
        if entry.license_access_class not in access.permitted_source_classes:
            raise AccessDeniedError(
                f"[AM content store] Source class '{entry.license_access_class}' "
                f"for {entry.standard_id} is not in permitted_source_classes "
                f"{access.permitted_source_classes} (tenant={access.tenant_id})."
            )
        if _classification_rank(entry.data_classification) > _classification_rank(
            access.max_data_classification
        ):
            raise AccessDeniedError(
                f"[AM content store] {entry.standard_id} classification "
                f"{entry.data_classification.value} exceeds boundary "
                f"{access.max_data_classification.value} -- rejected, never "
                "silently downgraded (Rev 5 §4.5)."
            )
        if entry.data_classification not in _DEMO_SERVABLE_CLASSIFICATIONS:
            raise AccessDeniedError(
                f"[AM content store] {entry.standard_id} is classified "
                f"{entry.data_classification.value}; this store serves only "
                "PUBLIC content until a regime-aware ClassificationPolicy "
                "evaluator exists (Rev 5 §4.5, Product Track)."
            )
        if not entry.shippable:
            raise AccessDeniedError(
                f"[AM content store] {entry.standard_id} is marked "
                "non-shippable and cannot be served (Rev 5 §4.4)."
            )

    # -- retrieval ----------------------------------------------------------

    def available_standards(self, access: Optional[AccessContext]) -> list[str]:
        """Standards the caller is allowed to see. Deny-by-default."""
        ctx = self._require_access(access)
        manifest = self.load_manifest()
        allowed: list[str] = []
        for entry in manifest.packs:
            try:
                self._check_entry_access(entry, ctx)
            except AccessDeniedError:
                continue
            allowed.append(entry.standard_id)
        return allowed

    def get_placeholders(
        self, access: Optional[AccessContext]
    ) -> list[PlaceholderStandard]:
        """Name-only placeholder catalog (Rev 5 §4.1). Access still required."""
        self._require_access(access)
        return list(self.load_manifest().placeholders)

    def load_pack(
        self, standard_id: str, access: Optional[AccessContext]
    ) -> FrozenRulePack:
        """Load a frozen rule pack after access + integrity checks."""
        ctx = self._require_access(access)
        manifest = self.load_manifest()

        for placeholder in manifest.placeholders:
            if placeholder.standard_id == standard_id:
                raise PlaceholderInertError(
                    f"[AM content store] {standard_id} is an inert name-only "
                    "placeholder: no clauses, excerpts, mappings, or retrieval "
                    "exist for it in the Demo Track (Rev 5 §4.1)."
                )

        entry = next(
            (e for e in manifest.packs if e.standard_id == standard_id), None
        )
        if entry is None:
            raise UnknownStandardError(
                f"[AM content store] {standard_id} is not in the corpus manifest."
            )
        self._check_entry_access(entry, ctx)

        pack_path = self._store_dir / entry.file_name
        if not pack_path.is_file():
            LOGGER.critical(
                "[AM content store] Manifest lists %s but %s is missing",
                standard_id,
                pack_path,
            )
            raise SafetyCriticalError(
                f"Rule pack file {pack_path} listed in the manifest is missing."
            )

        actual_hash = sha256_of_file(pack_path)
        if actual_hash != entry.sha256:
            LOGGER.critical(
                "[AM content store] HASH MISMATCH for %s: manifest=%s actual=%s",
                standard_id,
                entry.sha256,
                actual_hash,
            )
            raise SafetyCriticalError(
                f"Rule pack {entry.file_name} fails integrity check: manifest "
                f"sha256 {entry.sha256} != actual {actual_hash}. The frozen "
                "pack has been modified outside the freeze gate (Rev 5 §4.3)."
            )

        try:
            payload = json.loads(pack_path.read_text(encoding="utf-8"))
            pack = FrozenRulePack.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            LOGGER.critical(
                "[AM content store] Pack %s passes hash but fails schema: %s",
                standard_id,
                exc,
            )
            raise SafetyCriticalError(
                f"Rule pack {entry.file_name} does not conform to "
                f"am_rulepack/v1: {exc}"
            ) from exc

        if pack.standard_id != standard_id:
            raise SafetyCriticalError(
                f"Rule pack {entry.file_name} declares standard_id "
                f"{pack.standard_id!r} but the manifest entry is for "
                f"{standard_id!r}."
            )
        return pack
