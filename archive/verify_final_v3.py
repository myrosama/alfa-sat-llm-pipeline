import firebase_admin
from firebase_admin import credentials, firestore
import os

# Use absolute path for service account key
SERVICE_ACCOUNT_KEY = "/home/sadrikov49/Desktop/ALFA SAT PROJECT/llm-pipeline/serviceAccountKey.json"

def verify_test(test_id):
    if not firebase_admin._apps:
        cred = credentials.Certificate(SERVICE_ACCOUNT_KEY)
        firebase_admin.initialize_app(cred)
    db = firestore.client()

    print(f"\n--- Verifying Test: {test_id} ---")
    
    test_ref = db.collection("tests").document(test_id)
    test_doc = test_ref.get()
    if not test_doc.exists:
        print(f"❌ Test {test_id} not found!")
        return

    questions_ref = test_ref.collection("questions")
    docs = questions_ref.stream()
    
    modules = {1: [], 2: [], 3: [], 4: []}
    math_issues = []
    ordering_issues = []

    for doc in docs:
        q = doc.to_dict()
        mod = q.get("module")
        num = q.get("questionNumber")
        modules[mod].append(num)
        
        # Check Math formatting
        if mod >= 3:
            content = (str(q.get("prompt") or "") + " " + str(q.get("explanation") or ""))
            if "$" in content:
                math_issues.append(f"M{mod}_Q{num}: Contains raw $ delimiters (should be wrapped in ql-formula)")
            if any(c in content for c in ("=", "+", "-", "/", "^", "\\")) and "ql-formula" not in content:
                math_issues.append(f"M{mod}_Q{num}: Potential missing math formatting (no ql-formula tags)")

        # Check for R&W swaps (rough check: module 1 should be pages 1-11 approx)
        # This is hard without page metadata, but we can check for common "swapped" question sequences.
    
    for mod in range(1, 5):
        nums = sorted(modules[mod])
        expected = 27 if mod <= 2 else 22
        missing = [i for i in range(1, expected + 1) if i not in nums]
        print(f"Module {mod}: Found {len(nums)}/{expected}. Missing: {missing}")

    if math_issues:
        print(f"\n⚠️ Math Formatting Issues ({len(math_issues)}):")
        for issue in math_issues[:10]: print(f"  - {issue}")
    else:
        print("\n✅ Math Formatting looks good (ql-formula tags found)!")

    print("\n--- Verification Complete ---")

if __name__ == "__main__":
    import sys
    test_id = sys.argv[1] if len(sys.argv) > 1 else "test_v3_2_final"
    verify_test(test_id)
