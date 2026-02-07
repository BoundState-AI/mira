#!/usr/bin/env python3
"""
Module: Run Search Tests
Purpose: Search Test Runner for BoundState MIRA

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

import sys
import argparse
import subprocess
from pathlib import Path

# Ensure we're in the right directory
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def run_tests(
    unit: bool = False,
    golden: bool = False,
    api: bool = False,
    verbose: bool = False,
    coverage: bool = False,
    fast: bool = False,
) -> int:
    """Run search tests with specified options."""

    # Build pytest command
    cmd = ["python", "-m", "pytest"]

    # Test file selection
    test_files = []
    if unit or (not golden and not api):
        test_files.append("tests/mira/test_hybrid_search.py")
    if golden or (not unit and not api):
        test_files.append("tests/mira/test_golden_queries.py")
    if api or (not unit and not golden):
        test_files.append("tests/api/test_search_endpoint.py")

    cmd.extend(test_files)

    # Options
    if verbose:
        cmd.append("-v")
    else:
        cmd.append("--tb=short")

    if fast:
        cmd.extend(["-x", "--ff"])  # Stop on first failure, run failed first

    if coverage:
        cmd.extend([
            "--cov=mira.search",
            "--cov=mira.api.routers.ui_endpoints",
            "--cov-report=term-missing",
            "--cov-report=html:htmlcov/search",
        ])

    # Skip integration tests by default (require live resources)
    cmd.extend(["-m", "not integration"])

    # Print command
    print(f"Running: {' '.join(cmd)}")
    print("=" * 60)

    # Run tests
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)

    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="Run MIRA search tests")
    parser.add_argument("--unit", action="store_true", help="Run unit tests only")
    parser.add_argument("--golden", action="store_true", help="Run golden query tests only")
    parser.add_argument("--api", action="store_true", help="Run API tests only")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--coverage", action="store_true", help="Generate coverage report")
    parser.add_argument("--fast", action="store_true", help="Fast mode - stop on first failure")

    args = parser.parse_args()

    exit_code = run_tests(
        unit=args.unit,
        golden=args.golden,
        api=args.api,
        verbose=args.verbose,
        coverage=args.coverage,
        fast=args.fast,
    )

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
