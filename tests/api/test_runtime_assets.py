from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mira.api.runtime_assets import iter_required_runtime_assets, validate_required_runtime_assets


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_required_runtime_assets_validate():
    assets = validate_required_runtime_assets()
    assert assets
    assert len(assets) >= 7


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
