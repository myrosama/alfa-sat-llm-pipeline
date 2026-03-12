"""
ALFA SAT — Schema Validator
============================
Strict validation of extracted questions before Firestore writes.
Run standalone:  python validate.py --file output/some_test.jsonl
"""

import json
import sys
from typing import Dict, List, Tuple

from prompts import RW_TAXONOMY, MATH_TAXONOMY, get_taxonomy_for_module


def validate_question(q: dict, module: int) -> Tuple[bool, str]:
    """
    Validate a single question dict against the Firestore schema.
    Returns (is_valid, error_message).
    """
    required_fields = [
        "passage", "prompt", "explanation", "format",
        "domain", "skill", "correctAnswer", "options",
        "questionNumber",
    ]

    # --- Check required fields ---
    for field in required_fields:
        if field not in q:
            return False, f"Missing field: {field}"

    # --- Check questionNumber is a valid int ---
    try:
        q_num = int(q["questionNumber"])
        if q_num < 1 or q_num > 27:
            return False, f"questionNumber out of range: {q_num}"
    except (ValueError, TypeError):
        return False, f"Invalid questionNumber: {q['questionNumber']}"

    # --- Check domain/skill against taxonomy ---
    taxonomy = get_taxonomy_for_module(module)

    domain = q["domain"]
    if domain not in taxonomy:
        return False, f"Invalid domain for module {module}: '{domain}'"

    skill = q["skill"]
    if skill not in taxonomy[domain]:
        return False, f"Invalid skill '{skill}' for domain '{domain}'"

    # --- Check format-specific rules ---
    fmt = q["format"]
    if fmt not in ("mcq", "fill-in"):
        return False, f"Invalid format: '{fmt}'"

    if fmt == "mcq":
        # correctAnswer must be A/B/C/D
        ans = q["correctAnswer"]
        if ans not in ("A", "B", "C", "D"):
            return False, f"Invalid correctAnswer for mcq: '{ans}'"

        # Options must have A, B, C, D
        opts = q.get("options", {})
        if not isinstance(opts, dict):
            return False, f"Options is not a dict: {type(opts)}"
        for letter in ("A", "B", "C", "D"):
            if letter not in opts:
                return False, f"Missing option: {letter}"
            # Options should not be empty for mcq
            if not opts[letter] or not str(opts[letter]).strip():
                return False, f"Empty option {letter}"

    elif fmt == "fill-in":
        ans = q["correctAnswer"]
        if not ans or not str(ans).strip():
            return False, "Fill-in correctAnswer is empty"

    # --- Check prompt is not empty ---
    if not q["prompt"] or not str(q["prompt"]).strip():
        return False, "Empty prompt"

    return True, "OK"


def validate_batch(questions: List[Dict], default_module: int = 1) -> Tuple[List[Dict], List[Dict]]:
    """
    Validate a list of questions.
    Returns (valid_questions, invalid_questions_with_errors).
    """
    valid = []
    invalid = []

    for q in questions:
        module = q.get("module", default_module)
        try:
            module = int(module)
        except (ValueError, TypeError):
            module = default_module

        is_valid, error = validate_question(q, module)
        if is_valid:
            valid.append(q)
        else:
            q["_validation_error"] = error
            invalid.append(q)

    return valid, invalid


# ─────────────────────────────────────────────
#  CLI: Validate a .jsonl file
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate ALFA SAT JSONL backup file")
    parser.add_argument("--file", type=str, required=True, help="Path to .jsonl file")
    args = parser.parse_args()

    questions = []
    with open(args.file, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, list):
                    questions.extend(obj)
                else:
                    questions.append(obj)
            except json.JSONDecodeError as e:
                print(f"⚠️  Skipping malformed line: {e}")

    if not questions:
        print("❌ No questions found in file.")
        sys.exit(1)

    print(f"📋 Validating {len(questions)} questions from {args.file}...")

    valid, invalid = validate_batch(questions)

    print(f"\n✅ Valid: {len(valid)}")
    print(f"❌ Invalid: {len(invalid)}")

    if invalid:
        print("\n--- Validation Errors ---")
        for q in invalid:
            q_num = q.get("questionNumber", "?")
            mod = q.get("module", "?")
            err = q.get("_validation_error", "Unknown")
            print(f"  M{mod}_Q{q_num}: {err}")

    sys.exit(0 if not invalid else 1)
