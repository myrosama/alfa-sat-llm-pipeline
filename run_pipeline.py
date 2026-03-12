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
    print("  [1] Process SINGLE PDF (Pass 1 + Pass 2)")
    print("  [2] Start/RESUME FULL BATCH (Chains Step 1 & Step 2)")
    print("      (Safe to stop anytime. Re-run and press 2 to resume.)")
    print("  [3] Run Step 2 Only (Fixes & Images for existing JSONs)")
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
            pdf_name = input("Enter PDF test ID (e.g. 2025_oct_int_a): ").strip()
            if not pdf_name: continue
            
            # Pass 1: Pipeline (if needed, but usually we just run the single fix)
            # Actually for a single PDF we should run the whole thing
            run_cmd([sys.executable, PIPELINE_SCRIPT, "--pdf", f"./pdfs/{pdf_name}.pdf"])
            run_cmd([sys.executable, FIX_RUNNER, "--single", pdf_name])
            input("\n✅ Done. Press Enter to return to Dashboard...")
            
        elif choice == '2':
            print("\n🚀 Starting Full Batch (Pass 1)...")
            run_cmd([sys.executable, BATCH_RUNNER, "--folder", "./pdfs/", "--resume"])
            
            print("\n🛠️ Starting Full Batch Fixes (Pass 2)...")
            run_cmd([sys.executable, FIX_RUNNER, "--resume"])
            input("\n✅ Done. Press Enter to return to Dashboard...")
            
        elif choice == '3':
            print("\n🛠️ Resuming Pass 2 for all extracted JSONs...")
            run_cmd([sys.executable, FIX_RUNNER, "--resume"])
            input("\n✅ Done. Press Enter to return to Dashboard...")
            
        elif choice == 'q':
            print("👋 Goodbye!")
            break
        else:
            print("❌ Invalid choice.")
            time.sleep(1)

if __name__ == "__main__":
    main()
