"""
ALFA SAT — Local LLM Batch Runner
===================================
Runs pipeline_local.py on all PDFs in the pdfs/ directory.
Resumes from crashes using a progress file.

Usage:
    cd llm-pipeline
    python batch_runner_local.py

Optional: override vision model
    python batch_runner_local.py --vision-model llava:13b
"""
import os
import glob
import json
import time
import argparse
from pathlib import Path

# Import from the local pipeline (no Gemini dependencies)
from pipeline_local import process_pdf, init_firebase
import config

PDFS_DIR = "../pdfs"
PROGRESS_FILE = "progress/batch_local_progress.json"


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    return {"completed": [], "failed": []}


def save_progress(progress):
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, indent=4)


def clean_test_id(filename: str) -> str:
    name = Path(filename).stem.lower()
    for char in ["@", "(", ")", "[", "]", ",", ".", "-", "+", "="]:
        name = name.replace(char, "")
    name = name.replace(" ", "_")
    while "__" in name:
        name = name.replace("__", "_")
    return name


def main():
    parser = argparse.ArgumentParser(description="ALFA SAT Local LLM Batch Runner")
    parser.add_argument("--vision-model", default=None, help="Ollama vision model to use (overrides config)")
    parser.add_argument("--pdfs-dir", default=PDFS_DIR, help="Directory containing PDFs")
    args = parser.parse_args()

    if args.vision_model:
        config.LOCAL_VISION_MODEL = args.vision_model
        print(f"🔧 Overriding vision model: {args.vision_model}")

    # Quick Ollama connectivity check
    import requests
    endpoint = getattr(config, "LOCAL_LLM_ENDPOINT", "http://localhost:11434/api/generate")
    try:
        r = requests.get("http://localhost:11434", timeout=5)
        print(f"✅ Ollama is running at http://localhost:11434")
    except Exception:
        print("❌ CRITICAL: Cannot reach Ollama at http://localhost:11434")
        print("   Run in a terminal: ollama serve")
        return

    vision_model = getattr(config, "LOCAL_VISION_MODEL", "llava:7b")
    text_model = getattr(config, "LOCAL_TEXT_MODEL", "alfasat:latest")
    print(f"🤖 Vision model : {vision_model}")
    print(f"📝 Text model   : {text_model}")

    pdf_files = sorted(glob.glob(os.path.join(args.pdfs_dir, "*.pdf")))
    if not pdf_files:
        print(f"❌ No PDFs found in {args.pdfs_dir}")
        return

    print(f"\n📄 Found {len(pdf_files)} PDFs to process.")

    progress = load_progress()
    print(f"📈 Progress: {len(progress['completed'])} completed, {len(progress['failed'])} previously failed.\n")

    for idx, pdf_path in enumerate(pdf_files, 1):
        filename = os.path.basename(pdf_path)

        if filename in progress["completed"]:
            print(f"⏭️  Skipping (done): {filename}")
            continue

        print(f"\n{'='*60}")
        print(f"⚙️  PDF {idx}/{len(pdf_files)}: {filename}")
        print(f"{'='*60}")

        test_name = Path(filename).stem
        test_id = clean_test_id(filename)

        try:
            process_pdf(pdf_path, test_name=test_name, test_id=test_id)
            progress["completed"].append(filename)
            if filename in progress["failed"]:
                progress["failed"].remove(filename)
            save_progress(progress)
            print(f"✅ Done: {filename}")
            print(f"📊 Progress: {len(progress['completed'])}/{len(pdf_files)} complete")
            print("⏳ Cooldown 5s before next PDF...")
            time.sleep(5)

        except Exception as e:
            print(f"❌ Failed: {filename} — {e}")
            if filename not in progress["failed"]:
                progress["failed"].append(filename)
            save_progress(progress)
            print("  -> Continuing to next PDF in 10s...")
            time.sleep(10)

    print("\n🏁 Batch complete!")
    print(f"   ✅ Succeeded : {len(progress['completed'])}")
    print(f"   ❌ Failed    : {len(progress['failed'])}")
    if progress["failed"]:
        print("   Failed PDFs:")
        for f in progress["failed"]:
            print(f"     - {f}")


if __name__ == "__main__":
    main()
