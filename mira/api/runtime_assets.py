#!/usr/bin/env python3
"""
Required runtime asset manifest and validation for the API surface.

These assets must be present in a clean checkout and must match the expected
tracked content, or the app should fail at startup instead of degrading
silently at runtime.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEXT_RUNTIME_ASSET_SUFFIXES = {".json", ".yaml", ".yml", ".txt", ".md", ".csv"}


@dataclass(frozen=True)
class RuntimeAsset:
    asset_id: str
    relative_path: str
    domain: str
    sha256: str
    required_by: tuple[str, ...]
    notes: str = ""

    @property
    def path(self) -> Path:
        return _REPO_ROOT / self.relative_path

    def resolve_path(self, repo_root: Path | None = None) -> Path:
        return (repo_root or _REPO_ROOT) / self.relative_path


REQUIRED_RUNTIME_ASSETS: tuple[RuntimeAsset, ...] = (
    RuntimeAsset(
        asset_id="tocr_guidance",
        relative_path="sentinel/tocr/data/guidance.json",
        domain="tocr",
        sha256="703215ac0750a6f98b68998a5c4908549887b4d2d8c5a5f6c131fa5334f26dc3",
        required_by=("mira.api.routers.tocr", "sentinel.tocr.engine.remediation_advisor"),
        notes="Plain-English guidance pack for TOCR findings and remediation.",
    ),
    RuntimeAsset(
        asset_id="tocr_scan_rules",
        relative_path="sentinel/tocr/data/scan_rules.json",
        domain="tocr",
        sha256="d2300e7782468b86155d62f087c00c65f98eb459f64d646822742e75e3cc50f7",
        required_by=("sentinel.tocr.engine.conductor",),
        notes="Standalone scan rules for TOCR single-document analysis.",
    ),
    RuntimeAsset(
        asset_id="tocr_rules",
        relative_path="sentinel/tocr/data/tocr_rules.json",
        domain="tocr",
        sha256="fc9137fe46ceb0f9a85624e438fd36b4656a63acf57cca9be2f75e0fcce83f46",
        required_by=("sentinel.tocr.engine.conductor",),
        notes="Revision-review rule pack for TOCR.",
    ),
    RuntimeAsset(
        asset_id="tocr_qms_triggers",
        relative_path="sentinel/tocr/data/qms_triggers.json",
        domain="tocr",
        sha256="3e0e9cac145491876780ed643defe088f7e296605677d1eab0eaeee689b24a63",
        required_by=("sentinel.tocr.engine.conductor",),
        notes="QMS trigger catalog used during TOCR review generation.",
    ),
    RuntimeAsset(
        asset_id="h2_evidence_corpus",
        relative_path="mira/data/h2_evidence_merged.json",
        domain="h2",
        sha256="c3dea4824bdc505e109361d82760c461ae9368a0f82ad38fdd5db55b3f774e7d",
        required_by=("mira.knowledge_twins.h2.engine_simple", "mira.h2.ft_temp"),
        notes="Structured hydrogen embrittlement evidence corpus.",
    ),
    RuntimeAsset(
        asset_id="h2_guidance_pack",
        relative_path="mira/h2/data/guidance.json",
        domain="h2",
        sha256="216a6b784e12d049a0e7d42fd700a2d6f3dfb4b6829dc2d0d13ec0464bbf1d8b",
        required_by=("mira.api.routers.h2",),
        notes="Backend-packaged H2 guidance payload served by the H2 router.",
    ),
    RuntimeAsset(
        asset_id="o2_bok_faiss_index",
        relative_path="mira/databases/o2_bok/o2_bok_faiss.index",
        domain="o2",
        sha256="c89468fb273081b3ed0b32d1f29f6440a9a18787f323a85247bc1d0ecb77bd89",
        required_by=("mira.o2.engine", "mira.api.routers.o2"),
        notes="Dedicated O2 BOK semantic index used by O2 standards search.",
    ),
    RuntimeAsset(
        asset_id="o2_bok_faiss_metadata",
        relative_path="mira/databases/o2_bok/o2_bok_faiss_metadata.json",
        domain="o2",
        sha256="f21053d6f5055c18a7e9a3e8d5fd52acab69889c303b07bb9fd3aa4ce8089383",
        required_by=("mira.o2.engine", "mira.api.routers.o2"),
        notes="Chunk metadata for the dedicated O2 BOK semantic index.",
    ),
    RuntimeAsset(
        asset_id="o2_bok_text_lookup",
        relative_path="mira/databases/o2_bok/o2_bok_text_lookup.json",
        domain="o2",
        sha256="bc91031165935f47745aa23cec8bc12506f32a12fd22cbe55751ba20b22db188",
        required_by=("mira.o2.engine", "mira.api.routers.o2"),
        notes="Chunk text lookup for the dedicated O2 BOK semantic index.",
    ),
    RuntimeAsset(
        asset_id="mp_plan_6016c_catalog",
        relative_path="mira/compliance/data/mprs_6016c.yaml",
        domain="mp_plan",
        sha256="8e7212c5ef2c4a45fc4cd957968acc6da1d664593cb89ba6cd8d9d389a9db766",
        required_by=("mira.api.routers.compliance", "mira.mp_plan.engines.applicability_codex"),
        notes="NASA-STD-6016C MPR catalog used by compliance and MP Plan codex.",
    ),
    RuntimeAsset(
        asset_id="guidance_oca_pack",
        relative_path="frontend/src/data/oca-guidance-pack.json",
        domain="guidance",
        sha256="daf80ed6f28e6cdf1294648f321b82713ad2fd03768dceda3d6bbd31e94628c5",
        required_by=("mira.api.routers.guidance",),
        notes="Universal Guidance Schema pack for OCA frontend surfaces.",
    ),
    RuntimeAsset(
        asset_id="guidance_mua_pack",
        relative_path="frontend/src/data/mua-guidance-pack.json",
        domain="guidance",
        sha256="c685dcb1f97e47071f7a25806562feb5e67b9357a51e0d91c5f4015215c8c208",
        required_by=("mira.api.routers.guidance",),
        notes="Universal Guidance Schema pack for MUA frontend surfaces.",
    ),
    RuntimeAsset(
        asset_id="guidance_miul_pack",
        relative_path="frontend/src/data/miul-guidance-pack.json",
        domain="guidance",
        sha256="2e6642d262670b2ea9d8a50297eb09cb9df2d2f3f03bdbfad1ad23ace255e1fb",
        required_by=("mira.api.routers.guidance",),
        notes="Universal Guidance Schema pack for MIUL frontend surfaces.",
    ),
    RuntimeAsset(
        asset_id="guidance_h2_pack",
        relative_path="frontend/src/data/h2-guidance-pack.json",
        domain="guidance",
        sha256="6158dc667682ba6fb2fb8d5d5b98a4e1b6b945772eee766355e8d31e3affeb24",
        required_by=("mira.api.routers.guidance",),
        notes="Universal Guidance Schema pack for H2 frontend surfaces.",
    ),
    RuntimeAsset(
        asset_id="guidance_galvanic_pack",
        relative_path="frontend/src/data/galvanic-guidance-pack.json",
        domain="guidance",
        sha256="5dc6429d4937ae0d4a2f2df08a8e99e1a440e7036da996ef8bd5593963050b09",
        required_by=("mira.api.routers.guidance",),
        notes="Universal Guidance Schema pack for galvanic frontend surfaces.",
    ),
    RuntimeAsset(
        asset_id="guidance_fracture_pack",
        relative_path="frontend/src/data/fracture-guidance-pack.json",
        domain="guidance",
        sha256="bcfe1076beefec4c9ceb0b8b96f5fc7e80669121b05c39da019a3b3cbe4973ba",
        required_by=("mira.api.routers.guidance",),
        notes="Universal Guidance Schema pack for fracture frontend surfaces.",
    ),
    RuntimeAsset(
        asset_id="guidance_mp_plan_pack",
        relative_path="frontend/src/data/mp-plan-guidance-pack.json",
        domain="guidance",
        sha256="d96ce1c92088cfdab13089d49af0abd758ad4af2636d0763592b652ecbec7d01",
        required_by=("mira.api.routers.guidance",),
        notes="Universal Guidance Schema pack for MP Plan frontend surfaces.",
    ),
    RuntimeAsset(
        asset_id="guidance_authority_registry",
        relative_path="frontend/src/data/authority-registry.json",
        domain="guidance",
        sha256="8520eea63fb9a439744819aa4413bff499e8d5337b6812271d4ce9282bd8387b",
        required_by=("mira.api.routers.guidance",),
        notes="Authority registry served alongside Universal Guidance Schema packs.",
    ),
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    raw = path.read_bytes()

    # Runtime assets are tracked text payloads. Normalize line endings so
    # clean git snapshots (LF) and CRLF working trees hash identically.
    if path.suffix.lower() in _TEXT_RUNTIME_ASSET_SUFFIXES:
        raw = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

    digest.update(raw)
    return digest.hexdigest()


def iter_required_runtime_assets() -> tuple[RuntimeAsset, ...]:
    return REQUIRED_RUNTIME_ASSETS


def _validate_assets(repo_root: Path) -> tuple[RuntimeAsset, ...]:
    missing: list[RuntimeAsset] = []
    mismatched: list[tuple[RuntimeAsset, str]] = []

    for asset in REQUIRED_RUNTIME_ASSETS:
        asset_path = asset.resolve_path(repo_root)
        if not asset_path.exists():
            missing.append(asset)
            continue

        actual_sha = _sha256_file(asset_path)
        if actual_sha != asset.sha256:
            mismatched.append((asset, actual_sha))

    if missing or mismatched:
        lines = ["Required runtime asset validation failed."]
        if missing:
            lines.append("Missing assets:")
            lines.extend(f"- {asset.asset_id}: {asset.relative_path}" for asset in missing)
        if mismatched:
            lines.append("Checksum mismatches:")
            lines.extend(
                (
                    f"- {asset.asset_id}: expected {asset.sha256}, "
                    f"got {actual_sha} ({asset.relative_path})"
                )
                for asset, actual_sha in mismatched
            )
        raise RuntimeError("\n".join(lines))

    return REQUIRED_RUNTIME_ASSETS


@lru_cache(maxsize=1)
def validate_required_runtime_assets() -> tuple[RuntimeAsset, ...]:
    return _validate_assets(_REPO_ROOT)


def validate_runtime_assets_for_root(repo_root: Path) -> tuple[RuntimeAsset, ...]:
    return _validate_assets(repo_root)
