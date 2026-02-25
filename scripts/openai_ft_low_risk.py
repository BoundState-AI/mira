#!/usr/bin/env python3
"""Launch low-risk OpenAI fine-tune runs and wait out daily caps safely."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI, RateLimitError

TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-file", type=Path, required=True)
    parser.add_argument("--val-file", type=Path, required=True)
    parser.add_argument("--model", type=str, default="gpt-4.1-2025-04-14")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-epochs", type=int, default=1, choices=[1, 2])
    parser.add_argument("--learning-rate-multiplier", type=float, default=0.5)
    parser.add_argument("--suffix", type=str, default="mua-lr")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--retry-seconds", type=int, default=1800)
    parser.add_argument("--run-log", type=Path, default=Path("temp/openai_ft_runs/low_risk_runs.jsonl"))
    return parser.parse_args()


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, ensure_ascii=True))
        handle.write("\n")


def calc_next_slot(client: OpenAI, model: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    jobs = list(client.fine_tuning.jobs.list(limit=100).data)
    used = []
    for job in jobs:
        if job.model != model:
            continue
        dt = datetime.fromtimestamp(job.created_at, tz=timezone.utc)
        if dt >= now - timedelta(hours=24):
            used.append(dt)
    if len(used) < 8:
        return None
    return min(used) + timedelta(hours=24)


def main() -> None:
    args = parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set.")
    if not args.train_file.exists() or not args.val_file.exists():
        raise FileNotFoundError("Train/val file missing.")
    if args.learning_rate_multiplier > 0.7:
        raise ValueError("Low-risk launcher enforces lr multiplier <= 0.7.")

    client = OpenAI()
    print(f"Uploading train file: {args.train_file}")
    with args.train_file.open("rb") as fh:
        train_upload = client.files.create(file=fh, purpose="fine-tune")
    print(f"Uploading val file: {args.val_file}")
    with args.val_file.open("rb") as fh:
        val_upload = client.files.create(file=fh, purpose="fine-tune")

    job = None
    while job is None:
        try:
            print(
                f"[{now_utc()}] Creating low-risk FT job "
                f"(epochs={args.n_epochs}, lr={args.learning_rate_multiplier}, seed={args.seed})"
            )
            job = client.fine_tuning.jobs.create(
                model=args.model,
                training_file=train_upload.id,
                validation_file=val_upload.id,
                method={
                    "type": "supervised",
                    "supervised": {
                        "hyperparameters": {
                            "n_epochs": args.n_epochs,
                            "batch_size": "auto",
                            "learning_rate_multiplier": args.learning_rate_multiplier,
                        }
                    },
                },
                seed=args.seed,
                suffix=args.suffix[:18],
                metadata={
                    "project": "mua-low-risk-ft",
                    "seed": str(args.seed),
                    "n_epochs": str(args.n_epochs),
                    "learning_rate_multiplier": str(args.learning_rate_multiplier),
                },
            )
        except RateLimitError as exc:
            msg = str(exc)
            if "daily_rate_limit_exceeded" in msg:
                next_slot = calc_next_slot(client, args.model)
                eta_min = int((next_slot - datetime.now(timezone.utc)).total_seconds() // 60) if next_slot else -1
                print(
                    f"[{now_utc()}] Daily cap reached. "
                    f"Next expected slot: {next_slot.isoformat() if next_slot else 'unknown'} "
                    f"(eta~{eta_min}m). Sleeping {args.retry_seconds}s."
                )
                time.sleep(max(args.retry_seconds, 60))
                continue
            raise

    print(f"Created job: {job.id} status={job.status}")
    record = {
        "timestamp_utc": now_utc(),
        "event": "job_created",
        "job_id": job.id,
        "status": job.status,
        "model": args.model,
        "seed": args.seed,
        "n_epochs": args.n_epochs,
        "learning_rate_multiplier": args.learning_rate_multiplier,
        "train_file_id": train_upload.id,
        "val_file_id": val_upload.id,
    }
    append_jsonl(args.run_log, record)

    if not args.wait:
        return

    while True:
        state = client.fine_tuning.jobs.retrieve(job.id)
        print(f"[{now_utc()}] {job.id} status={state.status}")
        if state.status in TERMINAL_STATES:
            checkpoints = list(client.fine_tuning.jobs.checkpoints.list(job.id, limit=5).data)
            best = None
            if checkpoints:
                best = max(checkpoints, key=lambda cp: getattr(cp, "step_number", 0))
            done = {
                "timestamp_utc": now_utc(),
                "event": "job_finished",
                "job_id": job.id,
                "status": state.status,
                "fine_tuned_model": getattr(state, "fine_tuned_model", None),
                "trained_tokens": getattr(state, "trained_tokens", None),
                "checkpoint_step": getattr(best, "step_number", None) if best else None,
                "train_loss": getattr(best.metrics, "train_loss", None) if best else None,
                "valid_loss": getattr(best.metrics, "valid_loss", None) if best else None,
                "full_valid_loss": getattr(best.metrics, "full_valid_loss", None) if best else None,
                "error": str(getattr(state, "error", None)),
            }
            append_jsonl(args.run_log, done)
            print(json.dumps(done, indent=2))
            break
        time.sleep(max(args.poll_seconds, 15))


if __name__ == "__main__":
    main()
