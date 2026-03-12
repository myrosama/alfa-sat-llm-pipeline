import json

with open("latest_test.json") as f:
    data = json.load(f)

for q in data.get("questions", []):
    if q["module"] == 2 and q.get("skill") == "Rhetorical Synthesis":
        print(f"M2 Q{q['questionNumber']} Passage:\n", q.get("passage"))
        print(f"M2 Q{q['questionNumber']} Prompt:\n", q.get("prompt"))
        print("-" * 40)
    
    prompt = q.get("prompt", "")
    if "In triangle" in prompt and "RST" in prompt:
        print(f"Triangle Question: M{q['module']} Q{q['questionNumber']}")
        print("Prompt:\n", prompt)
        print("-" * 40)
