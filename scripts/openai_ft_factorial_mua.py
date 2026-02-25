#!/usr/bin/env python3
"""Run a 2^3 factorial OpenAI FT experiment for MUA rationale tuning.

Factors:
1) learning_rate_multiplier (low/high)
2) n_epochs (low/high)
3) negative_example_ratio in training set (low/high)

Objective:
- Minimize full_valid_loss (primary)
- Do not optimize for min train_loss
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

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


@dataclass
class RunConfig:
    run_id: str
    learning_rate_multiplier: float
    n_epochs: int
    negative_ratio: float
    seed: int
    train_local_file: str = ""
    train_file_id: str = ""
    validation_file_id: str = ""
    job_id: str = ""
    status: str = "pending_create"
    fine_tuned_model: str = ""
    trained_tokens: int | None = None
    train_loss: float | None = None
    valid_loss: float | None = None
    full_valid_loss: float | None = None
    checkpoint_step: int | None = None
    created_at_utc: str = ""
    finished_at_utc: str = ""
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-model", type=str, default="gpt-4.1-2025-04-14")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--lr-levels", type=str, default="0.5,1.0")
    parser.add_argument("--epoch-levels", type=str, default="1,2")
    parser.add_argument("--neg-levels", type=str, default="0.0,0.30")
    parser.add_argument("--train-size", type=int, default=704)
    parser.add_argument(
        "--positive-train-file",
        type=Path,
        default=Path("mua_rationale_train_v2_curated.jsonl"),
    )
    parser.add_argument(
        "--validation-file",
        type=Path,
        default=Path("mua_rationale_val_v2_curated.jsonl"),
    )
    parser.add_argument(
        "--negative-source-files",
        type=Path,
        nargs="+",
        default=[Path("mua_rationale_train.jsonl"), Path("mua_rationale_val.jsonl")],
    )
    parser.add_argument(
        "--experiment-dir",
        type=Path,
        default=Path("temp/openai_ft_factorial_mua"),
    )
    parser.add_argument("--poll-seconds", type=int, default=90)
    parser.add_argument("--capacity-check-seconds", type=int, default=60)
    parser.add_argument("--max-jobs", type=int, default=8)
    return parser.parse_args()


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_float_levels(raw: str) -> list[float]:
    vals = [float(x.strip()) for x in raw.split(",") if x.strip()]
    if len(vals) != 2:
        raise ValueError(f"Expected 2 levels, got: {raw}")
    return vals


def parse_int_levels(raw: str) -> list[int]:
    vals = [int(x.strip()) for x in raw.split(",") if x.strip()]
    if len(vals) != 2:
        raise ValueError(f"Expected 2 levels, got: {raw}")
    return vals


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def normalize_spaces(text: str) -> str:
    return " ".join((text or "").split())


def uppercase_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


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


def row_quality_metrics(row: dict[str, Any]) -> dict[str, float]:
    messages = row.get("messages") or []
    if len(messages) < 3:
        return {
            "word_count": 0.0,
            "uppercase_ratio": 0.0,
            "deficiency_recall": 0.0,
            "context_recall": 0.0,
            "evidence_recall": 0.0,
            "quality_score": 0.0,
        }
    user_prompt = messages[-2].get("content", "")
    target = normalize_spaces(messages[-1].get("content", ""))
    sections = parse_sections(user_prompt)

    word_count = float(len(target.split()))
    up_ratio = uppercase_ratio(target)
    d_recall = recall_score(sections["deficiency"], target)
    c_recall = recall_score(f"{sections['application']} {sections['environment']}", target)
    if "No explicit supporting evidence captured" in sections["evidence"]:
        e_recall = 1.0
    else:
        e_recall = recall_score(sections["evidence"], target)
    quality_score = 0.5 * d_recall + 0.3 * c_recall + 0.2 * e_recall
    return {
        "word_count": word_count,
        "uppercase_ratio": up_ratio,
        "deficiency_recall": d_recall,
        "context_recall": c_recall,
        "evidence_recall": e_recall,
        "quality_score": quality_score,
    }


def row_key(row: dict[str, Any]) -> str:
    # Stable content key across files.
    return json.dumps(row, sort_keys=True, ensure_ascii=True)


def make_negative_pool(
    positive_rows: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    positive_keys = {row_key(r) for r in positive_rows}
    candidates = [r for r in source_rows if row_key(r) not in positive_keys]

    # Prioritize low-quality rows as "negatives" for this factorial factor.
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in candidates:
        m = row_quality_metrics(row)
        scored.append((m["quality_score"], row))
    scored.sort(key=lambda x: x[0])  # low quality first

    negatives = [row for _, row in scored]
    return negatives


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True))
            handle.write("\n")


def calc_capacity_status(client: OpenAI, model: str) -> tuple[int, datetime | None]:
    now = datetime.now(timezone.utc)
    jobs = list(client.fine_tuning.jobs.list(limit=100).data)
    in_window: list[datetime] = []
    for job in jobs:
        if job.model != model:
            continue
        dt = datetime.fromtimestamp(job.created_at, tz=timezone.utc)
        if dt >= now - timedelta(hours=24):
            in_window.append(dt)
    used = len(in_window)
    if used < 8:
        return used, None
    return used, min(in_window) + timedelta(hours=24)


def append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, ensure_ascii=True))
        handle.write("\n")


def summarize_results(runs: list[RunConfig], out_path: Path) -> None:
    ranked = [r for r in runs if r.full_valid_loss is not None]
    ranked.sort(key=lambda r: r.full_valid_loss if r.full_valid_loss is not None else 1e9)

    payload = {
        "generated_at_utc": now_utc(),
        "objective": "minimize_full_valid_loss",
        "runs_completed": len([r for r in runs if r.status in TERMINAL_STATES]),
        "runs_succeeded": len([r for r in runs if r.status == "succeeded"]),
        "best_run": asdict(ranked[0]) if ranked else None,
        "all_runs": [asdict(r) for r in runs],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    client = OpenAI()

    lr_levels = parse_float_levels(args.lr_levels)
    epoch_levels = parse_int_levels(args.epoch_levels)
    neg_levels = parse_float_levels(args.neg_levels)

    print(
        f"Factor levels -> lr={lr_levels}, epochs={epoch_levels}, neg_ratio={neg_levels}; "
        f"objective=min full_valid_loss"
    )

    pos_train = load_jsonl(args.positive_train_file)
    val_rows = load_jsonl(args.validation_file)
    neg_source: list[dict[str, Any]] = []
    for path in args.negative_source_files:
        neg_source.extend(load_jsonl(path))

    negatives = make_negative_pool(pos_train + val_rows, neg_source)
    if not negatives:
        raise RuntimeError("Negative pool is empty; cannot vary negative ratio.")

    print(
        f"Loaded: pos_train={len(pos_train)}, val={len(val_rows)}, "
        f"negative_pool={len(negatives)}"
    )

    design = list(itertools.product(lr_levels, epoch_levels, neg_levels))
    if len(design) != 8:
        raise RuntimeError("Expected 8 runs for 2^3 factorial design.")
    if args.max_jobs < len(design):
        design = design[: args.max_jobs]
        print(f"Truncated design to first {len(design)} runs due to --max-jobs.")

    runs: list[RunConfig] = []
    data_dir = args.experiment_dir / "datasets"
    files_dir = args.experiment_dir / "files"
    summary_path = args.experiment_dir / "factorial_summary.json"
    runlog_path = args.experiment_dir / "factorial_runlog.jsonl"

    random_base = random.Random(args.seed)
    # Shared validation file upload.
    with args.validation_file.open("rb") as fh:
        val_upload = client.files.create(file=fh, purpose="fine-tune")
    print(f"Uploaded validation file id={val_upload.id}")

    for i, (lr, epochs, neg_ratio) in enumerate(design, start=1):
        cfg_seed = args.seed + i * 101
        rng = random.Random(cfg_seed)
        run_id = f"run{i:02d}"
        run = RunConfig(
            run_id=run_id,
            learning_rate_multiplier=lr,
            n_epochs=epochs,
            negative_ratio=neg_ratio,
            seed=cfg_seed,
            validation_file_id=val_upload.id,
        )

        neg_n = int(round(args.train_size * neg_ratio))
        pos_n = args.train_size - neg_n
        if pos_n > len(pos_train):
            raise RuntimeError(f"Requested positive count {pos_n} exceeds pool {len(pos_train)}")
        if neg_n > len(negatives):
            raise RuntimeError(f"Requested negative count {neg_n} exceeds pool {len(negatives)}")

        pos_sample = rng.sample(pos_train, pos_n)
        neg_sample = rng.sample(negatives, neg_n) if neg_n > 0 else []
        mixed = pos_sample + neg_sample
        rng.shuffle(mixed)

        train_file = data_dir / f"{run_id}_train_lr{lr}_e{epochs}_n{neg_ratio}.jsonl"
        write_jsonl(train_file, mixed)
        run.train_local_file = str(train_file)

        with train_file.open("rb") as fh:
            train_upload = client.files.create(file=fh, purpose="fine-tune")
        run.train_file_id = train_upload.id
        runs.append(run)
        print(
            f"[{run_id}] dataset ready: pos={pos_n}, neg={neg_n}, "
            f"train_file_id={run.train_file_id}"
        )
        append_jsonl(
            runlog_path,
            {
                "timestamp_utc": now_utc(),
                "event": "dataset_uploaded",
                "run": asdict(run),
            },
        )

    # Main create/monitor loop.
    next_create_idx = 0
    while True:
        # Create as many jobs as capacity allows.
        while next_create_idx < len(runs):
            used, opens_at = calc_capacity_status(client, args.base_model)
            if used >= 8:
                eta = int((opens_at - datetime.now(timezone.utc)).total_seconds() // 60) if opens_at else -1
                print(
                    f"[{now_utc()}] FT cap reached ({used}/8). "
                    f"Next expected open at {opens_at.isoformat() if opens_at else 'unknown'} "
                    f"(eta~{eta}m)"
                )
                break

            run = runs[next_create_idx]
            suffix = f"muaf{next_create_idx+1:02d}"
            print(
                f"[{now_utc()}] Creating job for {run.run_id}: "
                f"lr={run.learning_rate_multiplier}, epochs={run.n_epochs}, neg={run.negative_ratio}"
            )
            job = client.fine_tuning.jobs.create(
                model=args.base_model,
                training_file=run.train_file_id,
                validation_file=run.validation_file_id,
                method={
                    "type": "supervised",
                    "supervised": {
                        "hyperparameters": {
                            "n_epochs": run.n_epochs,
                            "batch_size": "auto",
                            "learning_rate_multiplier": run.learning_rate_multiplier,
                        }
                    },
                },
                seed=run.seed,
                suffix=suffix,
                metadata={
                    "project": "mua-rationale-factorial",
                    "run_id": run.run_id,
                    "objective": "min_full_valid_loss",
                    "lr_mult": str(run.learning_rate_multiplier),
                    "n_epochs": str(run.n_epochs),
                    "negative_ratio": str(run.negative_ratio),
                    "seed": str(run.seed),
                },
            )
            run.job_id = job.id
            run.status = job.status
            run.created_at_utc = now_utc()
            append_jsonl(
                runlog_path,
                {
                    "timestamp_utc": now_utc(),
                    "event": "job_created",
                    "run_id": run.run_id,
                    "job_id": run.job_id,
                    "status": run.status,
                },
            )
            print(f"[{run.run_id}] job_id={run.job_id} status={run.status}")
            next_create_idx += 1

        # Refresh statuses and collect metrics for completed runs.
        completed = 0
        for run in runs:
            if not run.job_id:
                continue
            if run.status in TERMINAL_STATES and run.full_valid_loss is not None:
                completed += 1
                continue

            state = client.fine_tuning.jobs.retrieve(run.job_id)
            if run.status != state.status:
                print(f"[{now_utc()}] {run.run_id} ({run.job_id}) -> {state.status}")
                run.status = state.status
                append_jsonl(
                    runlog_path,
                    {
                        "timestamp_utc": now_utc(),
                        "event": "status_change",
                        "run_id": run.run_id,
                        "job_id": run.job_id,
                        "status": run.status,
                    },
                )

            if state.status in TERMINAL_STATES:
                run.fine_tuned_model = getattr(state, "fine_tuned_model", "") or ""
                run.trained_tokens = getattr(state, "trained_tokens", None)
                run.finished_at_utc = now_utc()
                if state.status != "succeeded":
                    run.error = str(getattr(state, "error", None))
                    run.full_valid_loss = run.full_valid_loss if run.full_valid_loss is not None else 1e9
                    completed += 1
                    continue

                checkpoints = list(client.fine_tuning.jobs.checkpoints.list(run.job_id, limit=20).data)
                if checkpoints:
                    best_cp = max(checkpoints, key=lambda cp: getattr(cp, "step_number", 0))
                    metrics = best_cp.metrics
                    run.checkpoint_step = int(getattr(best_cp, "step_number", 0))
                    run.train_loss = float(getattr(metrics, "train_loss", 0.0))
                    run.valid_loss = float(getattr(metrics, "valid_loss", 0.0))
                    run.full_valid_loss = float(getattr(metrics, "full_valid_loss", 0.0))
                else:
                    run.error = "No checkpoints returned"
                    run.full_valid_loss = 1e9
                completed += 1
                append_jsonl(
                    runlog_path,
                    {
                        "timestamp_utc": now_utc(),
                        "event": "run_completed",
                        "run": asdict(run),
                    },
                )
                summarize_results(runs, summary_path)

        summarize_results(runs, summary_path)

        all_created = next_create_idx >= len(runs)
        all_terminal = all(
            (r.job_id and r.status in TERMINAL_STATES and r.full_valid_loss is not None) for r in runs
        )
        if all_created and all_terminal:
            break

        time.sleep(max(args.poll_seconds, 30))

    # Final ranking by full_valid_loss only.
    successful = [r for r in runs if r.status == "succeeded" and r.full_valid_loss is not None]
    successful.sort(key=lambda r: r.full_valid_loss if r.full_valid_loss is not None else 1e9)
    print("Factorial complete.")
    print("Ranking by min full_valid_loss:")
    for idx, r in enumerate(successful, start=1):
        print(
            f"{idx}. {r.run_id} job={r.job_id} full_valid_loss={r.full_valid_loss:.6f} "
            f"(lr={r.learning_rate_multiplier}, epochs={r.n_epochs}, neg={r.negative_ratio})"
        )
    if successful:
        best = successful[0]
        print(
            f"BEST: {best.run_id} -> full_valid_loss={best.full_valid_loss:.6f}; "
            f"lr={best.learning_rate_multiplier}, epochs={best.n_epochs}, neg={best.negative_ratio}"
        )


if __name__ == "__main__":
    main()
