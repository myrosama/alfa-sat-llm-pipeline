"""
Fine-tune Phi-3.5 Mini for SAT question generation using Unsloth + QLoRA.
Runs locally on RTX 4050 (6GB VRAM) with 4-bit quantization.

Prerequisites:
    pip install "unsloth[cu122-torch250]"

Usage:
    python finetune_sat_model.py --data sat_training_data.jsonl
    python finetune_sat_model.py --data sat_training_data.jsonl --epochs 3

After training:
    The model is exported to GGUF format and an Ollama Modelfile is generated.
    Run: ollama create alfasat-trained -f Modelfile.trained
"""

import argparse
import json
import os

def check_gpu():
    """Check GPU availability and VRAM."""
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            vram_gb = torch.cuda.get_device_properties(0).total_mem / 1e9
            print(f"GPU: {gpu_name} ({vram_gb:.1f} GB VRAM)")
            return True
        else:
            print("No CUDA GPU found. Training will be slow on CPU.")
            return False
    except ImportError:
        print("PyTorch not installed.")
        return False

def load_training_data(data_path):
    """Load JSONL training data."""
    samples = []
    with open(data_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    print(f"Loaded {len(samples)} training samples")
    return samples

def format_for_training(sample):
    """Format into Alpaca-style for Unsloth."""
    instruction = sample.get('instruction', '')
    inp = sample.get('input', '')
    output = sample.get('output', '')
    
    alpaca_template = """Below is an instruction that describes a task, paired with further context. Write a response that appropriately completes the request.

### Instruction:
{instruction}

### Input:
{input}

### Response:
{output}"""
    
    return alpaca_template.format(
        instruction=instruction,
        input=inp if inp else "(no additional input)",
        output=output
    )

def run_finetuning(data_path, epochs=3, output_dir="./sat_model_output"):
    """Main fine-tuning pipeline."""
    
    print("\n=== ALFA SAT Model Fine-Tuning ===\n")
    check_gpu()
    
    # --- Step 1: Load Data ---
    print("\n[1/5] Loading training data...")
    samples = load_training_data(data_path)
    if len(samples) < 10:
        print("WARNING: Very few training samples. Consider processing more PDFs first.")
    
    # --- Step 2: Load Model with Unsloth ---
    print("\n[2/5] Loading Phi-3.5 Mini with 4-bit quantization...")
    from unsloth import FastLanguageModel
    
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name="unsloth/Phi-3.5-mini-instruct",
        max_seq_length=2048,
        dtype=None,  # Auto-detect
        load_in_4bit=True,  # QLoRA - fits in 6GB VRAM
    )
    
    # --- Step 3: Apply LoRA Adapters ---
    print("\n[3/5] Applying LoRA adapters...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,               # LoRA rank (higher = more capacity, more VRAM)
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        lora_alpha=16,
        lora_dropout=0,      # Optimized for Unsloth
        bias="none",
        use_gradient_checkpointing="unsloth",  # 30% less VRAM
        random_state=42,
    )
    
    # --- Step 4: Prepare Dataset ---
    print("\n[4/5] Preparing dataset...")
    from datasets import Dataset
    
    formatted_texts = [format_for_training(s) for s in samples]
    
    # Tokenize
    def tokenize_fn(example):
        return tokenizer(
            example["text"],
            truncation=True,
            max_length=2048,
            padding=False,
        )
    
    dataset = Dataset.from_dict({"text": formatted_texts})
    tokenized_dataset = dataset.map(tokenize_fn, batched=False)
    
    # --- Step 5: Train ---
    print(f"\n[5/5] Training for {epochs} epochs on {len(samples)} samples...")
    from trl import SFTTrainer
    from transformers import TrainingArguments
    
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=2048,
        args=TrainingArguments(
            per_device_train_batch_size=2,  # Small batch for 6GB VRAM
            gradient_accumulation_steps=4,  # Effective batch = 8
            warmup_steps=10,
            num_train_epochs=epochs,
            learning_rate=2e-4,
            fp16=True,
            logging_steps=5,
            output_dir=output_dir,
            optim="adamw_8bit",  # Memory efficient optimizer
            seed=42,
        ),
    )
    
    print("\nTraining started...")
    trainer.train()
    
    # --- Step 6: Export to GGUF for Ollama ---
    print("\n[EXPORT] Saving model as GGUF for Ollama...")
    gguf_dir = os.path.join(output_dir, "gguf")
    model.save_pretrained_gguf(
        gguf_dir,
        tokenizer,
        quantization_method="q5_k_m"  # Good quality/size balance for 6GB
    )
    
    # Generate Modelfile
    modelfile_path = os.path.join(output_dir, "Modelfile.trained")
    gguf_files = [f for f in os.listdir(gguf_dir) if f.endswith('.gguf')]
    if gguf_files:
        gguf_path = os.path.join(gguf_dir, gguf_files[0])
        with open(modelfile_path, 'w') as f:
            f.write(f'FROM {os.path.abspath(gguf_path)}\n\n')
            f.write('PARAMETER temperature 0.4\n')
            f.write('PARAMETER top_p 0.85\n')
            f.write('PARAMETER num_ctx 4096\n\n')
            f.write('SYSTEM """You are ALFA SAT AI, an expert SAT test question generator.\n')
            f.write('Generate original, high-quality SAT-style questions with correct answers and explanations.\n')
            f.write('Output valid JSON matching the ALFA SAT question schema."""\n')
        
        print(f"\n{'='*50}")
        print(f"TRAINING COMPLETE!")
        print(f"{'='*50}")
        print(f"GGUF model: {gguf_path}")
        print(f"Modelfile:  {modelfile_path}")
        print(f"\nTo deploy in Ollama:")
        print(f"  ollama create alfasat-trained -f {modelfile_path}")
        print(f"  ollama run alfasat-trained")
    else:
        print("WARNING: No GGUF file found in output directory")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fine-tune Phi-3.5 for SAT questions")
    parser.add_argument("--data", type=str, required=True, help="Path to JSONL training data")
    parser.add_argument("--epochs", type=int, default=3, help="Number of training epochs")
    parser.add_argument("--output", type=str, default="./sat_model_output", help="Output directory")
    args = parser.parse_args()
    
    run_finetuning(args.data, args.epochs, args.output)
