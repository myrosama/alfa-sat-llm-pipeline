import json
import re

with open("output/test_2023_dec_intd.json", "r") as f:
    data = json.load(f)

print("Checking ql-formula formats:")
found_formulas = 0
for q in data:
    for text in [q.get('prompt', ''), q.get('explanation', '')]:
        formulas = re.findall(r'<span class="ql-formula"[^>]*>.*?</span>', text)
        for fml in formulas:
            if found_formulas < 3:
                print(f"  Sample: {repr(fml)}")
            found_formulas += 1

print(f"\nTotal formulas found: {found_formulas}")

print("\nChecking images:")
for q in data:
    if q.get('imageUrl') or q.get('hasImage'):
        print(f"M{q.get('module')} Q{q.get('questionNumber')} hasImage: {q.get('hasImage')}, imageUrl: {q.get('imageUrl')}")
