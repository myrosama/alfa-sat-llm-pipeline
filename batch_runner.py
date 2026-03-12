"""
ALFA SAT — Batch PDF Runner (Free Tier)
========================================
Processes all 89 PDFs through the free-tier Gemini pipeline.

Pass 1 (default): Extract-only mode, saves JSON + writes Firestore
  python batch_runner.py --folder ../pdfs/ --resume

Pass 2+: Full mode with critic/gap-filler
  python batch_runner.py --folder ../pdfs/ --resume --full

Usage:
  python batch_runner.py --folder "../pdfs/" --dry-run
  python batch_runner.py --folder "../pdfs/" --resume
"""

import os
import glob
import json
import time
import argparse
from pathlib import Path

from pipeline import process_pdf, load_progress, save_progress
import config


def clean_test_id(filename: str) -> str:
    """Convert PDF filename to a valid Firestore document ID."""
    name = Path(filename).stem
    clean = name.lower()
    for char in ["@", "(", ")", "[", "]", ",", ".", "-", "+", "=", "#"]:
        clean = clean.replace(char, "")
    clean = clean.replace(" ", "_")
    while "__" in clean:
        clean = clean.replace("__", "_")
    clean = clean.strip("_")
    return clean


def clean_test_name(filename: str) -> str:
    """Convert PDF filename to a display name."""
    name = Path(filename).stem
    name = name.split("@")[0].strip()
    return name


def main():
    parser = argparse.ArgumentParser(description="ALFA SAT Batch PDF Runner (Free Tier)")
    parser.add_argument("--folder", type=str, default="../pdfs/",
                        help="Folder containing PDF files")
    parser.add_argument("--resume", action="store_true",
                        help="Skip already-completed PDFs from progress.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and validate but do NOT write to Firestore")
    parser.add_argument("--full", action="store_true",
                        help="Run full pipeline with critic + gap filler (Pass 2+)")
    parser.add_argument("--output-dir", type=str, default="output",
                        help="Directory for JSON backups")
    args = parser.parse_args()

    extract_only = not args.full
    mode_label = "FULL (critic + gap filler)" if args.full else "EXTRACT-ONLY (Pass 1)"

    print("🚀 ALFA SAT Batch Runner — FREE TIER")
    print(f"   Model: {config.GEMINI_MODEL}")
    print(f"   Mode: {mode_label}")
    print(f"   Rate limits: {config.FREE_TIER_RPM} RPM / {config.FREE_TIER_RPD} RPD")
    print(f"   Folder: {args.folder}")
    print(f"   Dry run: {args.dry_run}")
    print(f"   Resume: {args.resume}")

    pdf_files = sorted(glob.glob(os.path.join(args.folder, "*.pdf")))
    if not pdf_files:
        print(f"❌ No PDFs found in {args.folder}")
        return

    print(f"📄 Found {len(pdf_files)} PDFs")

    # Estimate time
    calls_per_pdf = 20 if extract_only else 50
    total_calls = len(pdf_files) * calls_per_pdf
    est_days = max(1, total_calls // config.FREE_TIER_RPD)
    print(f"⏱️  Estimated: ~{total_calls} API calls → ~{est_days} day(s) on free tier")
    print(f"   (Leave running. It auto-sleeps when daily limit is hit.)\n")

    progress = load_progress() if args.resume else {"completed": [], "failed": []}
    skip_count = 0
    success_count = len(progress["completed"])

    for idx, pdf_path in enumerate(pdf_files):
        filename = os.path.basename(pdf_path)

        if args.resume and filename in progress["completed"]:
            skip_count += 1
            continue

        test_name = clean_test_name(filename)
        test_id = clean_test_id(filename)

        print(f"\n{'='*60}")
        print(f"⚙️  [{success_count + 1}/{len(pdf_files)}] {filename}")
        print(f"   ID: {test_id} | Name: {test_name}")
        print(f"{'='*60}")

        try:
            process_pdf(
                pdf_path=pdf_path,
                test_name=test_name,
                test_id=test_id,
                extract_only=extract_only,
                dry_run=args.dry_run,
                output_dir=args.output_dir,
            )

            progress["completed"].append(filename)
            if filename in progress["failed"]:
                progress["failed"].remove(filename)

            save_progress(progress)
            success_count += 1
            print(f"✅ [{success_count}/{len(pdf_files)}] Done: {filename}")

        except KeyboardInterrupt:
            print(f"\n\n⏸️  Interrupted! Progress saved ({success_count} completed).")
            print(f"   Run with --resume to continue where you left off.")
            save_progress(progress)
            return

        except Exception as e:
            print(f"❌ Failed: {filename} — {e}")
            if filename not in progress["failed"]:
                progress["failed"].append(filename)
            save_progress(progress)

    print(f"\n{'='*60}")
    print("🏁 Batch Complete!")
    print(f"   ✅ Success: {success_count}")
    print(f"   ❌ Failed:  {len(progress['failed'])}")
    if skip_count:
        print(f"   ⏭️  Skipped: {skip_count} (already completed)")
    if progress["failed"]:
        print(f"   Failed PDFs: {progress['failed']}")
    print(f"\n   JSON backups saved in: {args.output_dir}/")
    if extract_only:
        print(f"\n   📌 Next step: run `python fix_runner.py --resume` to fix gaps + quality")


if __name__ == "__main__":
    main()
