import firebase_admin
from firebase_admin import credentials, firestore
import config
cred = credentials.Certificate(config.SERVICE_ACCOUNT_KEY)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()
doc = db.collection("tests").document("2023_dec_intd").collection("questions").where("questionNumber", "==", 11).where("sectionType", "==", "math").limit(1).get()
for q in doc:
    print("PROMPT:")
    print(q.to_dict()["prompt"])
    print("OPTIONS:")
    print(q.to_dict()["options"])
