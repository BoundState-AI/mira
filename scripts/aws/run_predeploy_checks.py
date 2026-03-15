#!/usr/bin/env python3
"""
Select and execute changed-path-aware predeploy checks for the GovCloud runtime.

This script is intentionally conservative: it always runs the runtime
foundation tests, then adds module-specific pytest targets based on the files
being shipped. If frontend sources changed, it also runs a local Vite build
against the deploy snapshot.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
BASELINE_PYTEST_TARGETS = (
    "tests/api/test_runtime_assets.py",
    "tests/api/test_app_entrypoint_parity.py",
)


@dataclass(frozen=True)
class CheckRule:
    name: str
    prefixes: tuple[str, ...]
    pytest_targets: tuple[str, ...] = ()
    frontend_build: bool = False


RULES: tuple[CheckRule, ...] = (
    CheckRule(
        name="tocr",
        prefixes=("sentinel/tocr/", "mira/api/routers/tocr.py"),
        pytest_targets=("tests/api/test_tocr_endpoint.py", "tests/sentinel/tocr"),
    ),
    CheckRule(
        name="forge",
        prefixes=("mira/forge/", "mira/forge_claude/", "mira/api/routers/forge.py"),
        pytest_targets=("tests/api/test_forge_endpoint.py", "tests/mira/forge"),
    ),
    CheckRule(
        name="h2",
        prefixes=("mira/h2/", "mira/knowledge_twins/h2/", "mira/api/routers/h2.py", "mira/data/h2_"),
        pytest_targets=(
            "tests/mira/test_h2_compatibility_core.py",
            "tests/mira/test_h2_knowledge_twin_automated.py",
        ),
    ),
    CheckRule(
        name="galvanic",
        prefixes=("mira/galvanic/", "mira/api/routers/galvanic.py"),
        pytest_targets=("tests/api/test_galvanic_endpoint.py", "tests/mira/test_galvanic_engine.py"),
    ),
    CheckRule(
        name="fracture",
        prefixes=("mira/fracture/", "mira/api/routers/fracture.py"),
        pytest_targets=(
            "tests/api/test_fracture_endpoint.py",
            "tests/mira/test_fracture_engine.py",
            "tests/mira/test_fracture_golden_cases.py",
        ),
    ),
    CheckRule(
        name="oca",
        prefixes=("mira/oca/", "mira/api/routers/oca.py", "mira/api/routers/oca_systems.py"),
        pytest_targets=(
            "tests/api/test_oca_endpoints.py",
            "tests/api/test_oca_system_endpoints.py",
            "tests/mira/test_oca_engine.py",
            "tests/mira/test_oca_engine_compat.py",
            "tests/mira/test_oca_system_engine.py",
        ),
    ),
    CheckRule(
        name="mp_plan",
        prefixes=("mira/mp_plan/", "mira/compliance/", "mira/api/routers/mp_plan.py", "mira/api/routers/mp_plan_v2_codex.py"),
        pytest_targets=(
            "tests/mira/mp_plan/test_api_v2_codex.py",
            "tests/mira/mp_plan/test_codex_golden_cases.py",
            "tests/mira/mp_plan/test_codex_tier3_golden.py",
        ),
    ),
    CheckRule(
        name="mua",
        prefixes=("mira/mua/", "mira/api/routers/mua.py", "mira/api/routers/mua_v6.py", "mira/api/routers/mua_v7.py", "mira/api/routers/mua_v10.py", "mira/api/routers/matchmaker.py"),
        pytest_targets=(
            "tests/api/test_mua_endpoint.py",
            "tests/api/test_mua_v6_api.py",
            "tests/api/test_mua_v10_api.py",
            "tests/mira/mua/test_mua_classifier.py",
            "tests/mira/mua/test_docx_renderer.py",
        ),
    ),
    CheckRule(
        name="miul",
        prefixes=("mira/miul/", "mira/api/routers/miul.py"),
        pytest_targets=("tests/api/test_miul_endpoint.py", "tests/mira/test_miul_v2_miul.py", "tests/mira/test_miul_workflow.py"),
    ),
    CheckRule(
        name="search",
        prefixes=("mira/search/", "mira/api/routers/search.py", "mira/api/routers/hybrid_query.py"),
        pytest_targets=(
            "tests/api/test_search_api.py",
            "tests/api/test_search_endpoint.py",
            "tests/mira/test_hybrid_search.py",
            "tests/mira/test_hybrid_search_v6.py",
        ),
    ),
    CheckRule(
        name="frontend",
        prefixes=("frontend/",),
        frontend_build=True,
    ),
)


def _run_git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _first_parent(repo_root: Path, deploy_ref: str) -> str:
    parents = _run_git(repo_root, "rev-list", "--parents", "-n", "1", deploy_ref).split()
    return parents[1] if len(parents) > 1 else EMPTY_TREE


def _dirty_changed_paths(repo_root: Path) -> list[str]:
    tracked = _run_git(repo_root, "diff", "--name-only", "HEAD").splitlines()
    staged = _run_git(repo_root, "diff", "--name-only", "--cached").splitlines()
    untracked = _run_git(repo_root, "ls-files", "--others", "--exclude-standard").splitlines()
    return sorted({path for path in tracked + staged + untracked if path})


def _changed_paths(repo_root: Path, deploy_ref: str, *, dirty_worktree: bool) -> tuple[str, list[str]]:
    if dirty_worktree:
        return "WORKTREE", _dirty_changed_paths(repo_root)
    diff_base = _first_parent(repo_root, deploy_ref)
    changed = _run_git(repo_root, "diff", "--name-only", diff_base, deploy_ref).splitlines()
    return diff_base, [path for path in changed if path]


def _matches_rule(path: str, rule: CheckRule) -> bool:
    return any(path.startswith(prefix) for prefix in rule.prefixes)


def _select_plan(changed_paths: list[str]) -> tuple[list[str], bool, list[str]]:
    pytest_targets = list(BASELINE_PYTEST_TARGETS)
    frontend_build = False
    matched_rules: list[str] = []

    for rule in RULES:
        if any(_matches_rule(path, rule) for path in changed_paths):
            matched_rules.append(rule.name)
            for target in rule.pytest_targets:
                if target not in pytest_targets:
                    pytest_targets.append(target)
            frontend_build = frontend_build or rule.frontend_build

    return pytest_targets, frontend_build, matched_rules


def _candidate_test_pythons(repo_root: Path) -> list[Path]:
    candidates = [
        Path(os.environ["PREDEPLOY_TEST_PYTHON"]) if os.environ.get("PREDEPLOY_TEST_PYTHON") else None,
        Path(sys.executable),
        Path("/tmp/mira-mpplan-venv/bin/python3"),
        repo_root / ".venv" / "bin" / "python",
        repo_root.parent / ".venv" / "bin" / "python",
        repo_root.parent.parent / ".venv" / "bin" / "python",
        repo_root / ".venv" / "Scripts" / "python.exe",
        repo_root.parent / ".venv" / "Scripts" / "python.exe",
        repo_root.parent.parent / ".venv" / "Scripts" / "python.exe",
    ]
    return [candidate for candidate in candidates if candidate is not None]


def _resolve_pytest_python(repo_root: Path) -> Path:
    for candidate in _candidate_test_pythons(repo_root):
        if not candidate.exists():
            continue
        result = subprocess.run(
            [str(candidate), "-m", "pytest", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return candidate
    raise RuntimeError(
        "Unable to find a Python interpreter with pytest installed. "
        "Set PREDEPLOY_TEST_PYTHON to a suitable interpreter."
    )


def _ensure_frontend_node_modules(repo_root: Path, build_root: Path) -> None:
    source = repo_root / "frontend" / "node_modules"
    target = build_root / "frontend" / "node_modules"
    if target.exists():
        return
    if not source.exists():
        raise RuntimeError(
            "Frontend changes detected but frontend/node_modules is missing. "
            "Run npm install in frontend or set up the dependency cache first."
        )
    target.symlink_to(source, target_is_directory=True)


def _run_pytest(pytest_python: Path, build_root: Path, targets: list[str]) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(build_root)
    cmd = [str(pytest_python), "-m", "pytest", "-s", "-q", *targets]
    result = subprocess.run(
        cmd,
        cwd=build_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError("Predeploy pytest slice failed.")
    return {
        "cmd": cmd,
        "returncode": result.returncode,
        "stdout": stdout,
        "stderr": stderr,
    }


def _run_frontend_build(repo_root: Path, build_root: Path) -> dict[str, object]:
    npm_bin = shutil.which("npm")
    if not npm_bin:
        raise RuntimeError("Frontend changes detected but npm is not installed.")
    _ensure_frontend_node_modules(repo_root, build_root)
    cmd = [npm_bin, "run", "build"]
    result = subprocess.run(
        cmd,
        cwd=build_root / "frontend",
        text=True,
        capture_output=True,
        check=False,
    )
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError("Frontend build failed during predeploy checks.")
    return {
        "cmd": cmd,
        "returncode": result.returncode,
        "stdout": stdout,
        "stderr": stderr,
    }


def _write_json(path: str, payload: dict[str, object]) -> None:
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--build-root", required=True)
    parser.add_argument("--deploy-ref", required=True)
    parser.add_argument("--dirty-worktree", action="store_true")
    parser.add_argument(
        "--changed-path",
        action="append",
        default=[],
        help="Optional explicit changed path override. Can be supplied multiple times.",
    )
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    build_root = Path(args.build_root).resolve()

    try:
        diff_base, changed_paths = _changed_paths(
            repo_root,
            args.deploy_ref,
            dirty_worktree=args.dirty_worktree,
        )
        if args.changed_path:
            diff_base = "EXPLICIT"
            changed_paths = sorted({path for path in args.changed_path if path})
        pytest_targets, frontend_build, matched_rules = _select_plan(changed_paths)
        pytest_python = _resolve_pytest_python(repo_root)

        print("== Changed-path-aware predeploy checks ==")
        print(f"Deploy ref: {args.deploy_ref}")
        print(f"Diff base:  {diff_base}")
        print(f"Changed paths: {len(changed_paths)}")
        if matched_rules:
            print(f"Matched rules: {', '.join(matched_rules)}")
        print("Pytest targets:")
        for target in pytest_targets:
            print(f"  - {target}")
        print(f"Frontend build required: {'yes' if frontend_build else 'no'}")

        pytest_result = _run_pytest(pytest_python, build_root, pytest_targets)
        frontend_result = None
        if frontend_build:
            frontend_result = _run_frontend_build(repo_root, build_root)

        summary = {
            "ok": True,
            "deploy_ref": args.deploy_ref,
            "diff_base": diff_base,
            "dirty_worktree": args.dirty_worktree,
            "changed_paths": changed_paths,
            "matched_rules": matched_rules,
            "pytest_python": str(pytest_python),
            "pytest_targets": pytest_targets,
            "frontend_build_required": frontend_build,
            "pytest_result": pytest_result,
            "frontend_build_result": frontend_result,
        }
    except Exception as exc:  # pragma: no cover - CLI guard
        summary = {
            "ok": False,
            "deploy_ref": args.deploy_ref,
            "error": str(exc),
        }
        if args.json_out:
            _write_json(args.json_out, summary)
        print(f"Predeploy checks failed: {exc}", file=sys.stderr)
        return 1

    if args.json_out:
        _write_json(args.json_out, summary)
    print("Changed-path-aware predeploy checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
