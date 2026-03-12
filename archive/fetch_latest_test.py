import firebase_admin
from firebase_admin import credentials, firestore
import json

cred = credentials.Certificate("/home/sadrikov49/Desktop/ALFA SAT PROJECT/llm-pipeline/serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

doc = db.collection("tests").document("1").get()
if doc.exists:
    data = doc.to_dict()
    print(f"Latest Test ID: {doc.id}")
    
    questions = []
    q_docs = db.collection("tests").document("1").collection("questions").stream()
    for q in q_docs:
        questions.append(q.to_dict())
        
    data["questions"] = questions
    print(f"Questions Count: {len(questions)}")
    
    with open("latest_test.json", "w") as f:
        json.dump(data, f, indent=2, default=str)
    print("Saved to latest_test.json")
else:
    print("Not found")
