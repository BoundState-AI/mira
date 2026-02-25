#!/usr/bin/env python3
"""Evaluate MUA category/determination routing accuracy on validation set."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

CATEGORY_RE = re.compile(r"Category:\s*(IV|III|II|I)\b", re.IGNORECASE)
DETERMINATION_RE = re.compile(r"Determination:\s*([A-Z_]+)", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--val-file", type=Path, default=Path("mua_val.jsonl"))
    parser.add_argument(
        "--model-name",
        type=str,
        default="meta-llama/Llama-3.2-3B-Instruct",
    )
    parser.add_argument("--adapter-dir", type=Path, default=Path("mua_lora_adapter"))
    parser.add_argument("--max-new-tokens", type=int, default=192)
    parser.add_argument("--predictions-out", type=Path, default=Path("mua_val_predictions.jsonl"))
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional cap on number of validation rows to evaluate (0 = all rows).",
    )
    return parser.parse_args()


def normalize_determination(raw: str) -> str:
    value = (raw or "").strip().upper()
    if value == "APPROVED":
        return "APPROVED"
    if value in {"DENIED", "REJECTED", "CANCELLED"}:
        return "DENIED"
    return "APPROVED_WITH_LIMITS"


def parse_labels(text: str) -> tuple[str, str]:
    category_match = CATEGORY_RE.search(text or "")
    determination_match = DETERMINATION_RE.search(text or "")
    category = category_match.group(1).upper() if category_match else ""
    determination = normalize_determination(determination_match.group(1)) if determination_match else ""
    return category, determination


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            rows.append(json.loads(line))
    return rows


def main() -> None:
    args = parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required for this evaluation run.")

    supports_bf16 = torch.cuda.is_bf16_supported()
    compute_dtype = torch.bfloat16 if supports_bf16 else torch.float16
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=compute_dtype,
    )

    tokenizer = AutoTokenizer.from_pretrained(args.model_name, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    base_model = AutoModelForCausalLM.from_pretrained(
        args.model_name,
        device_map="auto",
        quantization_config=bnb_config,
        torch_dtype=compute_dtype,
    )
    model = PeftModel.from_pretrained(base_model, str(args.adapter_dir))
    model.eval()

    rows = load_rows(args.val_file)
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]
    predictions: list[dict[str, Any]] = []

    category_correct = 0
    determination_correct = 0
    category_totals = {"I": 0, "II": 0, "III": 0, "IV": 0}
    category_hits = {"I": 0, "II": 0, "III": 0, "IV": 0}

    for idx, row in enumerate(rows, start=1):
        messages = row["messages"]
        target_text = messages[-1]["content"]
        target_category, target_determination = parse_labels(target_text)

        prompt_text = tokenizer.apply_chat_template(
            messages[:-1],
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = tokenizer(prompt_text, return_tensors="pt")
        model_device = next(model.parameters()).device
        inputs = {key: value.to(model_device) for key, value in inputs.items()}

        with torch.no_grad():
            output_ids = model.generate(
                **inputs,
                max_new_tokens=args.max_new_tokens,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )

        generated_ids = output_ids[0][inputs["input_ids"].shape[1] :]
        generated_text = tokenizer.decode(generated_ids, skip_special_tokens=True)
        pred_category, pred_determination = parse_labels(generated_text)

        if pred_category == target_category:
            category_correct += 1
            if target_category in category_hits:
                category_hits[target_category] += 1
        if pred_determination == target_determination:
            determination_correct += 1
        if target_category in category_totals:
            category_totals[target_category] += 1

        predictions.append(
            {
                "index": idx,
                "target_category": target_category,
                "pred_category": pred_category,
                "target_determination": target_determination,
                "pred_determination": pred_determination,
                "generated_text": generated_text,
            }
        )

        if idx % 10 == 0 or idx == len(rows):
            print(f"Evaluated {idx}/{len(rows)}", flush=True)

    total = len(rows)
    category_accuracy = category_correct / total if total else 0.0
    determination_accuracy = determination_correct / total if total else 0.0

    args.predictions_out.parent.mkdir(parents=True, exist_ok=True)
    with args.predictions_out.open("w", encoding="utf-8") as handle:
        for pred in predictions:
            handle.write(json.dumps(pred, ensure_ascii=True))
            handle.write("\n")

    print(f"Validation rows: {total}")
    print(f"Category accuracy: {category_accuracy:.4f} ({category_correct}/{total})")
    print(
        "Determination accuracy: "
        f"{determination_accuracy:.4f} ({determination_correct}/{total})"
    )
    for cat in ("I", "II", "III", "IV"):
        denom = category_totals[cat]
        if denom == 0:
            continue
        acc = category_hits[cat] / denom
        print(f"Category {cat} recall: {acc:.4f} ({category_hits[cat]}/{denom})")
    if category_totals["II"] > 0:
        ii_acc = category_hits["II"] / category_totals["II"]
        print(f"Cat II accuracy: {ii_acc:.4f} ({category_hits['II']}/{category_totals['II']})")
    if category_totals["III"] > 0:
        iii_acc = category_hits["III"] / category_totals["III"]
        print(
            f"Cat III accuracy: {iii_acc:.4f} "
            f"({category_hits['III']}/{category_totals['III']})"
        )
    print(f"Predictions written: {args.predictions_out}")


if __name__ == "__main__":
    main()
