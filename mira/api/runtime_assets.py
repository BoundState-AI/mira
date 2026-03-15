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
        sha256="1bbc6c619f47caa87dc5d67573c3b01a4b3bdf8b55ae8a67561cf6b9bf10523c",
        required_by=("mira.api.routers.tocr", "sentinel.tocr.engine.remediation_advisor"),
        notes="Plain-English guidance pack for TOCR findings and remediation.",
    ),
    RuntimeAsset(
        asset_id="tocr_scan_rules",
        relative_path="sentinel/tocr/data/scan_rules.json",
        domain="tocr",
        sha256="79ef1c35c48293effe32f8e146d66f46cffd62f60173d96dedc0e9992dcc9f2e",
        required_by=("sentinel.tocr.engine.conductor",),
        notes="Standalone scan rules for TOCR single-document analysis.",
    ),
    RuntimeAsset(
        asset_id="tocr_rules",
        relative_path="sentinel/tocr/data/tocr_rules.json",
        domain="tocr",
        sha256="583d2b8188d364600e389e54091f2bcd8ea394eb34885b9622b84032abe313ab",
        required_by=("sentinel.tocr.engine.conductor",),
        notes="Revision-review rule pack for TOCR.",
    ),
    RuntimeAsset(
        asset_id="tocr_qms_triggers",
        relative_path="sentinel/tocr/data/qms_triggers.json",
        domain="tocr",
        sha256="a6e3b1afac55db09c49b16a51518601cca93bb909b2249cb750117cf7a265cad",
        required_by=("sentinel.tocr.engine.conductor",),
        notes="QMS trigger catalog used during TOCR review generation.",
    ),
    RuntimeAsset(
        asset_id="h2_evidence_corpus",
        relative_path="mira/data/h2_evidence_merged.json",
        domain="h2",
        sha256="69c4a320d7b47b71f4c808d494e3c777c09d8993b46c6fe04f12b5dbee78f87a",
        required_by=("mira.knowledge_twins.h2.engine_simple", "mira.h2.ft_temp"),
        notes="Structured hydrogen embrittlement evidence corpus.",
    ),
    RuntimeAsset(
        asset_id="h2_guidance_pack",
        relative_path="mira/h2/data/guidance.json",
        domain="h2",
        sha256="60c71b6300c7606e6d8c5e6f79d323b17c7590f2fd76bca60dd420310a4ce770",
        required_by=("mira.api.routers.h2",),
        notes="Backend-packaged H2 guidance payload served by the H2 router.",
    ),
    RuntimeAsset(
        asset_id="mp_plan_6016c_catalog",
        relative_path="mira/compliance/data/mprs_6016c.yaml",
        domain="mp_plan",
        sha256="b077cd8ae28eaa02c618a3f3f9811dad5d1deec37c82e404645b71c1ccdbb53c",
        required_by=("mira.api.routers.compliance", "mira.mp_plan.engines.applicability_codex"),
        notes="NASA-STD-6016C MPR catalog used by compliance and MP Plan codex.",
    ),
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
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
