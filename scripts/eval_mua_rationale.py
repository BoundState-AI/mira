#!/usr/bin/env python3
"""Evaluate MUA rationale generation quality with grounding-oriented proxy metrics."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--val-file", type=Path, default=Path("mua_rationale_val.jsonl"))
    parser.add_argument(
        "--model-name",
        type=str,
        default="Qwen/Qwen2.5-3B-Instruct",
    )
    parser.add_argument("--adapter-dir", type=Path, default=Path("mua_rationale_lora_adapter"))
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument(
        "--predictions-out",
        type=Path,
        default=Path("mua_rationale_val_predictions.jsonl"),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional cap on number of validation rows to evaluate (0 = all rows).",
    )
    parser.add_argument(
        "--sample-prints",
        type=int,
        default=3,
        help="How many example generations to print to stdout.",
    )
    return parser.parse_args()


def tokenize_terms(text: str) -> list[str]:
    terms: list[str] = []
    for tok in re.findall(r"[a-z0-9][a-z0-9_/-]{1,}", (text or "").lower()):
        if tok in STOPWORDS:
            continue
        if len(tok) < 3 and not re.search(r"\d", tok):
            continue
        terms.append(tok)
    return terms


def recall_score(reference: str, generated: str) -> float:
    ref_terms = set(tokenize_terms(reference))
    if not ref_terms:
        return 0.0
    gen_terms = set(tokenize_terms(generated))
    return len(ref_terms & gen_terms) / len(ref_terms)


def parse_user_sections(user_prompt: str) -> dict[str, str]:
    match = SECTION_RE.search(user_prompt or "")
    if not match:
        return {
            "deficiency": "",
            "application": "",
            "environment": "",
            "evidence": "",
        }
    return {
        "deficiency": match.group("deficiency").strip(),
        "application": match.group("application").strip(),
        "environment": match.group("environment").strip(),
        "evidence": match.group("evidence").strip(),
    }


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
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
    deficiency_recalls: list[float] = []
    context_recalls: list[float] = []
    evidence_recalls: list[float] = []
    target_overlap_recalls: list[float] = []
    deficiency_hits = 0
    context_hits = 0
    evidence_hits = 0

    for idx, row in enumerate(rows, start=1):
        messages = row["messages"]
        user_prompt = messages[-2]["content"]
        target_text = messages[-1]["content"]
        sections = parse_user_sections(user_prompt)

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
        generated_text = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()

        deficiency_recall = recall_score(sections["deficiency"], generated_text)
        context_recall = recall_score(
            f"{sections['application']} {sections['environment']}", generated_text
        )
        evidence_text = sections["evidence"]
        evidence_required = "No explicit supporting evidence captured" not in evidence_text
        evidence_recall = recall_score(evidence_text, generated_text) if evidence_required else 1.0
        target_overlap = recall_score(target_text, generated_text)

        deficiency_recalls.append(deficiency_recall)
        context_recalls.append(context_recall)
        evidence_recalls.append(evidence_recall)
        target_overlap_recalls.append(target_overlap)

        deficiency_ok = deficiency_recall >= 0.12
        context_ok = context_recall >= 0.10
        evidence_ok = evidence_recall >= 0.10
        if deficiency_ok:
            deficiency_hits += 1
        if context_ok:
            context_hits += 1
        if evidence_ok:
            evidence_hits += 1

        pred = {
            "index": idx,
            "deficiency_recall": deficiency_recall,
            "context_recall": context_recall,
            "evidence_recall": evidence_recall,
            "target_overlap_recall": target_overlap,
            "deficiency_ok": deficiency_ok,
            "context_ok": context_ok,
            "evidence_ok": evidence_ok,
            "generated_text": generated_text,
            "target_text": target_text,
        }
        predictions.append(pred)

        if idx <= args.sample_prints:
            print(f"--- Sample {idx} ---")
            print("Deficiency:", sections["deficiency"][:240])
            print("Generated:", generated_text[:420])
            print("Target:", target_text[:420])
            print(
                "Scores:",
                f"def={deficiency_recall:.3f}",
                f"ctx={context_recall:.3f}",
                f"ev={evidence_recall:.3f}",
                f"ovlp={target_overlap:.3f}",
            )
        if idx % 10 == 0 or idx == len(rows):
            print(f"Evaluated {idx}/{len(rows)}", flush=True)

    total = len(rows)
    avg_def = sum(deficiency_recalls) / total if total else 0.0
    avg_ctx = sum(context_recalls) / total if total else 0.0
    avg_ev = sum(evidence_recalls) / total if total else 0.0
    avg_ovlp = sum(target_overlap_recalls) / total if total else 0.0

    args.predictions_out.parent.mkdir(parents=True, exist_ok=True)
    with args.predictions_out.open("w", encoding="utf-8") as handle:
        for pred in predictions:
            handle.write(json.dumps(pred, ensure_ascii=True))
            handle.write("\n")

    print(f"Validation rows: {total}")
    print(f"Avg deficiency term recall: {avg_def:.4f}")
    print(f"Avg context term recall: {avg_ctx:.4f}")
    print(f"Avg evidence term recall: {avg_ev:.4f}")
    print(f"Avg target overlap recall: {avg_ovlp:.4f}")
    print(f"Deficiency coverage pass rate: {deficiency_hits/total:.4f} ({deficiency_hits}/{total})")
    print(f"Context grounding pass rate: {context_hits/total:.4f} ({context_hits}/{total})")
    print(f"Evidence usage pass rate: {evidence_hits/total:.4f} ({evidence_hits}/{total})")
    print(f"Predictions written: {args.predictions_out}")


if __name__ == "__main__":
    main()
