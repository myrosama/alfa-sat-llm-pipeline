import json

with open("output/test_2023_dec_intd.json", "r") as f:
    data = json.load(f)

for q in data:
    if q.get("questionNumber") == 22 and q.get("sectionType") == "math":
        print(f"PROMPT:\n{q.get('prompt')}")
        print(f"IMAGE:\n{q.get('imageUrl')}")
