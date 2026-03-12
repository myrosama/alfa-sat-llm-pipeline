import firebase_admin
from firebase_admin import credentials, firestore
import json

cred = credentials.Certificate("/home/sadrikov49/Desktop/ALFA SAT PROJECT/llm-pipeline/serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

test_ref = db.collection("tests").document("test_v3_2_final")
questions = list(test_ref.collection("questions").stream())

print("Analyzing extracted data...")

notes_qs = []
math_qs = []
truncated_qs = []

for q in questions:
    data = q.to_dict()
    mod = data.get("module")
    prompt_text = data.get("prompt", "").lower()
    passage_text = data.get("passage", "").lower()
    
    if mod in [1, 2] and "notes" in prompt_text:
        notes_qs.append(data)
        
    if mod in [3, 4]:
        math_qs.append(data)
        
    if len(passage_text) > 0 and len(passage_text) < 50:
        truncated_qs.append(data)

print(f"\n--- 1. FIRST NOTES QUESTION (Found {len(notes_qs)}) ---")
if notes_qs:
    print(json.dumps(notes_qs[0], indent=2))

print(f"\n--- 2. FIRST TRUNCATED/SHORT PASSAGE QUESTION (Found {len(truncated_qs)}) ---")
if truncated_qs:
    print(json.dumps(truncated_qs[0], indent=2))

print(f"\n--- 3. FIRST MATH QUESTION (Found {len(math_qs)}) ---")
if math_qs:
    print(json.dumps(math_qs[0], indent=2))
