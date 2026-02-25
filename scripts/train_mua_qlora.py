#!/usr/bin/env python3
"""Train a local MUA QLoRA adapter with TRL SFTTrainer."""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from datasets import load_dataset
from peft import LoraConfig, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-file", type=Path, default=Path("mua_train.jsonl"))
    parser.add_argument("--val-file", type=Path, default=Path("mua_val.jsonl"))
    parser.add_argument(
        "--model-name",
        type=str,
        default="meta-llama/Llama-3.2-3B-Instruct",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("mua_lora_adapter"))
    parser.add_argument("--max-seq-length", type=int, default=1024)
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument(
        "--max-steps",
        type=int,
        default=-1,
        help="Optional cap on optimizer steps; -1 means use full epochs.",
    )
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--packing",
        action="store_true",
        help="Enable sequence packing to increase token throughput.",
    )
    parser.add_argument(
        "--eval-strategy",
        type=str,
        default="no",
        choices=["no", "steps", "epoch"],
        help="Trainer evaluation strategy.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required for this QLoRA run.")

    supports_bf16 = torch.cuda.is_bf16_supported()
    compute_dtype = torch.bfloat16 if supports_bf16 else torch.float16

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=compute_dtype,
    )

    print(f"Loading model: {args.model_name}")
    tokenizer = AutoTokenizer.from_pretrained(args.model_name, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    model = AutoModelForCausalLM.from_pretrained(
        args.model_name,
        device_map="auto",
        quantization_config=bnb_config,
        dtype=compute_dtype,
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model)

    lora_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=0.05,
        bias="none",
        target_modules="all-linear",
        task_type="CAUSAL_LM",
    )

    data_files = {"train": str(args.train_file), "validation": str(args.val_file)}
    raw_ds = load_dataset("json", data_files=data_files)

    def to_text(example: dict) -> dict[str, str]:
        text = tokenizer.apply_chat_template(
            example["messages"],
            tokenize=False,
            add_generation_prompt=False,
        )
        return {"text": text}

    train_ds = raw_ds["train"].map(to_text, remove_columns=raw_ds["train"].column_names)
    val_ds = raw_ds["validation"].map(to_text, remove_columns=raw_ds["validation"].column_names)

    print(f"Train examples: {len(train_ds)}")
    print(f"Validation examples: {len(val_ds)}")
    print(
        "Run config: "
        f"seq={args.max_seq_length}, batch={args.batch_size}, grad_accum={args.grad_accum}, "
        f"epochs={args.epochs}, lr={args.learning_rate}, lora_r={args.lora_r}, "
        f"lora_alpha={args.lora_alpha}, packing={args.packing}"
    )

    sft_config = SFTConfig(
        output_dir=str(args.output_dir),
        max_length=args.max_seq_length,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.grad_accum,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        learning_rate=args.learning_rate,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        save_strategy="epoch",
        eval_strategy=args.eval_strategy,
        logging_steps=10,
        bf16=supports_bf16,
        fp16=not supports_bf16,
        gradient_checkpointing=True,
        report_to="none",
        seed=args.seed,
        save_total_limit=3,
        packing=args.packing,
    )

    trainer = SFTTrainer(
        model=model,
        args=sft_config,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        peft_config=lora_config,
        processing_class=tokenizer,
    )

    try:
        trainer.train()
    except RuntimeError as exc:
        if "out of memory" in str(exc).lower():
            raise RuntimeError(
                "CUDA OOM during training. Re-run with --max-seq-length 768."
            ) from exc
        raise

    trainer.save_model(str(args.output_dir))
    tokenizer.save_pretrained(str(args.output_dir))
    print(f"Adapter saved to: {args.output_dir}")


if __name__ == "__main__":
    main()
