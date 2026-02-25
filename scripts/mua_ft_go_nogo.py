#!/usr/bin/env python3
"""Gate a candidate FT model by comparing eval metrics vs baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-preds", type=Path, required=True)
    parser.add_argument("--candidate-preds", type=Path, required=True)
    parser.add_argument("--report-out", type=Path, default=Path("temp/openai_ft_runs/mua_go_nogo_report.json"))
    parser.add_argument("--max-def-drop", type=float, default=0.02)
    parser.add_argument("--max-ctx-drop", type=float, default=0.02)
    parser.add_argument("--max-ev-drop", type=float, default=0.03)
    parser.add_argument("--min-target-overlap-delta", type=float, default=0.0)
    return parser.parse_args()


def load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def avg(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return sum(float(row.get(key, 0.0)) for row in rows) / len(rows)


def pass_rate(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if row.get(key)) / len(rows)


def metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    return {
        "deficiency_recall": avg(rows, "deficiency_recall"),
        "context_recall": avg(rows, "context_recall"),
        "evidence_recall": avg(rows, "evidence_recall"),
        "target_overlap_recall": avg(rows, "target_overlap_recall"),
        "deficiency_pass_rate": pass_rate(rows, "deficiency_ok"),
        "context_pass_rate": pass_rate(rows, "context_ok"),
        "evidence_pass_rate": pass_rate(rows, "evidence_ok"),
        "avg_words": avg(
            [{"w": len((row.get("generated_text") or "").split())} for row in rows],
            "w",
        ),
        "rows": float(len(rows)),
    }


def main() -> None:
    args = parse_args()
    if not args.baseline_preds.exists() or not args.candidate_preds.exists():
        raise FileNotFoundError("Missing prediction files.")

    base_rows = load(args.baseline_preds)
    cand_rows = load(args.candidate_preds)
    n = min(len(base_rows), len(cand_rows))
    base_rows = base_rows[:n]
    cand_rows = cand_rows[:n]

    base = metrics(base_rows)
    cand = metrics(cand_rows)
    delta = {k: cand[k] - base[k] for k in base.keys() if k in cand}

    checks = {
        "deficiency_drop_ok": delta["deficiency_recall"] >= -args.max_def_drop,
        "context_drop_ok": delta["context_recall"] >= -args.max_ctx_drop,
        "evidence_drop_ok": delta["evidence_recall"] >= -args.max_ev_drop,
        "target_overlap_ok": delta["target_overlap_recall"] >= args.min_target_overlap_delta,
    }
    decision = "GO" if all(checks.values()) else "NO_GO"

    report = {
        "decision": decision,
        "rows_compared": n,
        "thresholds": {
            "max_def_drop": args.max_def_drop,
            "max_ctx_drop": args.max_ctx_drop,
            "max_ev_drop": args.max_ev_drop,
            "min_target_overlap_delta": args.min_target_overlap_delta,
        },
        "baseline_metrics": base,
        "candidate_metrics": cand,
        "delta": delta,
        "checks": checks,
    }

    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Decision: {decision}")
    print(f"Rows compared: {n}")
    print("Delta (candidate - baseline):")
    print(
        f"  deficiency={delta['deficiency_recall']:.4f}, "
        f"context={delta['context_recall']:.4f}, "
        f"evidence={delta['evidence_recall']:.4f}, "
        f"target_overlap={delta['target_overlap_recall']:.4f}"
    )
    print(f"Report: {args.report_out}")


if __name__ == "__main__":
    main()
