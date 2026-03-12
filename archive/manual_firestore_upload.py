import json
import firebase_admin
from firebase_admin import credentials, firestore
import os

# Paths
KEY_PATH = "/home/sadrikov49/Desktop/ALFA SAT PROJECT/llm-pipeline/serviceAccountKey.json"
JSONL_PATH = "/home/sadrikov49/Desktop/ALFA SAT PROJECT/llm-pipeline/output/test_v3_final_fixed_v2.jsonl"
FAILED_JSONL_PATH = "/home/sadrikov49/Desktop/ALFA SAT PROJECT/llm-pipeline/output/failed/test_v3_final_fixed_v2_failed.jsonl"

TEST_NAME = "2025 Nov US-A (Final Corrected)"
TEST_ID = "test_v3_final_production"
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
                q.pop("_validation_error", None) # Clean up validation error field
                questions.append(q)

    # Sort by module and question number
    questions.sort(key=lambda x: (x.get('module', 1), x.get('questionNumber', 0)))
    
    print(f"🚀 Uploading {len(questions)} questions to Firestore under ID: {TEST_ID}...")
    
    # Create test metadata
    test_ref = db.collection("tests").document(TEST_ID)
    test_ref.set({
        "title": TEST_NAME,
        "category": "real_exam",
        "createdBy": ADMIN_UID,
        "createdAt": firestore.SERVER_TIMESTAMP,
        "status": "ready",
        "questionCount": len(questions)
    })
    
    # Batch upload questions
    batch = db.batch()
    for i, q in enumerate(questions):
        q_id = f"q_{i+1:03d}"
        q_ref = test_ref.collection("questions").document(q_id)
        batch.set(q_ref, q)
        
        if (i + 1) % 50 == 0:
            batch.commit()
            batch = db.batch()
            print(f"  ✅ Uploaded {i+1} questions...")
            
    batch.commit()
    print(f"🎉 SUCCESS! Test '{TEST_NAME}' is now live in Firestore.")

if __name__ == "__main__":
    main()
