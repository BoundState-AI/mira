#!/usr/bin/env python3
"""Run iterative OpenAI fine-tune experiments for MUA rationale quality."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI, RateLimitError

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
}

SECTION_RE = re.compile(
    r"Deficiency:\n(?P<deficiency>.*?)\n\nApplication:\n(?P<application>.*?)\n\nEnvironment:\n"
    r"(?P<environment>.*?)\n\nEvidence Cited:\n(?P<evidence>.*?)\n\nTask:",
    re.DOTALL | re.IGNORECASE,
)

TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--train-file",
        type=Path,
        default=Path("mua_rationale_train_v2_curated.jsonl"),
    )
    parser.add_argument(
        "--val-file",
        type=Path,
        default=Path("mua_rationale_val_v2_curated.jsonl"),
    )
    parser.add_argument("--base-model", type=str, default="gpt-4.1-2025-04-14")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--eval-limit", type=int, default=80)
    parser.add_argument("--max-output-tokens", type=int, default=220)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--retry-seconds", type=int, default=1800)
    parser.add_argument("--max-runs", type=int, default=4)
    parser.add_argument(
        "--configs-json",
        type=str,
        default='[{"n_epochs":1,"lr_mult":1.0},{"n_epochs":1,"lr_mult":0.7},{"n_epochs":1,"lr_mult":0.5},{"n_epochs":2,"lr_mult":0.5}]',
        help="JSON list of config dicts with n_epochs and lr_mult.",
    )
    parser.add_argument(
        "--target-deficiency",
        type=float,
        default=0.90,
        help="Stop early if model meets or exceeds this deficiency recall.",
    )
    parser.add_argument(
        "--target-context",
        type=float,
        default=0.50,
        help="Stop early if model meets or exceeds this context recall.",
    )
    parser.add_argument(
        "--target-evidence",
        type=float,
        default=0.85,
        help="Stop early if model meets or exceeds this evidence recall.",
    )
    parser.add_argument(
        "--runs-log",
        type=Path,
        default=Path("temp/openai_ft_runs/mua_rationale_v2_iterative_runs.jsonl"),
    )
    parser.add_argument(
        "--best-report",
        type=Path,
        default=Path("temp/openai_ft_runs/mua_rationale_v2_best.json"),
    )
    return parser.parse_args()


def tokenize_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for tok in re.findall(r"[a-z0-9][a-z0-9_/-]{1,}", (text or "").lower()):
        if tok in STOPWORDS:
            continue
        if len(tok) < 3 and not re.search(r"\d", tok):
            continue
        terms.add(tok)
    return terms


def recall_score(reference: str, generated: str) -> float:
    ref_terms = tokenize_terms(reference)
    if not ref_terms:
        return 0.0
    gen_terms = tokenize_terms(generated)
    return len(ref_terms & gen_terms) / len(ref_terms)


def parse_sections(user_prompt: str) -> dict[str, str]:
    match = SECTION_RE.search(user_prompt or "")
    if not match:
        return {"deficiency": "", "application": "", "environment": "", "evidence": ""}
    return {
        "deficiency": match.group("deficiency").strip(),
        "application": match.group("application").strip(),
        "environment": match.group("environment").strip(),
        "evidence": match.group("evidence").strip(),
    }


def load_rows(path: Path, limit: int) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return rows[:limit] if limit and limit > 0 else rows


def evaluate_model(
    client: OpenAI,
    model_name: str,
    rows: list[dict[str, Any]],
    max_output_tokens: int,
) -> dict[str, float]:
    def_scores: list[float] = []
    ctx_scores: list[float] = []
    ev_scores: list[float] = []
    tgt_scores: list[float] = []
    def_ok = 0
    ctx_ok = 0
    ev_ok = 0
    avg_words = 0.0

    for idx, row in enumerate(rows, start=1):
        messages = row["messages"]
        system_msg = messages[0]["content"]
        user_msg = messages[1]["content"]
        target = messages[2]["content"]
        sections = parse_sections(user_msg)

        resp = client.responses.create(
            model=model_name,
            input=[
                {"role": "system", "content": [{"type": "input_text", "text": system_msg}]},
                {"role": "user", "content": [{"type": "input_text", "text": user_msg}]},
            ],
            max_output_tokens=max_output_tokens,
            temperature=0,
        )
        generated = (resp.output_text or "").strip()

        d = recall_score(sections["deficiency"], generated)
        c = recall_score(f"{sections['application']} {sections['environment']}", generated)
        evidence_text = sections["evidence"]
        if "No explicit supporting evidence captured" in evidence_text:
            e = 1.0
        else:
            e = recall_score(evidence_text, generated)
        t = recall_score(target, generated)

        def_scores.append(d)
        ctx_scores.append(c)
        ev_scores.append(e)
        tgt_scores.append(t)
        avg_words += len(generated.split())

        def_ok += 1 if d >= 0.12 else 0
        ctx_ok += 1 if c >= 0.10 else 0
        ev_ok += 1 if e >= 0.10 else 0

        if idx % 10 == 0 or idx == len(rows):
            print(f"Evaluated {idx}/{len(rows)} for model={model_name}", flush=True)

    total = len(rows)
    return {
        "rows": float(total),
        "deficiency_recall": sum(def_scores) / total if total else 0.0,
        "context_recall": sum(ctx_scores) / total if total else 0.0,
        "evidence_recall": sum(ev_scores) / total if total else 0.0,
        "target_overlap_recall": sum(tgt_scores) / total if total else 0.0,
        "deficiency_pass_rate": def_ok / total if total else 0.0,
        "context_pass_rate": ctx_ok / total if total else 0.0,
        "evidence_pass_rate": ev_ok / total if total else 0.0,
        "avg_words": avg_words / total if total else 0.0,
    }


def append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, ensure_ascii=True))
        handle.write("\n")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    args = parse_args()
    configs = json.loads(args.configs_json)
    if not configs:
        raise ValueError("No configs provided.")

    client = OpenAI()
    if not args.train_file.exists() or not args.val_file.exists():
        raise FileNotFoundError("Curated train/val files are required.")

    rows = load_rows(args.val_file, args.eval_limit)
    print(f"Loaded eval rows: {len(rows)} from {args.val_file}")

    print(f"[{now_utc()}] Evaluating base model {args.base_model}")
    base_metrics = evaluate_model(client, args.base_model, rows, args.max_output_tokens)
    print(f"Base metrics: {base_metrics}")
    append_jsonl(
        args.runs_log,
        {
            "timestamp_utc": now_utc(),
            "kind": "baseline",
            "model": args.base_model,
            "metrics": base_metrics,
            "seed": args.seed,
        },
    )

    print(f"[{now_utc()}] Uploading train/val files once for all runs")
    with args.train_file.open("rb") as fh:
        train_upload = client.files.create(file=fh, purpose="fine-tune")
    with args.val_file.open("rb") as fh:
        val_upload = client.files.create(file=fh, purpose="fine-tune")
    print(f"Training file id: {train_upload.id}")
    print(f"Validation file id: {val_upload.id}")

    best: dict[str, Any] | None = None
    run_count = 0

    for config in configs:
        if run_count >= args.max_runs:
            break

        n_epochs = int(config["n_epochs"])
        lr_mult = float(config["lr_mult"])
        suffix = f"mua-rat-v2-e{n_epochs}-lr{str(lr_mult).replace('.', 'p')}-s{args.seed}"

        while True:
            try:
                print(
                    f"[{now_utc()}] Creating FT job config: "
                    f"n_epochs={n_epochs}, lr_mult={lr_mult}, seed={args.seed}"
                )
                job = client.fine_tuning.jobs.create(
                    model=args.base_model,
                    training_file=train_upload.id,
                    validation_file=val_upload.id,
                    method={
                        "type": "supervised",
                        "supervised": {
                            "hyperparameters": {
                                "n_epochs": n_epochs,
                                "batch_size": "auto",
                                "learning_rate_multiplier": lr_mult,
                            }
                        },
                    },
                    seed=args.seed,
                    suffix=suffix[:18],
                    metadata={
                        "project": "mua-rationale-v2-iterate",
                        "seed": str(args.seed),
                        "n_epochs": str(n_epochs),
                        "lr_mult": str(lr_mult),
                    },
                )
                break
            except RateLimitError as exc:
                msg = str(exc)
                if "daily_rate_limit_exceeded" in msg:
                    print(
                        f"[{now_utc()}] Daily FT cap reached. "
                        f"Sleeping {args.retry_seconds}s and retrying."
                    )
                    time.sleep(max(args.retry_seconds, 60))
                    continue
                raise

        run_count += 1
        print(f"Job created: {job.id}")

        while True:
            state = client.fine_tuning.jobs.retrieve(job.id)
            print(f"[{now_utc()}] job={job.id} status={state.status}")
            if state.status in TERMINAL_STATES:
                break
            time.sleep(max(args.poll_seconds, 15))

        run_record: dict[str, Any] = {
            "timestamp_utc": now_utc(),
            "kind": "fine_tune_run",
            "job_id": job.id,
            "status": state.status,
            "seed": args.seed,
            "n_epochs": n_epochs,
            "lr_mult": lr_mult,
            "training_file_id": train_upload.id,
            "validation_file_id": val_upload.id,
            "trained_tokens": getattr(state, "trained_tokens", None),
            "fine_tuned_model": getattr(state, "fine_tuned_model", None),
        }

        if state.status != "succeeded":
            run_record["error"] = str(getattr(state, "error", None))
            append_jsonl(args.runs_log, run_record)
            print(f"Run failed/cancelled: {run_record['error']}")
            continue

        ft_model = state.fine_tuned_model
        print(f"[{now_utc()}] Evaluating fine-tuned model {ft_model}")
        ft_metrics = evaluate_model(client, ft_model, rows, args.max_output_tokens)
        run_record["metrics"] = ft_metrics
        append_jsonl(args.runs_log, run_record)
        print(f"Run metrics: {ft_metrics}")

        score = (
            0.5 * ft_metrics["deficiency_recall"]
            + 0.3 * ft_metrics["context_recall"]
            + 0.2 * ft_metrics["evidence_recall"]
        )
        if best is None or score > best["score"]:
            best = {
                "score": score,
                "job_id": job.id,
                "model": ft_model,
                "n_epochs": n_epochs,
                "lr_mult": lr_mult,
                "seed": args.seed,
                "metrics": ft_metrics,
                "baseline_metrics": base_metrics,
                "selected_at_utc": now_utc(),
            }
            args.best_report.parent.mkdir(parents=True, exist_ok=True)
            args.best_report.write_text(json.dumps(best, indent=2), encoding="utf-8")
            print(f"Updated best model -> {ft_model}")

        if (
            ft_metrics["deficiency_recall"] >= args.target_deficiency
            and ft_metrics["context_recall"] >= args.target_context
            and ft_metrics["evidence_recall"] >= args.target_evidence
        ):
            print("Target quality reached. Stopping iteration.")
            break

    print("Iteration complete.")
    if best:
        print(f"Best model: {best['model']}")
        print(f"Best metrics: {best['metrics']}")
        print(f"Baseline metrics: {best['baseline_metrics']}")


if __name__ == "__main__":
    main()
