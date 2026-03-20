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
        asset_id="mp_plan_6016c_catalog",
        relative_path="mira/compliance/data/mprs_6016c.yaml",
        domain="mp_plan",
        sha256="8e7212c5ef2c4a45fc4cd957968acc6da1d664593cb89ba6cd8d9d389a9db766",
        required_by=("mira.api.routers.compliance", "mira.mp_plan.engines.applicability_codex"),
        notes="NASA-STD-6016C MPR catalog used by compliance and MP Plan codex.",
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
