import json
import firebase_admin
from firebase_admin import credentials, firestore
import os

# Paths
KEY_PATH = "/home/sadrikov49/Desktop/ALFA SAT PROJECT/llm-pipeline/serviceAccountKey.json"
JSONL_PATH = "/home/sadrikov49/Desktop/ALFA SAT PROJECT/llm-pipeline/output/test_v3_final_fixed_v2.jsonl"
FAILED_JSONL_PATH = "/home/sadrikov49/Desktop/ALFA SAT PROJECT/llm-pipeline/output/failed/test_v3_final_fixed_v2_failed.jsonl"

# NEW COMPLIANT METADATA
TEST_NAME = "2025 Nov US-A (EliteXSAT)"
# Using a dYYYY_MM style ID to match other visible tests
TEST_ID = "d2025_11_usa_final"
ADMIN_UID = "Kz0qlMcOk9XmPLGytEHm2nOYMhY2"

def main():
    if not firebase_admin._apps:
        cred = credentials.Certificate(KEY_PATH)
        firebase_admin.initialize_app(cred)
    
    db = firestore.client()
    
    questions = []
    
    # Load successful ones
    if os.path.exists(JSONL_PATH):
        with open(JSONL_PATH, 'r') as f:
            for line in f:
                questions.append(json.loads(line))
    
    # Load "failed" ones (which have correct formatting but strict schema issues)
    if os.path.exists(FAILED_JSONL_PATH):
        with open(FAILED_JSONL_PATH, 'r') as f:
            for line in f:
                q = json.loads(line)
                q.pop("_validation_error", None)
                questions.append(q)

    # Sort by module and question number
    questions.sort(key=lambda x: (x.get('module', 1), x.get('questionNumber', 0)))
    
    print(f"🚀 Uploading {len(questions)} questions to Firestore under ID: {TEST_ID}...")
    
    # Create test metadata with ALL required dashboard fields
    test_ref = db.collection("tests").document(TEST_ID)
    test_ref.set({
        "name": TEST_NAME,            # Frontend uses 'name' not 'title'
        "testCategory": "real_exam",   # Frontend uses 'testCategory'
        "visibility": "hide",          # Frontend requires this
        "whitelist": [],               # Frontend requires this
        "createdBy": ADMIN_UID,
        "createdAt": firestore.SERVER_TIMESTAMP,
        "questionCount": len(questions)
    })
    
    # Batch upload questions
    batch = db.batch()
    for i, q in enumerate(questions):
        mod = q.get('module', 1)
        num = q.get('questionNumber', i+1)
        doc_id = f"m{mod}_q{num}"
        q_ref = test_ref.collection("questions").document(doc_id)
        
        # Build standardized question data
        data = {
            "passage": q.get("passage", ""),
            "prompt": q.get("prompt", ""),
            "explanation": q.get("explanation", ""),
            "imageUrl": q.get("imageUrl", ""),
            "imageWidth": q.get("imageWidth", "100%"),
            "imagePosition": q.get("imagePosition", "above"),
            "module": mod,
            "questionNumber": num,
            "domain": q.get("domain", ""),
            "skill": q.get("skill", ""),
            "format": q.get("format", "mcq"),
            "correctAnswer": q.get("correctAnswer", ""),
            "fillInAnswer": q.get("fillInAnswer", ""),
            "lastUpdated": firestore.SERVER_TIMESTAMP
        }
        
        # Handle options for MCQ
        if data["format"] == "mcq":
            opts = q.get("options", {})
            data["options"] = {
                "A": str(opts.get("A", "")),
                "B": str(opts.get("B", "")),
                "C": str(opts.get("C", "")),
                "D": str(opts.get("D", ""))
            }
            
        batch.set(q_ref, data)
        
        if (i + 1) % 50 == 0:
            batch.commit()
            batch = db.batch()
            print(f"  ✅ Uploaded {i+1} questions...")
            
    batch.commit()
    print(f"🎉 SUCCESS! Test '{TEST_NAME}' ({TEST_ID}) is now live in Firestore.")

if __name__ == "__main__":
    main()
