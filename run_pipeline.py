import os
import sys
import time
import json
import subprocess
from pathlib import Path
import datetime

# --- Config ---
PIPELINE_SCRIPT = "pipeline.py"
BATCH_RUNNER = "batch_runner.py"
FIX_RUNNER = "fix_runner.py"
PROGRESS_FILE = "progress.json"
USAGE_FILE = "key_usage.json"
OUTPUT_DIR = "output"

# Enforce virtual environment python if it exists
PYTHON_EXEC = "./venv/bin/python3" if os.path.exists("./venv/bin/python3") else sys.executable

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except:
            return default
    return default

def get_stats():
    progress = load_json(PROGRESS_FILE, {"completed": [], "failed": []})
    usage = load_json(USAGE_FILE, {})
    
    total_completed = len(progress.get("completed", []))
    total_failed = len(progress.get("failed", []))
    
    total_calls_today = sum(k.get("daily_count", 0) for k in usage.values())
    active_keys = len(usage)
    
    return {
        "completed": total_completed,
        "failed": total_failed,
        "calls_today": total_calls_today,
        "active_keys": active_keys,
        "usage": usage
    }

def print_dashboard():
    stats = get_stats()
    clear()
    print("="*60)
    print("🚀 ALFA SAT — UNIFIED PIPELINE DASHBOARD")
    print("="*60)
    print(f"  🏁 Progress: {stats['completed']} PDFs completed | {stats['failed']} failed")
    print(f"  🔑 API Usage: {stats['calls_today']} total calls today across {stats['active_keys']} keys")
    print(f"  🌐 Visibility: PUBLIC (tests will be visible in student app)")
    print("-" * 60)
    
    # Show active keys status
    now_day = datetime.datetime.now().strftime("%Y-%m-%d")
    for key, data in stats['usage'].items():
        if data.get("day") == now_day:
            count = data.get("daily_count", 0)
            prefix = "🟢" if count < 1400 else "🟡" if count < 1500 else "🔴"
            print(f"    {prefix} Key ..{key[-6:]}: {count}/1500 calls")
    
    print("-" * 60)
    print("  [1] Process a SPECIFIC PDF (Pass 1 + Pass 2)")
    print("  [2] Start/RESUME FULL BATCH (89 PDFs)")
    print("      (Safe to stop anytime. Re-run and press 2 to resume.)")
    print("  [3] Process a RANDOM PDF (Pass 1 + Pass 2)")
    print("      (Picks one file you haven't started yet)")
    print("  [4] Run Step 2 Only (Fixes & Images for existing JSONs)")
    print("  [Q] Quit")
    print("=" * 60)

def run_cmd(cmd):
    print(f"\n🏃 Running: {' '.join(cmd)}")
    subprocess.run(cmd)

def main():
    while True:
        print_dashboard()
        choice = input("\n👉 Select an option: ").strip().lower()
        
        if choice == '1':
            all_pdfs = [f.stem for f in Path("./pdfs").glob("*.pdf")]
            print("\n📄 Available PDFs:")
            for i, p in enumerate(all_pdfs):
                print(f"  [{i}] {p}")
            
            idx = input("\n👉 Enter number to run: ").strip()
            try:
                idx = int(idx)
                if 0 <= idx < len(all_pdfs):
                    pdf_id = all_pdfs[idx]
                else:
                    print("❌ Invalid number.")
                    continue
            except ValueError:
                continue
            
            pdf_file = f"./pdfs/{pdf_id}.pdf"
            
            name = pdf_id.split("@")[0].strip()
            clean_id = name.lower()
            for char in ["(", ")", "[", "]", ",", ".", "-", "+", "=", "#"]:
                clean_id = clean_id.replace(char, "")
            clean_id = clean_id.replace(" ", "_")
            while "__" in clean_id:
                clean_id = clean_id.replace("__", "_")
            clean_id = clean_id.strip("_")
            
            print(f"\n🚀 Running Single PDF: {pdf_id}")
            run_cmd([PYTHON_EXEC, PIPELINE_SCRIPT, pdf_file, pdf_id.split("@")[0].strip(), clean_id])
            run_cmd([PYTHON_EXEC, FIX_RUNNER, "--single", clean_id])
            
            # Save to progress.json
            progress = load_json(PROGRESS_FILE, {"completed": [], "failed": []})
            filename = f"{pdf_id}.pdf"
            if filename not in progress["completed"]:
                progress["completed"].append(filename)
                with open(PROGRESS_FILE, "w") as f: json.dump(progress, f, indent=2)
                
            input("\n✅ Done. Press Enter to return to Dashboard...")
            
        elif choice == '2':
            print("\n🚀 Starting Full Batch (Pass 1)...")
            run_cmd([PYTHON_EXEC, BATCH_RUNNER, "--folder", "./pdfs/", "--resume"])
            
            print("\n🛠️ Starting Full Batch Fixes (Pass 2)...")
            run_cmd([PYTHON_EXEC, FIX_RUNNER, "--resume"])
            input("\n✅ Done. Press Enter to return to Dashboard...")
            
        elif choice == '3':
            import random
            progress = load_json(PROGRESS_FILE, {"completed": []})
            completed = set(progress.get("completed", []))
            
            all_pdfs = [f.stem for f in Path("./pdfs").glob("*.pdf")]
            available = [p for p in all_pdfs if p.replace(" ", "_").lower() not in completed]
            
            if not available:
                print("\n🎉 All PDFs in the folder are already completed!")
                time.sleep(2)
                continue
                
            pdf_id = random.choice(available)
            pdf_file = f"./pdfs/{pdf_id}.pdf"
            
            name = pdf_id.split("@")[0].strip()
            clean_id = name.lower()
            for char in ["(", ")", "[", "]", ",", ".", "-", "+", "=", "#"]:
                clean_id = clean_id.replace(char, "")
            clean_id = clean_id.replace(" ", "_")
            while "__" in clean_id:
                clean_id = clean_id.replace("__", "_")
            clean_id = clean_id.strip("_")
            
            print(f"\n🎲 Picked Random PDF: {pdf_id}")
            run_cmd([PYTHON_EXEC, PIPELINE_SCRIPT, pdf_file, pdf_id.split("@")[0].strip(), clean_id])
            run_cmd([PYTHON_EXEC, FIX_RUNNER, "--single", clean_id])
            
            # Save to progress.json
            progress["completed"].append(f"{pdf_id}.pdf")
            with open(PROGRESS_FILE, "w") as f: json.dump(progress, f, indent=2)
            
            input("\n✅ Random PDF Done. Press Enter to return to Dashboard...")

        elif choice == '4':
            print("\n🛠️ Resuming Pass 2 for all extracted JSONs...")
            run_cmd([PYTHON_EXEC, FIX_RUNNER, "--resume"])
            input("\n✅ Done. Press Enter to return to Dashboard...")
            
        elif choice == 'q':
            print("👋 Goodbye!")
            break
        else:
            print("❌ Invalid choice.")
            time.sleep(1)

if __name__ == "__main__":
    main()
