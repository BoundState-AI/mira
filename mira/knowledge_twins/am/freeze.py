"""
Module: AM Knowledge Twin -- rule-pack freeze gate (Rev 5 §4.3, PR-0)
Purpose: Convert an oracle GPCM rule pack (output of the shall-extractor
         pipeline) into a frozen, hash-pinned ``am_rulepack/v1`` pack in the
         governed content store, and maintain the corpus manifest including
         the inert placeholder catalog.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032 (Data Validation), SWE-033, NASA-STD-8739.8B
Safety Critical: True

Cross-repo boundary note: GPCM packs are consumed as ARTIFACTS (JSON files
produced by the boundstate_oracle pipeline). No code is imported across the
repo boundary (REPO_BOUNDARIES.md).

Freeze semantics (Rev 5 §4.3):
- ``source_document_hash`` = SHA-256 of the exact source PDF.
- ``source_pack_hash``     = SHA-256 of the GPCM JSON the pack derives from.
- The manifest pins the frozen pack file by SHA-256; the content store
  refuses to serve a pack whose bytes no longer match.
- Packs freeze as UNVERIFIED. Verification against the source document is a
  human act recorded by re-freezing with --verified; until then every
  derived output is labeled provisional.

CLI:
    py -m mira.knowledge_twins.am.freeze <gpcm_pack.json> <source.pdf>
        [--store DIR] [--title TEXT] [--verified]
"""

from __future__ import annotations

__version__ = "0.1.0"
__safety_critical__ = True

import argparse
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from mira.knowledge_twins.am.am_models import DataClassification
from mira.knowledge_twins.am.content_store import (
    MANIFEST_FILE_NAME,
    sha256_of_file,
)
from mira.knowledge_twins.am.rule_pack_models import (
    CorpusManifest,
    FrozenRulePack,
    PackManifestEntry,
    PackRequirement,
    PlaceholderStandard,
    VerificationStatus,
)

LOGGER = logging.getLogger(__name__)

_GPCM_SCHEMA_VERSION = "gpcm_rulepack/v1"

# Rev 5 §4.1: controlled standard families shown only as inert name-only
# placeholders in the Demo Track. Names and titles are public catalog
# information; no clause content exists or may exist for these entries.
DEMO_PLACEHOLDER_CATALOG: tuple[tuple[str, str], ...] = (
    ("SAE-AMS7000", "AMS7000: Laser-PBF Produced Parts (controlled - not loaded)"),
    ("SAE-AMS7001", "AMS7001: AM Metal Powder Feedstock (controlled - not loaded)"),
    ("SAE-AMS7002", "AMS7002: AM Powder Manufacturing (controlled - not loaded)"),
    ("SAE-AMS7003A", "AMS7003A: L-PBF Process Specification (controlled - not loaded)"),
    ("ISO-ASTM-52900", "ISO/ASTM 52900 family: AM terminology and PBF specs (controlled - not loaded)"),
    ("SAE-AS9100", "AS9100: Aerospace Quality Management Systems (controlled - not loaded)"),
    ("NADCAP-AC7110-14", "NADCAP AC7110/14: Laser/EB Metallic Powder-Bed AM audit criteria (controlled - not loaded)"),
)


def _canonical_requirement_id(standard_id: str, raw: dict[str, Any], index: int) -> str:
    """Build ``REQ:<standard>:<TAG>`` from the GPCM row.

    Prefers the source tag (e.g. "AMR 1" -> "AMR-1"); falls back to the GPCM
    row id; finally a 1-based sequence number keyed to extraction order.
    """
    tag = str(raw.get("source_tag") or "").strip()
    if tag:
        return f"REQ:{standard_id}:{re.sub(r'\s+', '-', tag).upper()}"
    row_id = str(raw.get("id") or "").strip()
    if row_id:
        return f"REQ:{standard_id}:{row_id.upper()}"
    return f"REQ:{standard_id}:SEQ-{index + 1}"


def _normalize_requirements(
    gpcm: dict[str, Any], standard_id: str
) -> list[PackRequirement]:
    requirements: list[PackRequirement] = []
    for index, raw in enumerate(gpcm.get("requirements", [])):
        shall_text = str(raw.get("shall_text") or "").strip()
        if not shall_text:
            # A requirement without text cannot be cited; refuse to freeze it
            # silently -- fail the freeze so the ingest gets fixed upstream.
            raise ValueError(
                f"GPCM requirement at index {index} has empty shall_text; "
                "refusing to freeze an uncitable rule."
            )
        requirements.append(
            PackRequirement(
                requirement_id=_canonical_requirement_id(standard_id, raw, index),
                source_tag=str(raw.get("source_tag") or ""),
                section=str(raw.get("section") or ""),
                shall_text=shall_text,
                subject=str(raw.get("subject") or ""),
                requirement=str(raw.get("requirement") or ""),
                page=raw.get("page"),
                justification=str(raw.get("justification") or ""),
                keywords=list(raw.get("keywords") or []),
                applies_to=list(raw.get("applies_to") or []),
            )
        )
    return requirements


def _load_manifest_or_new(store_dir: Path) -> CorpusManifest:
    manifest_path = store_dir / MANIFEST_FILE_NAME
    if manifest_path.is_file():
        return CorpusManifest.model_validate(
            json.loads(manifest_path.read_text(encoding="utf-8"))
        )
    return CorpusManifest(
        generated_at=datetime.now(timezone.utc).isoformat(),
        packs=[],
        placeholders=[],
    )


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> str:
    """Write via unique temp file + atomic replace; return SHA-256 of the
    exact bytes written. Hashing the in-memory bytes (not re-reading the
    file) closes the write/hash TOCTOU window, and the pid-unique temp name
    prevents collisions between concurrent freeze runs."""
    data = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return digest


def seed_placeholders(store_dir: Path) -> CorpusManifest:
    """Install/refresh the inert placeholder catalog in the manifest."""
    store_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest_or_new(store_dir)
    manifest.placeholders = [
        PlaceholderStandard(standard_id=sid, title=title)
        for sid, title in DEMO_PLACEHOLDER_CATALOG
    ]
    manifest.generated_at = datetime.now(timezone.utc).isoformat()
    _write_json_atomic(
        store_dir / MANIFEST_FILE_NAME, manifest.model_dump(mode="json")
    )
    LOGGER.info(
        "[AM freeze] Seeded %d inert placeholders", len(manifest.placeholders)
    )
    return manifest


def freeze_gpcm_pack(
    gpcm_json: Path,
    source_pdf: Path,
    store_dir: Optional[Path] = None,
    *,
    standard_title: str = "",
    verified: bool = False,
) -> Path:
    """Freeze a GPCM rule pack into the content store. Returns pack path."""
    from mira.knowledge_twins.am.content_store import default_store_dir

    store = Path(store_dir) if store_dir else default_store_dir()
    store.mkdir(parents=True, exist_ok=True)

    gpcm = json.loads(gpcm_json.read_text(encoding="utf-8"))
    schema = gpcm.get("schema_version")
    if schema != _GPCM_SCHEMA_VERSION:
        raise ValueError(
            f"{gpcm_json} has schema_version {schema!r}; expected "
            f"{_GPCM_SCHEMA_VERSION!r}. Refusing to freeze an unrecognized "
            "pack format."
        )
    standard_id = str(gpcm.get("standard_id") or "").strip()
    if not standard_id:
        raise ValueError(f"{gpcm_json} is missing standard_id.")
    # GPCM packs have recorded either a bare filename or a full path here;
    # compare by filename. The byte-level pin is source_document_hash below.
    declared_source = Path(str(gpcm.get("source_document") or "").strip()).name
    if declared_source and declared_source != source_pdf.name:
        raise ValueError(
            f"GPCM pack was built from {declared_source!r} but the supplied "
            f"source PDF is {source_pdf.name!r}. The freeze gate pins the "
            "exact source; pass the matching document."
        )

    requirements = _normalize_requirements(gpcm, standard_id)
    declared_total = gpcm.get("total_requirements")
    if declared_total is not None and int(declared_total) != len(requirements):
        raise ValueError(
            f"GPCM pack declares total_requirements={declared_total} but "
            f"contains {len(requirements)}; refusing to freeze an "
            "inconsistent pack."
        )

    pack = FrozenRulePack(
        rule_pack_id=f"am-rulepack-{standard_id.lower()}",
        standard_id=standard_id,
        standard_title=standard_title or standard_id,
        version=str(gpcm.get("version") or "1.0.0"),
        freeze_date=datetime.now(timezone.utc).isoformat(),
        source_document=source_pdf.name,
        source_document_hash=sha256_of_file(source_pdf),
        source_pack=gpcm_json.name,
        source_pack_hash=sha256_of_file(gpcm_json),
        license_access_class="public",
        data_classification=DataClassification.PUBLIC,
        shippable=True,
        verification_status=(
            VerificationStatus.VERIFIED if verified else VerificationStatus.UNVERIFIED
        ),
        total_requirements=len(requirements),
        requirements=requirements,
    )

    file_name = f"am_rulepack_{standard_id.lower().replace('-', '_')}.json"
    pack_path = store / file_name
    pack_sha256 = _write_json_atomic(pack_path, pack.model_dump(mode="json"))

    manifest = _load_manifest_or_new(store)
    entry = PackManifestEntry(
        standard_id=standard_id,
        rule_pack_id=pack.rule_pack_id,
        file_name=file_name,
        sha256=pack_sha256,
        license_access_class=pack.license_access_class,
        data_classification=pack.data_classification,
        shippable=pack.shippable,
        verification_status=pack.verification_status,
    )
    manifest.packs = [e for e in manifest.packs if e.standard_id != standard_id]
    manifest.packs.append(entry)
    manifest.packs.sort(key=lambda e: e.standard_id)
    manifest.generated_at = datetime.now(timezone.utc).isoformat()
    _write_json_atomic(store / MANIFEST_FILE_NAME, manifest.model_dump(mode="json"))

    LOGGER.info(
        "[AM freeze] Froze %s: %d requirements, source sha256=%s..., status=%s",
        standard_id,
        len(requirements),
        pack.source_document_hash[:12],
        pack.verification_status.value,
    )
    return pack_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze a GPCM rule pack into the AM content store."
    )
    parser.add_argument("gpcm_json", type=Path)
    parser.add_argument("source_pdf", type=Path)
    parser.add_argument("--store", type=Path, default=None)
    parser.add_argument("--title", type=str, default="")
    parser.add_argument(
        "--verified",
        action="store_true",
        help="Record human verification against the source document.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    store = args.store
    if store:
        seed_placeholders(store)
    else:
        from mira.knowledge_twins.am.content_store import default_store_dir

        seed_placeholders(default_store_dir())
    pack_path = freeze_gpcm_pack(
        args.gpcm_json,
        args.source_pdf,
        store,
        standard_title=args.title,
        verified=args.verified,
    )
    print(f"Frozen: {pack_path}")


if __name__ == "__main__":
    main()
