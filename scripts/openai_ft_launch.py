#!/usr/bin/env python3
"""Launch and optionally wait for an OpenAI supervised fine-tuning job."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI


TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-file", type=Path, required=True)
    parser.add_argument("--val-file", type=Path, required=True)
    parser.add_argument("--model", type=str, default="gpt-4.1-2025-04-14")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--n-epochs",
        type=str,
        default="auto",
        help="Epoch count as integer string or 'auto'.",
    )
    parser.add_argument(
        "--learning-rate-multiplier",
        type=str,
        default="auto",
        help="LR multiplier as float string or 'auto'.",
    )
    parser.add_argument(
        "--batch-size",
        type=str,
        default="auto",
        help="Batch size as integer string or 'auto'.",
    )
    parser.add_argument("--suffix", type=str, default="mua-rationale")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument(
        "--run-log-dir",
        type=Path,
        default=Path("temp/openai_ft_runs"),
    )
    return parser.parse_args()


def parse_auto_int(value: str) -> str | int:
    value = value.strip().lower()
    if value == "auto":
        return "auto"
    return int(value)


def parse_auto_float(value: str) -> str | float:
    value = value.strip().lower()
    if value == "auto":
        return "auto"
    return float(value)


def file_record(obj: Any) -> dict[str, Any]:
    return {
        "id": obj.id,
        "filename": getattr(obj, "filename", ""),
        "bytes": getattr(obj, "bytes", None),
        "status": getattr(obj, "status", None),
        "created_at": getattr(obj, "created_at", None),
    }


def job_record(obj: Any) -> dict[str, Any]:
    payload = {
        "id": obj.id,
        "model": getattr(obj, "model", None),
        "status": getattr(obj, "status", None),
        "created_at": getattr(obj, "created_at", None),
        "finished_at": getattr(obj, "finished_at", None),
        "trained_tokens": getattr(obj, "trained_tokens", None),
        "fine_tuned_model": getattr(obj, "fine_tuned_model", None),
        "seed": getattr(obj, "seed", None),
    }
    if getattr(obj, "error", None):
        payload["error"] = {
            "code": getattr(obj.error, "code", None),
            "message": getattr(obj.error, "message", None),
            "param": getattr(obj.error, "param", None),
        }
    if getattr(obj, "hyperparameters", None):
        payload["hyperparameters"] = {
            "n_epochs": getattr(obj.hyperparameters, "n_epochs", None),
            "batch_size": getattr(obj.hyperparameters, "batch_size", None),
            "learning_rate_multiplier": getattr(
                obj.hyperparameters, "learning_rate_multiplier", None
            ),
        }
    if getattr(obj, "method", None):
        payload["method"] = str(obj.method)
    return payload


def main() -> None:
    args = parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set in the environment.")
    if not args.train_file.exists() or not args.val_file.exists():
        raise FileNotFoundError("Train/val JSONL files were not found.")

    client = OpenAI()

    print(f"Uploading training file: {args.train_file}")
    with args.train_file.open("rb") as fh:
        train_upload = client.files.create(file=fh, purpose="fine-tune")

    print(f"Uploading validation file: {args.val_file}")
    with args.val_file.open("rb") as fh:
        val_upload = client.files.create(file=fh, purpose="fine-tune")

    hyperparameters = {
        "n_epochs": parse_auto_int(args.n_epochs),
        "batch_size": parse_auto_int(args.batch_size),
        "learning_rate_multiplier": parse_auto_float(args.learning_rate_multiplier),
    }

    metadata = {
        "project": "mua-rationale-writer",
        "dataset_train": args.train_file.name,
        "dataset_val": args.val_file.name,
        "seed": str(args.seed),
    }

    print("Creating fine-tuning job...")
    job = client.fine_tuning.jobs.create(
        model=args.model,
        training_file=train_upload.id,
        validation_file=val_upload.id,
        method={"type": "supervised", "supervised": {"hyperparameters": hyperparameters}},
        seed=args.seed,
        suffix=args.suffix,
        metadata=metadata,
    )

    print(f"Fine-tuning job id: {job.id}")
    print(f"Initial status: {job.status}")

    event_log: list[dict[str, Any]] = []
    if args.wait:
        while True:
            current = client.fine_tuning.jobs.retrieve(job.id)
            stamp = datetime.now(timezone.utc).isoformat()
            event_log.append({"timestamp_utc": stamp, "status": current.status})
            print(f"[{stamp}] status={current.status}")
            if current.status in TERMINAL_STATES:
                job = current
                break
            time.sleep(max(args.poll_seconds, 5))

    run_payload = {
        "launched_at_utc": datetime.now(timezone.utc).isoformat(),
        "request": {
            "model": args.model,
            "seed": args.seed,
            "n_epochs": args.n_epochs,
            "batch_size": args.batch_size,
            "learning_rate_multiplier": args.learning_rate_multiplier,
            "suffix": args.suffix,
        },
        "train_file": file_record(train_upload),
        "val_file": file_record(val_upload),
        "job": job_record(job),
        "status_polls": event_log,
    }

    args.run_log_dir.mkdir(parents=True, exist_ok=True)
    run_path = args.run_log_dir / f"{job.id}.json"
    run_path.write_text(json.dumps(run_payload, indent=2), encoding="utf-8")

    print(f"Run log written: {run_path}")
    if job.status == "succeeded":
        print(f"Fine-tuned model: {job.fine_tuned_model}")


if __name__ == "__main__":
    main()
