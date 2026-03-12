
import firebase_admin
from firebase_admin import credentials, firestore
import json

def verify_firestore():
    if not firebase_admin._apps:
        cred = credentials.Certificate("/home/sadrikov49/Desktop/ALFA SAT PROJECT/llm-pipeline/serviceAccountKey.json")
        firebase_admin.initialize_app(cred)
    
    db = firestore.client()
    test_id = "test_v3_final_production"
    
    # Get the latest few Math questions
    docs = db.collection("tests").document(test_id).collection("questions").where("module", "==", 3).limit(5).get()
    
    for doc in docs:
        print(f"--- Question {doc.to_dict().get('questionNumber')} (Module {doc.to_dict().get('module')}) ---")
        prompt = doc.to_dict().get("prompt", "")
        print(f"Prompt: {prompt}")
        if "ql-formula" in prompt:
            print("✅ Found Quill formula tag!")
        else:
            print("❌ No Quill formula tag found.")
        print("-" * 40)

if __name__ == "__main__":
    verify_firestore()
