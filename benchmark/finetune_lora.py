#!/usr/bin/env python
"""
LoRA fine-tuning script for qwen2.5-coder:1.5b using 4-bit quantization.
Designed to run on CPU with small batches.
"""

import json
import torch
from pathlib import Path
from datasets import Dataset
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    BitsAndBytesConfig,
    TrainingArguments,
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer

TRAINING_FILE = "benchmark_results/rainmaker_training_subset.jsonl"
BASE_MODEL = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
OUTPUT_DIR = "benchmark_results/finetune_lora"
MAX_SEQ_LENGTH = 512
LORA_RANK = 8
LORA_ALPHA = 16
LEARNING_RATE = 2e-4
BATCH_SIZE = 1
GRADIENT_ACCUMULATION = 4
EPOCHS = 3


def load_training_data(path: str) -> Dataset:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            messages = data.get("messages", [])
            if not messages:
                continue
            text = format_messages(messages)
            records.append({"text": text})
    return Dataset.from_list(records)


def format_messages(messages: list[dict]) -> str:
    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            parts.append(f"<|system|>\n{content}")
        elif role == "user":
            parts.append(f"<|user|>\n{content}")
        elif role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                calls_str = json.dumps(tool_calls)
                parts.append(f"<|assistant|>\n{calls_str}")
            else:
                parts.append(f"<|assistant|>\n{content}")
        elif role == "tool":
            parts.append(f"<|tool|>\n{content}")
    return "\n".join(parts)


def main():
    print("Loading training data...")
    dataset = load_training_data(TRAINING_FILE)
    print(f"Loaded {len(dataset)} examples")

    print("Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    print("Loading model with 4-bit quantization...")
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float32,
    )

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        quantization_config=bnb_config,
        device_map="cpu",
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)

    print("Applying LoRA...")
    lora_config = LoraConfig(
        r=LORA_RANK,
        lora_alpha=LORA_ALPHA,
        target_modules=["q_proj", "v_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    print("Setting up trainer...")
    training_args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRADIENT_ACCUMULATION,
        learning_rate=LEARNING_RATE,
        fp16=False,
        logging_steps=10,
        save_strategy="epoch",
        optim="adamw_torch",
        report_to="none",
        remove_unused_columns=False,
    )

    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        peft_config=lora_config,
        formatting_func=None,
        tokenizer=tokenizer,
        args=training_args,
        max_seq_length=MAX_SEQ_LENGTH,
    )

    print("Starting fine-tuning...")
    trainer.train()

    print(f"Saving LoRA adapter to {OUTPUT_DIR}")
    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
    print("Done.")


if __name__ == "__main__":
    main()
