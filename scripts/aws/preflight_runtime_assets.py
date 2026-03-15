#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from mira.api.runtime_assets import validate_runtime_assets_for_root


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate required runtime assets against a clean build root.",
    )
    parser.add_argument(
        "--repo-root",
        required=True,
        help="Repository root to validate (working tree or staged clean snapshot).",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    validate_runtime_assets_for_root(repo_root)
    print(f"Runtime asset preflight passed for {repo_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
