"""
Export Firestore SAT questions into JSONL training data for fine-tuning.
Generates instruction-tuning format compatible with Unsloth/Ollama.

Usage:
    python export_training_data.py
    python export_training_data.py --output sat_training.jsonl
"""

import json
import os
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore

import config

def init_firebase():
    key_path = Path(config.SERVICE_ACCOUNT_KEY)
    if not key_path.exists():
        print(f"❌ Service account key not found: {key_path}")
        return None
    cred = credentials.Certificate(str(key_path))
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    return firestore.client()

def strip_html(text):
    """Remove HTML tags for clean training text, preserve KaTeX data-value."""
    import re
    if not text:
        return ""
    # Extract KaTeX expressions first
    katex_pattern = r'<span class="ql-formula" data-value="([^"]+)">[^<]*</span>'
    text = re.sub(katex_pattern, r'$\1$', text)
    # Remove remaining HTML
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def question_to_training_sample(q_data, test_name, section_type):
    """Convert a Firestore question into an instruction-tuning sample."""
    
    passage = strip_html(q_data.get('passage', ''))
    prompt = strip_html(q_data.get('prompt', ''))
    domain = q_data.get('domain', '')
    skill = q_data.get('skill', '')
    fmt = q_data.get('format', 'mcq')
    correct = q_data.get('correctAnswer', '')
    explanation = strip_html(q_data.get('explanation', ''))
    
    # Build options text
    options_text = ""
    if fmt == 'mcq':
        opts = q_data.get('options', {})
        options_text = "\n".join([
            f"A) {strip_html(opts.get('A', ''))}",
            f"B) {strip_html(opts.get('B', ''))}",
            f"C) {strip_html(opts.get('C', ''))}",
            f"D) {strip_html(opts.get('D', ''))}"
        ])
    
    # --- Format 1: Question Generation (main training objective) ---
    # System: You are a SAT question creator
    # Input: Topic/domain/difficulty hints
    # Output: Full question with passage, prompt, options, answer
    
    gen_instruction = f"Generate a SAT {section_type} question for the domain: {domain}"
    if skill:
        gen_instruction += f", skill: {skill}"
    gen_instruction += f". Format: {fmt}."
    
    output_parts = []
    if passage:
        output_parts.append(f"[Passage]\n{passage}")
    output_parts.append(f"[Question]\n{prompt}")
    if options_text:
        output_parts.append(f"[Options]\n{options_text}")
    output_parts.append(f"[Answer]\n{correct}")
    if explanation:
        output_parts.append(f"[Explanation]\n{explanation}")
    
    gen_sample = {
        "instruction": gen_instruction,
        "input": "",
        "output": "\n\n".join(output_parts)
    }
    
    # --- Format 2: Question Answering (teaches the model SAT reasoning) ---
    answer_instruction = f"Answer this SAT {section_type} question. Show your reasoning."
    
    answer_input_parts = []
    if passage:
        answer_input_parts.append(f"Passage: {passage}")
    answer_input_parts.append(f"Question: {prompt}")
    if options_text:
        answer_input_parts.append(options_text)
    
    answer_output = f"The correct answer is {correct}."
    if explanation:
        answer_output += f"\n\nExplanation: {explanation}"
    
    answer_sample = {
        "instruction": answer_instruction,
        "input": "\n\n".join(answer_input_parts),
        "output": answer_output
    }
    
    return [gen_sample, answer_sample]


def export_all(output_path="sat_training_data.jsonl"):
    """Export all questions from all tests."""
    db = init_firebase()
    if not db:
        return
    
    print("📊 Fetching all tests from Firestore...")
    tests = db.collection('tests').get()
    
    total_samples = 0
    total_questions = 0
    
    with open(output_path, 'w', encoding='utf-8') as f:
        for test_doc in tests:
            test_data = test_doc.to_dict()
            test_name = test_data.get('name', test_doc.id)
            print(f"\n📝 Exporting: {test_name} ({test_doc.id})")
            
            questions = db.collection('tests').document(test_doc.id).collection('questions').get()
            
            for q_doc in questions:
                q_data = q_doc.to_dict()
                total_questions += 1
                
                # Determine section type from module number
                module = q_data.get('module', 1)
                section_type = "Reading & Writing" if module <= 2 else "Math"
                
                # Skip empty questions
                if not q_data.get('prompt'):
                    continue
                
                samples = question_to_training_sample(q_data, test_name, section_type)
                for sample in samples:
                    f.write(json.dumps(sample, ensure_ascii=False) + "\n")
                    total_samples += 1
    
    print(f"\n✅ Export complete!")
    print(f"   Questions: {total_questions}")
    print(f"   Training samples: {total_samples} (2 per question: generation + answering)")
    print(f"   Output: {output_path}")
    print(f"   File size: {os.path.getsize(output_path) / 1024:.1f} KB")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Export SAT questions for LLM training")
    parser.add_argument("--output", type=str, default="sat_training_data.jsonl")
    args = parser.parse_args()
    export_all(args.output)
