#!/usr/bin/env python3
"""Fine-tuning script for agent trajectories exported as JSONL.

Uses ParameterExtractor (qlora) for efficient fine-tuning on consumer GPUs.
Falls back to a simple instruction-tuning loop if transformers is unavailable.

Usage:
    python scripts/fine_tune.py --data-dir finetune_data --output-dir finetune_output --epochs 3 --lr 2e-4
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, Trainer
import torch


def load_trajectories(data_dir: str | Path) -> list[dict]:
    """Load JSONL trajectories from the data directory."""
    data_path = Path(data_dir)
    trajectories: list[dict] = []

    for jsonl_file in data_path.glob("*.jsonl"):
        with open(jsonl_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    trajectories.append(json.loads(line))

    return trajectories


def trajectory_to_conversations(trajectory: dict) -> list[dict[str, str]]:
    """Convert a trajectory dict to conversation format for fine-tuning.

    Args:
        trajectory: Exported trajectory with {"session_id", "app_type", "metadata", "trajectory"}.

    Returns:
        List of {"prompt", "completion"} pairs.
    """
    messages = trajectory["trajectory"]
    conversations: list[dict[str, str]] = []

    # Split trajectory into multi-turn conversations
    # Each turn ends when we have both user->assistant->tool->...->final assistant
    current_turn: list[str] = []

    for msg in messages:
        role = msg["role"]
        content = msg.get("content", "")

        if role == "user":
            if current_turn:
                # Flush previous turn
                conversations.append({
                    "prompt": "\n".join(current_turn),
                    "completion": msg["content"],
                })
            current_turn = [content]
        elif role == "assistant":
            if msg.get("tool_calls"):
                # Multi-step - include tool call as part of conversation
                current_turn.append(f"[assistant] {content}")
                for tc in msg["tool_calls"]:
                    # This will be handled by the tool role message
                    pass
            else:
                current_turn.append(f"[assistant] {content}")
        elif role == "tool":
            current_turn.append(f"[tool:{msg.get('tool_name', '')}] {content}")

    # Final flush
    if current_turn:
        conversations.append({
            "prompt": "\n".join(current_turn[:-1]) if len(current_turn) > 1 else "",
            "completion": current_turn[-1] if current_turn else "",
        })

    return conversations


def prepare_dataset(trajectories: list[dict]) -> list[dict[str, str]]:
    """Prepare all trajectories into training examples."""
    all_conversations: list[dict[str, str]] = []

    for traj in trajectories:
        convs = trajectory_to_conversations(traj)
        all_conversations.extend(convs)

    return all_conversations


def tokenize_conversation(tokenizer, prompt: str, completion: str, max_length: int = 2048) -> dict:
    """Tokenize a conversation pair."""
    full_text = f"<|user|>\n{prompt}<|end|>\n<|assistant|>\n{completion}<|end|>"
    inputs = tokenizer(
        full_text,
        truncation=True,
        max_length=max_length,
        padding="max_length",
        return_tensors="pt",
    )
    return {k: v.squeeze(0) for k, v in inputs.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fine-tune model on agent trajectories")
    parser.add_argument("--data-dir", default="finetune_data", help="Directory with exported JSONL trajectories")
    parser.add_argument("--output-dir", default="finetune_output", help="Output directory for the fine-tuned model")
    parser.add_argument("--base-model", default="Qwen/Qwen2.5-Coder-1.5B", help="Base model to fine-tune")
    parser.add_argument("--epochs", type=int, default=3, help="Number of training epochs")
    parser.add_argument("--lr", type=float, default=2e-4, help="Learning rate")
    parser.add_argument("--batch-size", type=int, default=4, help="Batch size")
    parser.add_argument("--gradient-accumulation", type=int, default=8, help="Gradient accumulation steps")
    parser.add_argument("--max-length", type=int, default=2048, help="Max sequence length")
    parser.add_argument("--lora-r", type=int, default=16, help="LoRA rank")
    parser.add_argument("--lora-alpha", type=int, default=32, help="LoRA alpha")
    parser.add_argument("--lora-dropout", type=float, default=0.05, help="LoRA dropout")
    args = parser.parse_args()

    # Load trajectories
    trajectories = load_trajectories(args.data_dir)
    print(f"Loaded {len(trajectories)} trajectories from {args.data_dir}")

    if not trajectories:
        print("No trajectories found. Run an agent session first and use --export-data.")
        return 1

    # Prepare dataset
    conversations = prepare_dataset(trajectories)
    print(f"Prepared {len(conversations)} training examples")

    # Try to use QLoRA, fall back to full fine-tuning
    try:
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

        print(f"Loading model: {args.base_model}")
        tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            args.base_model,
            load_in_4bit=True,
            device_map="auto",
            trust_remote_code=True,
        )
        model = prepare_model_for_kbit_training(model)

        lora_config = LoraConfig(
            r=args.lora_r,
            lora_alpha=args.lora_alpha,
            target_modules=["q_proj", "v_proj"],
            lora_dropout=args.lora_dropout,
            bias="none",
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, lora_config)
        print(f"Applied LoRA: r={args.lora_r}, alpha={args.lora_alpha}")

    except ImportError:
        print("PEFT not available, falling back to full fine-tuning")
        tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            args.base_model,
            device_map="auto",
            torch_dtype=torch.float16,
            trust_remote_code=True,
        )

    # Tokenize dataset
    print("Tokenizing dataset...")
    tokenized_data = []
    for conv in conversations:
        tokenized = tokenize_conversation(tokenizer, conv["prompt"], conv["completion"], args.max_length)
        tokenized_data.append(tokenized)

    class TrajectoryDataset(torch.utils.data.Dataset):
        def __init__(self, data: list[dict]):
            self.data = data

        def __len__(self):
            return len(self.data)

        def __getitem__(self, idx):
            return self.data[idx]

    dataset = TrajectoryDataset(tokenized_data)

    # Training setup
    training_args = TrainingArguments(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation,
        learning_rate=args.lr,
        fp16=True,
        logging_steps=10,
        save_steps=100,
        save_total_limit=2,
        report_to="none",
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        tokenizer=tokenizer,
    )

    print("Starting training...")
    trainer.train()

    # Save model
    print(f"Saving model to {args.output_dir}")
    model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)

    print("Fine-tuning complete!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
