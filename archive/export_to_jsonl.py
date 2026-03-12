import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
from pathlib import Path

# Config
KEY_PATH = "serviceAccountKey.json"
OUTPUT_FILE = "sat_training_data.jsonl"

def init_firebase():
    """Initialize Firebase Admin SDK."""
    if not os.path.exists(KEY_PATH):
        print(f"❌ Error: {KEY_PATH} not found.")
        return None
        
    try:
        cred = credentials.Certificate(KEY_PATH)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        print(f"❌ Firebase init error: {e}")
        return None

def export_questions(db):
    """Fetch all test questions and format as instruction-response pairs for LLM."""
    print("📥 Fetching tests from Firestore...")
    
    samples = []
    tests_ref = db.collection("tests")
    
    # You can limit to completed tests or just pull all
    for test_doc in tests_ref.stream():
        test_id = test_doc.id
        test_data = test_doc.to_dict()
        
        print(f"  -> Processing test: {test_data.get('name', test_id)}")
        
        qs_ref = tests_ref.document(test_id).collection("questions")
        
        for q_doc in qs_ref.stream():
            q = q_doc.to_dict()
            
            # --- Format for Training ---
            # We want the LLM to learn to GENERATE a question given a domain/skill
            
            domain = q.get("domain", "General")
            skill = q.get("skill", "General")
            mod = q.get("module", 1)
            
            section = "Reading & Writing" if mod <= 2 else "Math"
            
            instruction = f"Generate an ALFA SAT {section} question for the domain '{domain}' testing the skill '{skill}'."
            
            # For Math questions, maybe add an input constraint if it has an image
            inp = ""
            if q.get("imageUrl"):
                inp = "(Assume this question includes a diagram or table)"
                
            # The exact JSON structure we want the LLM to output
            # We clean out firestore-specific meta fields
            output_json = {
                "passage": q.get("passage", ""),
                "prompt": q.get("prompt", ""),
                "explanation": q.get("explanation", ""),
                "imageUrl": q.get("imageUrl", ""),
                "imageWidth": q.get("imageWidth", ""),
                "imagePosition": q.get("imagePosition", ""),
                "domain": domain,
                "skill": skill,
                "format": q.get("format", "mcq")
            }
            
            if q.get("format") == "mcq":
                output_json["options"] = q.get("options", {})
                output_json["correctAnswer"] = q.get("correctAnswer", "")
            else:
                output_json["fillInAnswer"] = q.get("fillInAnswer", "")
                output_json["correctAnswer"] = q.get("correctAnswer", "")
                
            # Clean empty fields
            output_json = {k: v for k, v in output_json.items() if v != ""}
            
            samples.append({
                "instruction": instruction,
                "input": inp,
                "output": json.dumps(output_json, ensure_ascii=False)
            })
            
    print(f"✅ Generated {len(samples)} training samples.")
    return samples

def write_jsonl(samples, outfile):
    """Write samples to JSONL format."""
    print(f"💾 Writing to {outfile}...")
    with open(outfile, 'w', encoding='utf-8') as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + '\n')
    print("✅ Done!")

if __name__ == "__main__":
    db = init_firebase()
    if db:
        data = export_questions(db)
        if data:
            write_jsonl(data, OUTPUT_FILE)
