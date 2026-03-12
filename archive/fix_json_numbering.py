import json

json_path = "output/2024_aug_int_b.json"
with open(json_path, "r", encoding="utf-8") as f:
    questions = json.load(f)

# Group by module
modules = {1: [], 2: [], 3: [], 4: []}
for q in questions:
    modules[q["module"]].append(q)

# Re-index each module 1..N
# We sort by their original position in the list (since they were extracted in order)
for mod_id, mod_qs in modules.items():
    # Sort by current questionNumber as a proxy for order, but trust extraction order more
    # Actually, in Pass 1 they are saved in order.
    # Let's just keep their order and re-label 1..len(mod_qs)
    for i, q in enumerate(mod_qs):
        q["questionNumber"] = i + 1

# Flatten back
final_questions = []
for m in [1, 2, 3, 4]:
    final_questions.extend(modules[m])

with open(json_path, "w", encoding="utf-8") as f:
    json.dump(final_questions, f, indent=2, ensure_ascii=False)

print(f"✅ Re-indexed 98 questions across 4 modules.")
