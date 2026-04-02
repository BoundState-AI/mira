from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mira.api.runtime_assets import _sha256_file, iter_required_runtime_assets, validate_required_runtime_assets


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_required_runtime_assets_validate():
    assets = validate_required_runtime_assets()
    assert assets
    assert len(assets) >= 15


def test_guidance_runtime_assets_are_present():
    asset_ids = {asset.asset_id for asset in iter_required_runtime_assets()}
    assert "guidance_oca_pack" in asset_ids
    assert "guidance_mua_pack" in asset_ids
    assert "guidance_miul_pack" in asset_ids
    assert "guidance_h2_pack" in asset_ids
    assert "guidance_galvanic_pack" in asset_ids
    assert "guidance_fracture_pack" in asset_ids
    assert "guidance_mp_plan_pack" in asset_ids
    assert "guidance_authority_registry" in asset_ids


def test_required_runtime_assets_are_tracked_in_git():
    repo_check = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if repo_check.returncode != 0:
        pytest.skip("git tracking check requires a git checkout")

    for asset in iter_required_runtime_assets():
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "--error-unmatch", asset.relative_path],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"{asset.relative_path} must be tracked in git for clean-checkout deploys. "
            f"git output: {result.stderr.strip() or result.stdout.strip()}"
        )


def test_runtime_asset_hashes_ignore_text_line_endings():
    class StubPath:
        def __init__(self, raw: bytes):
            self.suffix = ".json"
            self._raw = raw

        def read_bytes(self) -> bytes:
            return self._raw

    lf_path = StubPath(b'{\n  "status": "ok"\n}\n')
    crlf_path = StubPath(b'{\r\n  "status": "ok"\r\n}\r\n')

    assert _sha256_file(lf_path) == _sha256_file(crlf_path)
