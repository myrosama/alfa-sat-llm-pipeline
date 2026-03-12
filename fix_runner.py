"""
ALFA SAT — Fix Runner (Pass 2+)
=================================
Reads saved JSON from Pass 1, runs critic + gap filler, updates Firestore.

Run this after batch_runner.py has extracted all PDFs.
You can run this multiple times — each run fixes more issues.

Usage:
  python fix_runner.py --resume
  python fix_runner.py --single 2024_dec_usa
"""

import os
import json
import glob
import time
import argparse
from pathlib import Path

import fitz  # PyMuPDF for re-reading pages during gap fill

from pipeline import (
    call_gemini_vision, pdf_to_images, build_page_type_map,
    write_to_firestore, wrap_formulas_in_quill, init_firebase
)
import quality_agents
import config

FIX_PROGRESS_FILE = os.path.join(os.path.dirname(__file__), "progress", "fix_progress.json")


def load_fix_progress() -> dict:
    if os.path.exists(FIX_PROGRESS_FILE):
        with open(FIX_PROGRESS_FILE, "r") as f:
            return json.load(f)
    return {"fixed": [], "failed": []}


def save_fix_progress(progress: dict):
    os.makedirs(os.path.dirname(FIX_PROGRESS_FILE), exist_ok=True)
    with open(FIX_PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


def fix_test(test_id: str, json_path: str, pdf_folder: str):
    """Run critic + gap filler on a previously extracted test."""
    print(f"\n🔧 Fixing: {test_id}")

    # Load saved extraction
    with open(json_path, "r", encoding="utf-8") as f:
        questions = json.load(f)

    print(f"  📊 Loaded {len(questions)} questions from {json_path}")

    # Check completeness (free — no API calls)
    report = quality_agents.agent1_check_completeness(questions)

    total_gaps = sum(len(g) for g in report["gaps"].values())
    critic_candidates = 0
    for q in questions:
        passage = (q.get("passage") or "").strip()
        prompt = (q.get("prompt") or "").strip()
        mod = q.get("module", 0)
        if passage and passage[-1] not in ['.', '?', '!', '"', "'", '>']:
            critic_candidates += 1
        elif mod in [1, 2] and len(passage) > 0 and len(passage) < 40:
            critic_candidates += 1
        elif "notes" in prompt.lower() and "<ul>" not in passage.lower():
            critic_candidates += 1

    est_calls = total_gaps * 3 + critic_candidates  # rough estimate
    print(f"  📋 Gaps: {total_gaps} | Critic issues: {critic_candidates} | Est. API calls: ~{est_calls}")

    if total_gaps == 0 and critic_candidates == 0:
        print(f"  ✅ {test_id} is already perfect! No fixes needed.")
        return True

    # Find the original PDF for image re-scanning
    pdf_path = _find_pdf_for_test(test_id, pdf_folder)
    if not pdf_path:
        print(f"  ⚠️ Cannot find original PDF for {test_id}. Skipping gap fill (critic only).")
        images = []
        page_map = {}
    else:
        print(f"  📄 Found PDF: {os.path.basename(pdf_path)}")
        images = pdf_to_images(pdf_path)
        page_map = build_page_type_map(pdf_path)
        
    if images and pdf_path:
        # Agent 4: Intelligent Image Extractor
        doc = fitz.open(pdf_path)
        questions = quality_agents.agent4_image_extractor(questions, images, call_gemini_vision, doc)
        doc.close()
        
        # Agent 5: Student Validator
        questions = quality_agents.agent5_student_validator(questions, call_gemini_vision)

    # Agent 3: Critic (fix truncated passages)
    if critic_candidates > 0 and images:
        # Need to tag questions with _batch_start for critic
        for i, q in enumerate(questions):
            if "_batch_start" not in q:
                q["_batch_start"] = i  # approximate
        questions = quality_agents.agent3_critic(questions, images, call_gemini_vision)

    # Agent 2: Gap Filler
    if total_gaps > 0 and images:
        recovered = quality_agents.agent2_fill_gaps(
            report["gaps"], images, page_map, len(images), call_gemini_vision
        )
        questions.extend(recovered)

    # Re-deduplicate
    unique = {}
    for q in questions:
        key = f"M{q.get('module')}_Q{q.get('questionNumber')}"
        if key not in unique or len(str(q)) > len(str(unique[key])):
            unique[key] = q
    final = list(unique.values())

    # Re-wrap formulas
    for q in final:
        q.pop("_batch_start", None)
        q["prompt"] = wrap_formulas_in_quill(q.get("prompt", ""))
        q["explanation"] = wrap_formulas_in_quill(q.get("explanation", ""))
        opts = q.get("options", {})
        if isinstance(opts, dict):
            for k in opts:
                opts[k] = wrap_formulas_in_quill(opts[k])

    # Save updated JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(final, f, indent=2, ensure_ascii=False)
    print(f"  💾 Updated backup: {json_path}")

    # Re-derive test name from test_id
    test_name = test_id.replace("_", " ").title()
    write_to_firestore(test_id, test_name, final, "real_exam")

    # Show final completeness
    quality_agents.agent1_check_completeness(final)
    return True


def _find_pdf_for_test(test_id: str, pdf_folder: str) -> str:
    """Try to find the PDF that matches a test_id."""
    pdfs = glob.glob(os.path.join(pdf_folder, "*.pdf"))
    for pdf_path in pdfs:
        name = Path(pdf_path).stem.lower()
        # Strip @watermark tag (e.g. "@EliteXSAT") — same as batch_runner
        name = name.split("@")[0].strip()
        for char in ["(", ")", "[", "]", ",", ".", "-", "+", "=", "#"]:
            name = name.replace(char, "")
        name = name.replace(" ", "_")
        while "__" in name:
            name = name.replace("__", "_")
        name = name.strip("_")
        if name == test_id or name.replace("_", "") == test_id.replace("_", ""):
            return pdf_path
    return None


def main():
    parser = argparse.ArgumentParser(description="ALFA SAT Fix Runner (Pass 2+)")
    parser.add_argument("--output-dir", default="output",
                        help="Directory with saved JSON files from Pass 1")
    parser.add_argument("--pdf-folder", default="../pdfs/",
                        help="Folder where original PDFs live")
    parser.add_argument("--resume", action="store_true",
                        help="Skip already-fixed tests")
    parser.add_argument("--single", type=str,
                        help="Fix a single test by ID (e.g. 2024_dec_usa)")
    args = parser.parse_args()

    init_firebase()

    print("🔧 ALFA SAT Fix Runner — Pass 2+")
    print(f"   Model: {config.GEMINI_MODEL}")
    print(f"   Output dir: {args.output_dir}")
    print(f"   PDF folder: {args.pdf_folder}")

    if args.single:
        json_path = os.path.join(args.output_dir, f"{args.single}.json")
        if not os.path.exists(json_path):
            print(f"❌ Not found: {json_path}")
            return
        fix_test(args.single, json_path, args.pdf_folder)
        return

    # Process all JSONs
    json_files = sorted(glob.glob(os.path.join(args.output_dir, "*.json")))
    if not json_files:
        print(f"❌ No JSON files in {args.output_dir}/. Run batch_runner.py first!")
        return

    print(f"📄 Found {len(json_files)} tests to fix\n")

    progress = load_fix_progress() if args.resume else {"fixed": [], "failed": []}

    for json_path in json_files:
        test_id = Path(json_path).stem

        if args.resume and test_id in progress["fixed"]:
            continue

        try:
            success = fix_test(test_id, json_path, args.pdf_folder)
            if success:
                progress["fixed"].append(test_id)
                if test_id in progress["failed"]:
                    progress["failed"].remove(test_id)
            save_fix_progress(progress)

        except KeyboardInterrupt:
            print(f"\n⏸️  Interrupted! Progress saved.")
            save_fix_progress(progress)
            return

        except Exception as e:
            print(f"❌ Error fixing {test_id}: {e}")
            if test_id not in progress["failed"]:
                progress["failed"].append(test_id)
            save_fix_progress(progress)

    print(f"\n🏁 Fix run complete!")
    print(f"   ✅ Fixed: {len(progress['fixed'])}")
    print(f"   ❌ Failed: {len(progress['failed'])}")


if __name__ == "__main__":
    main()
