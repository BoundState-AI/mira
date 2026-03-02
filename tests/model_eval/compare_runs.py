#!/usr/bin/env python3
"""
Compare two model-eval result bundles and print tier/case deltas.

Usage:
  python -m tests.model_eval.compare_runs \
    --pre tests/model_eval/results_pre/results.json \
    --post tests/model_eval/results_post/results.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _model_map(payload: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in payload.get("sonnet_tier", []):
        out[(row["tier"], row["model"])] = row
    for row in payload.get("haiku_tier", []):
        out[(row["tier"], row["model"])] = row
    return out


def _print_model_delta(key: tuple[str, str], pre_row: dict[str, Any], post_row: dict[str, Any]) -> None:
    tier, model = key
    print(f"\n[{tier.upper()}] {model}")
    fields = [
        "weighted_avg",
        "avg_parseable",
        "avg_classification",
        "avg_key_facts",
        "avg_uncertainty",
        "avg_latency_s",
    ]
    for field in fields:
        a = float(pre_row[field])
        b = float(post_row[field])
        print(f"  {field}: {a:.3f} -> {b:.3f} (delta {b-a:+.3f})")

    pre_cases = {c["case_id"]: c for c in pre_row.get("cases", [])}
    post_cases = {c["case_id"]: c for c in post_row.get("cases", [])}
    deltas: list[tuple[float, str, dict[str, Any], dict[str, Any]]] = []
    for case_id, a in pre_cases.items():
        b = post_cases.get(case_id)
        if not b:
            continue
        d = float(b["weighted_total"]) - float(a["weighted_total"])
        if abs(d) > 1e-9:
            deltas.append((d, case_id, a, b))
    deltas.sort()
    if deltas:
        print("  case deltas:")
        for d, cid, a, b in deltas:
            print(
                "   "
                f"{cid}: total {a['weighted_total']:.3f}->{b['weighted_total']:.3f} ({d:+.3f}) | "
                f"parse {a['parseable']:.2f}->{b['parseable']:.2f} | "
                f"class {a['classification']:.2f}->{b['classification']:.2f} | "
                f"facts {a['key_facts']:.2f}->{b['key_facts']:.2f} | "
                f"unc {a['uncertainty']:.2f}->{b['uncertainty']:.2f}"
            )
    else:
        print("  case deltas: none")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two model-eval runs.")
    parser.add_argument("--pre", type=Path, required=True, help="Path to baseline results.json")
    parser.add_argument("--post", type=Path, required=True, help="Path to candidate results.json")
    args = parser.parse_args()

    pre = _load(args.pre)
    post = _load(args.post)
    pre_map = _model_map(pre)
    post_map = _model_map(post)

    keys = sorted(set(pre_map) & set(post_map))
    if not keys:
        print("No overlapping (tier, model) entries found between runs.")
        return

    for key in keys:
        _print_model_delta(key, pre_map[key], post_map[key])


if __name__ == "__main__":
    main()
