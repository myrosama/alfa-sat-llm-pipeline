import json
import firebase_admin
from firebase_admin import credentials, firestore
import sys
import os

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 final_upload.py <json_path> <test_id>")
        return

    json_path = sys.argv[1]
    test_id = sys.argv[2]
    
    KEY_PATH = "serviceAccountKey.json"
    ADMIN_UID = "Kz0qlMcOk9XmPLGytEHm2nOYMhY2"

    if not firebase_admin._apps:
        cred = credentials.Certificate(KEY_PATH)
        firebase_admin.initialize_app(cred)
    
    db = firestore.client()
    
    with open(json_path, 'r', encoding='utf-8') as f:
        questions = json.load(f)

    print(f"🚀 Uploading {len(questions)} questions to Firestore under ID: {test_id}...")
    
    test_ref = db.collection("tests").document(test_id)
    
    # Get current test doc to preserve 'name' if exists, otherwise use a default
    test_doc = test_ref.get()
    if test_doc.exists:
        test_data = test_doc.to_dict()
        name = test_data.get("name", test_id)
        test_category = test_data.get("testCategory", "real_exam")
    else:
        name = test_id.replace("_", " ").title()
        test_category = "real_exam"

    test_ref.set({
        "name": name,
        "testCategory": test_category,
        "visibility": "hide",
        "whitelist": [],
        "createdBy": ADMIN_UID,
        "createdAt": firestore.SERVER_TIMESTAMP,
        "questionCount": len(questions)
    }, merge=True)
    
    # Batch upload questions
    batch = db.batch()
    for i, q in enumerate(questions):
        mod = q.get('module', 1)
        num = q.get('questionNumber', i+1)
        doc_id = f"m{mod}_q{num}"
        q_ref = test_ref.collection("questions").document(doc_id)
        
        # Standardized question data
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
    print(f"🎉 SUCCESS! Test '{name}' ({test_id}) is now live in Firestore.")

if __name__ == "__main__":
    main()
