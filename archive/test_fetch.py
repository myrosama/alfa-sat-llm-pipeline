import firebase_admin
from firebase_admin import credentials, firestore
import config
cred = credentials.Certificate(config.SERVICE_ACCOUNT_KEY)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()
doc = db.collection("tests").document("2023_dec_intd").get()
if doc.exists:
    print(f"Found test: {doc.to_dict()}")
    qs = db.collection("tests").document("2023_dec_intd").collection("questions").limit(1).stream()
    for q in qs:
        print(f"Sample Q: {q.to_dict()}")
else:
    print("Test not found!")
