#!/usr/bin/env python3
"""
Fine-tune Mistral 7B with LoRA for ophthalmology response parsing.

Training configuration:
- Model: Mistral 7B v0.2 Instruct
- Method: QLoRA (4-bit quantization)
- Epochs: 2
- LoRA rank: 16
- Learning rate: 2e-4
- Batch size: 1 (gradient accumulation: 4)

Expected runtime: ~30 minutes on RTX 5070
Expected VRAM: ~10-11GB peak
"""

import torch
import os
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer
from datasets import load_dataset


def setup_model_and_tokenizer(model_name):
    """
    Load base model with 4-bit quantization and tokenizer.
    
    Returns:
        model, tokenizer
    """
    print("="*60)
    print("LOADING BASE MODEL")
    print("="*60)
    print(f"Model: {model_name}")
    print("Quantization: 4-bit NF4 with bfloat16 compute")
    print()
    
    # Configure 4-bit quantization
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True
    )
    
    # Load model
    print("Loading model (this takes ~30 seconds)...")
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
        torch_dtype=torch.bfloat16
    )
    
    # Prepare for k-bit training
    model = prepare_model_for_kbit_training(model)
    
    # Load tokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    
    # Set padding token (Mistral doesn't have one by default)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        model.config.pad_token_id = model.config.eos_token_id
    
    # Report memory usage
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1e9
        reserved = torch.cuda.memory_reserved() / 1e9
        print(f"GPU memory: {allocated:.2f}GB allocated, {reserved:.2f}GB reserved")
    
    print("Model loaded successfully")
    print()
    
    return model, tokenizer


def setup_lora_config(rank=16, alpha=32):
    """
    Configure LoRA adapter parameters.
    
    Args:
        rank: LoRA rank (16 or 32)
        alpha: LoRA alpha scaling factor
    
    Returns:
        LoraConfig
    """
    print("="*60)
    print("CONFIGURING LORA")
    print("="*60)
    print(f"LoRA rank: {rank}")
    print(f"LoRA alpha: {alpha}")
    print("Target modules: q_proj, k_proj, v_proj, o_proj (all attention layers)")
    print()
    
    lora_config = LoraConfig(
        r=rank,
        lora_alpha=alpha,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM"
    )
    
    return lora_config


def load_training_data(train_path, val_path):
    """
    Load training and validation datasets from JSONL files.
    
    Returns:
        train_dataset, val_dataset
    """
    print("="*60)
    print("LOADING TRAINING DATA")
    print("="*60)
    print(f"Training: {train_path}")
    print(f"Validation: {val_path}")
    print()
    
    # Load datasets
    train_dataset = load_dataset('json', data_files=str(train_path), split='train')
    val_dataset = load_dataset('json', data_files=str(val_path), split='train')
    
    print(f"Training examples: {len(train_dataset)}")
    print(f"Validation examples: {len(val_dataset)}")
    print()
    
    # Show sample
    print("Sample training example:")
    print(train_dataset[0])
    print()
    
    return train_dataset, val_dataset


def format_instruction(example):
    """
    Format example into instruction prompt for Mistral.
    
    Mistral format:
    <s>[INST] {instruction}\n\n{input} [/INST] {output}</s>
    """
    instruction = example['instruction']
    input_text = example['input']
    output = example['output']
    
    prompt = f"<s>[INST] {instruction}\n\n{input_text} [/INST] {output}</s>"
    
    return {"text": prompt}


def setup_training_args(output_dir, num_epochs=2):
    """
    Configure training hyperparameters.
    
    Args:
        output_dir: Where to save checkpoints and final model
        num_epochs: Number of training epochs
    
    Returns:
        TrainingArguments
    """
    print("="*60)
    print("TRAINING CONFIGURATION")
    print("="*60)
    print(f"Epochs: {num_epochs}")
    print(f"Batch size: 1")
    print(f"Gradient accumulation: 4 steps (effective batch size: 4)")
    print(f"Learning rate: 2e-4")
    print(f"Output: {output_dir}")
    print()
    
    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=num_epochs,
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=4,
        learning_rate=2e-4,
        lr_scheduler_type="cosine",
        warmup_ratio=0.1,
        logging_steps=10,
        eval_strategy="epoch",
        save_strategy="no",  # Don't save checkpoints during training
        save_total_limit=0,
        fp16=False,
        bf16=True,  # RTX 5070 supports bfloat16
        optim="paged_adamw_8bit",  # Memory-efficient optimizer
        report_to="none",  # No external logging
    )
    
    return training_args


def main():
    """Main fine-tuning pipeline"""
    
    print("\n" + "="*60)
    print("MISTRAL 7B FINE-TUNING FOR OPHTHALMOLOGY")
    print("="*60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Paths
    project_root = Path(__file__).parent.parent.parent
    train_path = project_root / "data" / "training" / "training_data.jsonl"
    val_path = project_root / "data" / "training" / "validation_data.jsonl"
    output_dir = project_root / "data" / "models" / "mistral-7b-ophth-parser"
    
    # Validate input files exist
    if not train_path.exists():
        print(f"ERROR: Training data not found: {train_path}")
        print("Run prepare_training_data.py first")
        return
    
    if not val_path.exists():
        print(f"ERROR: Validation data not found: {val_path}")
        print("Run prepare_training_data.py first")
        return
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Model name
    model_name = "mistralai/Mistral-7B-Instruct-v0.2"
    
    # Load model and tokenizer
    model, tokenizer = setup_model_and_tokenizer(model_name)
    
    # Configure LoRA
    lora_config = setup_lora_config(rank=16, alpha=32)
    
    # Note: LoRA will be applied by SFTTrainer via peft_config parameter
    print("LoRA configuration ready (will be applied by SFTTrainer)")
    print()
    
    # Load datasets
    train_dataset, val_dataset = load_training_data(train_path, val_path)
    
    # Format datasets for instruction tuning
    print("Formatting datasets for instruction tuning...")
    train_dataset = train_dataset.map(format_instruction, remove_columns=train_dataset.column_names)
    val_dataset = val_dataset.map(format_instruction, remove_columns=val_dataset.column_names)
    print("Datasets formatted")
    print()
    
    # Setup training arguments
    training_args = setup_training_args(output_dir, num_epochs=2)
    
    # Create trainer
    print("="*60)
    print("INITIALIZING TRAINER")
    print("="*60)
    
    # Define formatting function to extract 'text' field from examples
    def formatting_func(example):
        """Extract the 'text' field from formatted examples"""
        return example['text']
    
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        processing_class=tokenizer,
        peft_config=lora_config,
        formatting_func=formatting_func,
    )
    print("Trainer initialized")
    print()
    
    # Train
    print("="*60)
    print("STARTING TRAINING")
    print("="*60)
    print("This will take approximately 30 minutes...")
    print("Watch for:")
    print("  - Loss decreasing over time")
    print("  - No CUDA OOM errors")
    print("  - Eval loss after each epoch")
    print()
    
    try:
        trainer.train()
        print()
        print("="*60)
        print("TRAINING COMPLETE")
        print("="*60)
        
    except torch.cuda.OutOfMemoryError:
        print()
        print("="*60)
        print("CUDA OUT OF MEMORY")
        print("="*60)
        print("Try:")
        print("  1. Close other GPU applications")
        print("  2. Reduce LoRA rank to 8")
        print("  3. Increase gradient accumulation to 8")
        return
    
    except Exception as e:
        print()
        print("="*60)
        print("TRAINING FAILED")
        print("="*60)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Save final model
    print()
    print("="*60)
    print("SAVING FINE-TUNED MODEL")
    print("="*60)
    print(f"Saving to: {output_dir}")
    
    # Save adapter weights only (not full model)
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    
    print(f"Model saved successfully")
    print()
    
    # Final memory report
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1e9
        reserved = torch.cuda.memory_reserved() / 1e9
        print(f"Final GPU memory: {allocated:.2f}GB allocated, {reserved:.2f}GB reserved")
    
    print()
    print("="*60)
    print("FINE-TUNING COMPLETE")
    print("="*60)
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    print("Next steps:")
    print(f"  1. Check adapter files in: {output_dir}")
    print(f"  2. Test the fine-tuned model with backend/utils/hf_client.py")
    print(f"  3. Update response_parser.py to load the adapter")
    print()


if __name__ == '__main__':
    main()