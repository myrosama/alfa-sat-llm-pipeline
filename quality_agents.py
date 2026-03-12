"""
ALFA SAT — V3 Quality Agents
==============================
Three post-extraction agents that ensure 100% question completeness and quality.

Agent 1: Completeness Checker — finds missing question numbers per module
Agent 2: Gap Filler — re-scans specific pages to extract missing questions
Agent 3: Quality Validator — validates structure and content quality
"""

import json
import time
import re
from typing import List, Dict, Tuple, Set

import config
from prompts import GAP_FILL_PROMPT_RW, GAP_FILL_PROMPT_MATH, CRITIC_PROMPT


# ─────────────────────────────────────────────
#  Agent 1: Completeness Checker
# ─────────────────────────────────────────────

EXPECTED_COUNTS = {
    1: 27,   # RW Module 1
    2: 27,   # RW Module 2
    3: 22,   # Math Module 3
    4: 22,   # Math Module 4
}


def agent1_check_completeness(questions: List[Dict]) -> Dict:
    """
    Check that all expected question numbers exist for each module.
    Returns a report with missing questions per module.
    """
    print("\n  🔍 Agent 1: Completeness Check...")

    # Group questions by module
    module_map = {}
    for q in questions:
        # Skip placeholders that say "N/A" or "not provided"
        prompt = q.get("prompt", "")
        passage = q.get("passage", "")
        if prompt == "N/A" or (isinstance(passage, str) and "not provided in the source images" in passage):
            continue

        mod = q.get("module", 0)
        try:
            mod = int(mod)
        except (ValueError, TypeError):
            mod = 0
        if mod not in module_map:
            module_map[mod] = set()

        q_num = q.get("questionNumber", 0)
        try:
            q_num = int(q_num)
        except (ValueError, TypeError):
            q_num = 0
        module_map[mod].add(q_num)

    report = {"total": len(questions), "modules": {}, "gaps": {}}

    for mod in range(1, 5):
        expected = EXPECTED_COUNTS[mod]
        found = module_map.get(mod, set())
        missing = [i for i in range(1, expected + 1) if i not in found]
        section = "R&W" if mod <= 2 else "Math"

        report["modules"][mod] = {
            "section": section,
            "expected": expected,
            "found": len(found),
            "found_numbers": sorted(list(found)),
            "missing": missing,
        }

        if missing:
            report["gaps"][mod] = missing
            print(f"    ⚠️  Module {mod} ({section}): {len(found)}/{expected} — missing {missing}")
        else:
            print(f"    ✅ Module {mod} ({section}): {len(found)}/{expected} — complete!")

    total_missing = sum(len(g) for g in report["gaps"].values())
    print(f"    📊 Total: {len(questions)} found, {total_missing} missing")

    return report


# ─────────────────────────────────────────────
#  Agent 2: Gap Filler
# ─────────────────────────────────────────────

GAP_FILL_PROMPT_RW = """You are extracting a SPECIFIC missing SAT Reading & Writing question.

I need you to find and extract question number {q_num} from this page image.
This is Module {module} of a Digital SAT test.

RULES:
- Find ONLY question {q_num}. Do not return any other questions.
- "passage" = the reading passage associated with this question. Use HTML: <p>, <b>, <i>, <u>.
- "prompt" = the question text only. HTML formatted.
- Options A-D as HTML formatted strings without letter prefixes.
- "correctAnswer" = infer from visual cues, or pick the most defensible answer.
- "domain" and "skill" = must match the SAT taxonomy exactly.
- "explanation" = 2-3 sentence explanation. HTML formatted.
- If you CANNOT find question {q_num}, return an empty array [].

Return JSON array:
[{{"questionNumber": {q_num}, "sectionType": "rw", "passage": "...", "prompt": "...", "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}}, "correctAnswer": "A"|"B"|"C"|"D", "format": "mcq", "domain": "...", "skill": "...", "explanation": "...", "hasImage": false}}]
"""

GAP_FILL_PROMPT_MATH = """You are extracting a SPECIFIC missing SAT Math question.

I need you to find and extract question number {q_num} from this page image.
This is Module {module} of a Digital SAT test.

RULES:
- Find ONLY question {q_num}. Confirm the number in the black box at the top left of the question matches {q_num} exactly.
- If you CANNOT find question {q_num} on this image, return an empty array [].
- "passage" = STIMULUS area. If the question has a preamble, a large centered equation, a function definition (e.g. "The function $f$ is defined by..."), or a data table description, PLACE IT HERE.
- "prompt" = the specific question being asked (e.g. "What is the value of $x$?").
- Options A-D = HTML formatted with KaTeX. NEVER include prefixes like "A)".
- "hasImage" = true if there is a graph, table, or complex geometric figure.

Return JSON array:
[{{"questionNumber": {q_num}, "sectionType": "math", "passage": "<p>...</p>", "prompt": "<p>...</p>", "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}}, "correctAnswer": "A"|"B"|"C"|"D", "fillInAnswer": "...", "format": "mcq", "domain": "...", "skill": "...", "explanation": "...", "hasImage": false}}]
"""


def agent2_fill_gaps(
    gaps: Dict[int, List[int]],
    page_images: List[bytes],
    page_type_map: Dict[int, str],
    total_pages: int,
    call_gemini_fn,
) -> List[Dict]:
    """
    For each missing question, scan likely pages to find and extract it.
    Uses targeted single-question prompts for precision.
    """
    if not gaps:
        print("\n  ✅ Agent 2: No gaps to fill!")
        return []

    total_gaps = sum(len(v) for v in gaps.items())
    print(f"\n  🔧 Agent 2: Filling {total_gaps} gaps...")

    recovered = []

    for mod, missing_nums in gaps.items():
        section = "rw" if mod <= 2 else "math"

        # Dynamic page range detection based on page_type_map
        total_pages = len(page_images)
        for q_num in missing_nums:
            if mod <= 2:
                # R&W Modules: Usually pages 1-55
                all_rw_pages = [p for p, t in page_type_map.items() if t == "rw"]
                # Fallback
                if not all_rw_pages or len(all_rw_pages) > total_pages * 0.8:
                    all_rw_pages = list(range(0, min(60, total_pages)))
                mid = len(all_rw_pages) // 2
                if mod == 1:
                    likely_pages = all_rw_pages[:mid+3]
                else:
                    likely_pages = all_rw_pages[max(0, mid-3):]
                likely_pages = [p for p in likely_pages if p < 65]
            else:
                # Math Modules
                all_math_pages = [p for p, t in page_type_map.items() if t == "math"]
                # Fallback
                if not all_math_pages or len(all_math_pages) > total_pages * 0.8:
                    all_math_pages = list(range(max(0, total_pages // 3), total_pages))
                mid = len(all_math_pages) // 2
                if q_num >= 18:
                    likely_pages = [p for p in all_math_pages if p >= 75] # Force END search for high-numbered qs
                else:
                    likely_pages = [p for p in all_math_pages if p < 75]
                likely_pages = [p for p in likely_pages if p > 25]

            if not likely_pages:
                print(f"    ⚠️  No likely pages found for Module {mod} Q{q_num}")
                continue

            print(f"    🔎 Searching for M{mod}_Q{q_num} in pages {[p+1 for p in likely_pages]}...")

            found = False
            # Heuristic search order: sort by estimated position
            # Math averages 1 question per page in later sections
            qs_per_page = 3.5 if mod <= 2 else 1.0 
            estimated_page_offset = int((q_num - 1) / qs_per_page)
            search_order = []
            if estimated_page_offset < len(likely_pages):
                search_order.append(likely_pages[estimated_page_offset])
            
            for p in likely_pages:
                if p not in search_order:
                    search_order.append(p)

            for page_idx in search_order:
                if page_idx >= len(page_images):
                    continue

                if section == "rw":
                    prompt = GAP_FILL_PROMPT_RW.format(q_num=q_num, module=mod)
                else:
                    prompt = GAP_FILL_PROMPT_MATH.format(q_num=q_num, module=mod)

                result = call_gemini_fn([page_images[page_idx]], prompt)

                if result and len(result) > 0:
                    q = result[0]
                    # Ensure it didn't give us a different question if it failed to find q_num
                    if int(q.get("questionNumber", 0)) == q_num:
                        q["module"] = mod
                        q["questionNumber"] = q_num
                        q["sectionType"] = section
                        q["_batch_start"] = page_idx # Tag for deduplication trust
                        recovered.append(q)
                        print(f"    ✅ Recovered M{mod}_Q{q_num} from page {page_idx+1}")
                        found = True
                        break
                
                time.sleep(config.RATE_LIMIT_DELAY)

            if not found:
                print(f"    ❌ Could not find M{mod}_Q{q_num}")

    print(f"    📊 Recovered {len(recovered)} out of {total_gaps} missing questions")
    return recovered


# ─────────────────────────────────────────────
#  Agent 3: The Critic (Fixes Truncations & Logic)
# ─────────────────────────────────────────────

def agent3_critic(questions: List[Dict], page_images: List[bytes], call_gemini_fn) -> List[Dict]:
    """
    Scans for broken/truncated questions and uses overlapping pages to reconstruct them.
    Returns the fully repaired list of questions.
    """
    print("\n  🧐 Agent 3: Critic Reviewing Question Quality...")
    repaired_questions = []
    issues_found = 0

    for q in questions:
        q_num = q.get("questionNumber", 0)
        mod = q.get("module", 0)
        prompt_text = (q.get("prompt") or "").strip()
        passage_text = (q.get("passage") or "").strip()
        
        needs_repair = False
        reason = ""

        # Red Flag 1: Missing Notes Bullet Points
        if "notes" in prompt_text.lower() and "<ul>" not in passage_text.lower():
            needs_repair = True
            reason = "Missing bullet points in Notes passage"
            
        # Red Flag 2: Truncated Sentences (no ending punctuation)
        elif passage_text and passage_text[-1] not in ['.', '?', '!', '"', "'", '>']:
            needs_repair = True
            reason = f"Truncated passage text: ends with '{passage_text[-5:]}'"

        # Red Flag 3: Abnormally short passage for R&W
        elif mod in [1, 2] and len(passage_text) > 0 and len(passage_text) < 40 and not q.get("hasImage"):
            needs_repair = True
            reason = "Suspiciously short passage"

        if not needs_repair:
            repaired_questions.append(q)
            continue

        issues_found += 1
        page_idx = q.get("_batch_start", 0)
        print(f"    ⚠️  M{mod}_Q{q_num}: {reason}")
        print(f"       Action: Reconstructing using pages {max(1, page_idx)}-{min(len(page_images), page_idx+3)}...")
        
        # Give Critic the current page + next 2 pages to stitch the break
        start_idx = max(0, page_idx - 1)
        end_idx = min(len(page_images), page_idx + 2)
        overlap_images = page_images[start_idx:end_idx]
        
        critic_prompt = CRITIC_PROMPT.format(
            q_num=q_num,
            flawed_json=json.dumps(q, indent=2)
        )
        
        result = call_gemini_fn(overlap_images, critic_prompt)
        
        # Robust JSON extraction (strip markdown if present)
        if result and isinstance(result, str):
            try:
                # Try to find JSON block
                json_match = re.search(r'\{.*\}', result, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(0))
                else:
                    result = json.loads(result)
            except:
                result = None

        if result and isinstance(result, dict):
            # Success
            q.update(result)
            print(f"       ✅ Successfully reconstructed M{mod}_Q{q_num}")
            repaired_questions.append(q)
        else:
            print(f"       ❌ Critic failed to output valid JSON. Keeping original.")
            repaired_questions.append(q)
            
        time.sleep(config.RATE_LIMIT_DELAY)

    print(f"    📊 Agent 3 Finished: Processed {issues_found} potential issues.")
    if issues_found == 0:
        print("    ✅ All questions passed Critic review.")
        
    return repaired_questions


# ─────────────────────────────────────────────
#  Helper: Telegram Upload (Used by Agent 4)
# ─────────────────────────────────────────────

_key_index = 0

def upload_image_to_telegram(img_bytes: bytes) -> str:
    """Upload image to Telegram channel, return tg://file_id URL."""
    try:
        import requests
    except ImportError:
        print("    ⚠️ requests module not found. Skipping Telegram upload.")
        return ""
        
    if not hasattr(config, 'TELEGRAM_BOT_TOKENS') or not hasattr(config, 'TELEGRAM_CHANNEL_ID'):
        print("    ⚠️ Telegram config missing. Needs TELEGRAM_BOT_TOKENS and TELEGRAM_CHANNEL_ID.")
        return ""
        
    if not config.TELEGRAM_BOT_TOKENS or not config.TELEGRAM_CHANNEL_ID:
        return ""

    global _key_index
    token = config.TELEGRAM_BOT_TOKENS[_key_index % len(config.TELEGRAM_BOT_TOKENS)]
    _key_index += 1
    
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    data = {"chat_id": config.TELEGRAM_CHANNEL_ID}
    files = {"photo": ("image.jpg", img_bytes, "image/jpeg")}

    try:
        resp = requests.post(url, data=data, files=files, timeout=10)
        result = resp.json()
        if result.get("ok"):
            file_id = result["result"]["photo"][-1]["file_id"]
            return f"tg://{file_id}"
        else:
            print(f"    ⚠️ Telegram Error: {result.get('description')}")
    except Exception as e:
        print(f"    ⚠️ Telegram upload failed: {e}")
    return ""


# ─────────────────────────────────────────────
#  Agent 4: Intelligent Image Extractor
# ─────────────────────────────────────────────

AGENT4_PROMPT = """You are an expert SAT computer vision agent.

The user needs the EXACT, TIGHT bounding box for the mathematical diagram, graph, or data table that answers Question {q_num}.

RULES:
- ONLY locate the pure diagram/image element. 
- DO NOT include ANY question text, labels (like "Question 15"), answer options, or explanations in the box.
- The box should be tight to the edges of the drawing/graph axis.
- Return a JSON object with a single "image_bbox" field.
- "image_bbox": {{"x0": float, "y0": float, "x1": float, "y1": float}} where coordinates are normalized 0-1000 relative to the page. 
- If no structural image exists for this question, return an empty object {{}}.

Return ONLY a valid JSON object."""

def agent4_image_extractor(questions: List[Dict], page_images: List[bytes], call_gemini_fn, doc=None) -> List[Dict]:
    """
    Scans for questions flagged with needsImageExtraction=true.
    Uses AI vision to find the exact bounding box, then crops and uploads the image.
    Requires the original PyMuPDF `doc` block to perform the actual cropping.
    """
    print("\n  🖼️ Agent 4: Intelligent Image Extractor...")
    import fitz

    processed = []
    found_count = 0

    for q in questions:
        if not q.get("needsImageExtraction") and not q.get("hasImage"):
            processed.append(q)
            continue
            
        if not doc:
            print(f"    ⚠️ M{q.get('module')}_Q{q.get('questionNumber')}: PDF doc not provided, cannot crop.")
            processed.append(q)
            continue

        q_num = q.get("questionNumber", 0)
        mod = q.get("module", 0)
        
        # New 1-indexed imagePage from Pass 1 Native Extraction
        image_page = q.get("imagePage", 0)
        if image_page > 0:
            page_idx = image_page - 1
        else:
            page_idx = q.get("_batch_start", 0) # Fallback baseline

        print(f"    🔎 Extracting image for M{mod}_Q{q_num} on/near page {page_idx+1}...")
        
        # We need to give the AI the page image to find the box
        target_page_idx = page_idx
        if target_page_idx >= len(page_images):
            target_page_idx = len(page_images) - 1
            
        prompt = AGENT4_PROMPT.format(q_num=q_num)
        
        try:
            # We call gemini with a single page to get the precise bbox for THAT page
            result = call_gemini_fn([page_images[target_page_idx]], prompt)
            
            if result and isinstance(result, list) and len(result) > 0:
                bbox_data = result[0].get("image_bbox")
            elif result and isinstance(result, dict):
                bbox_data = result.get("image_bbox")
            else:
                bbox_data = None

            if not bbox_data:
                print("       ⚠️ Vision model could not find a distinct image.")
                q.pop("needsImageExtraction", None)
                processed.append(q)
                time.sleep(config.RATE_LIMIT_DELAY)
                continue
                
            # Normalization and extraction
            page = doc[target_page_idx]
            rect = page.rect
            
            bx0, by0, bx1, by1 = bbox_data.get("x0", 0), bbox_data.get("y0", 0), bbox_data.get("x1", 1), bbox_data.get("y1", 1)
            if max(bx0, by0, bx1, by1) > 1.0:
                if max(bx0, bx1) > 1000 or max(by0, by1) > 1000:
                    bx0 = bx0 / rect.width
                    bx1 = bx1 / rect.width
                    by0 = by0 / rect.height
                    by1 = by1 / rect.height
                else:
                    bx0, by0, bx1, by1 = bx0/1000.0, by0/1000.0, bx1/1000.0, by1/1000.0

            # Mild padding
            bw, bh = bx1 - bx0, by1 - by0
            bx0 = max(0.0, bx0 - bw * 0.05)
            bx1 = min(1.0, bx1 + bw * 0.05)
            by0 = max(0.0, by0 - bh * 0.05)
            by1 = min(1.0, by1 + bh * 0.05)

            x0, x1 = sorted([bx0 * rect.width, bx1 * rect.width])
            y0, y1 = sorted([by0 * rect.height, by1 * rect.height])
            
            if (x1 - x0) < 10 or (y1 - y0) < 10:
                print("       ⚠️ Skipping: Insufficient bounding box size.")
                q.pop("needsImageExtraction", None)
                processed.append(q)
                continue

            crop_rect = fitz.Rect(x0, y0, x1, y1)
            
            # Layer 2: Smart Expansion (paths and blocks)
            # ONLY expand if the element is largely within or very close to the AI-detected box
            try:
                for path in page.get_drawings():
                    path_rect = fitz.Rect(path["rect"])
                    # If diagram path intersects and is not "too big" (over half page)
                    if 10 < path_rect.width < rect.width * 0.8 and 10 < path_rect.height < rect.height * 0.8:
                        if crop_rect.intersects(path_rect):
                            # Only include if the intersection is significant (at least 20% of path)
                            inter = crop_rect & path_rect
                            if inter.get_area() > path_rect.get_area() * 0.2:
                                crop_rect.include_rect(path_rect)
            except Exception: pass
            
            try:
                for block in page.get_text("blocks"):
                    block_rect = fitz.Rect(block[:4])
                    # Only include small text blocks (labels) that are NEAR the crop_rect
                    if block_rect.width < rect.width * 0.3 and block_rect.height < rect.height * 0.1:
                        if crop_rect.intersects(block_rect):
                             # Only include if it overlaps significantly with our target
                             inter = crop_rect & block_rect
                             if inter.get_area() > block_rect.get_area() * 0.3:
                                crop_rect.include_rect(block_rect)
            except Exception: pass

            # Render at 3x scale
            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=crop_rect)
            img_bytes = pix.tobytes("png")
            
            # Upload
            tg_url = upload_image_to_telegram(img_bytes)
            if tg_url:
                q["imageUrl"] = tg_url
                q["_image_bytes"] = img_bytes  # Pass to Agent 5
                print(f"       ✅ Cropped & Uploaded: {tg_url[:35]}...")
                found_count += 1
            else:
                print("       ❌ Failed to upload image.")
                
            q.pop("needsImageExtraction", None)
            processed.append(q)
            
        except Exception as e:
            print(f"       ❌ Image Extraction failed: {e}")
            q.pop("needsImageExtraction", None)
            processed.append(q)
            
        time.sleep(config.RATE_LIMIT_DELAY)

    print(f"    📊 Agent 4 Finished: Extracted {found_count} images.")
    return processed


# ─────────────────────────────────────────────
#  Agent 5: The Student Validator
# ─────────────────────────────────────────────

AGENT5_PROMPT = """You are an incredibly smart high school student taking the SAT. 
You rely heavily on precision.

I am giving you the AI-extracted text of a question, and IF it has an image, I am providing the image too.

YOUR TASK:
1. "Solve" or read the question.
2. If there's an image, does the extracted question text EXACTLY match what is written in the image? Be extremely vigilant for OCR typos in Math (e.g. missing exponents, wrong signs, missing variables).
3. If there are typos, fix them in the JSON output.
4. If the text is perfect, return the exact same JSON back.

FLAWED_JSON:
{json_data}

Return ONLY the corrected JSON object. Do not explain your changes."""

def agent5_student_validator(questions: List[Dict], call_gemini_fn) -> List[Dict]:
    """
    Final QA pass. Simulates a student reading the final extracted text and comparing it 
    against the uploaded image (via bytes) to catch OCR typos, especially critical in Math.
    """
    print("\n  🎓 Agent 5: Student Validator QA Pass...")
    
    validated = []
    fixed_count = 0

    for q in questions:
        image_bytes = q.get("_image_bytes")
        image_url = q.get("imageUrl")
        
        # Only validate questions that have an image attached
        if not image_url and not image_bytes:
            validated.append(q)
            continue
            
        q_num = q.get("questionNumber", 0)
        mod = q.get("module", 0)
        
        if not image_bytes:
            print(f"    🧐 M{mod}_Q{q_num} has image but no local bytes. Skipping validator.")
            validated.append(q)
            continue
            
        print(f"    🧐 Validating text vs image for M{mod}_Q{q_num}...")
        
        # Prepare a clean version of the JSON (without the bytes) to show the model
        clean_q = {k: v for k, v in q.items() if k != "_image_bytes"}
        prompt = AGENT5_PROMPT.format(json_data=json.dumps(clean_q, indent=2))
        
        try:
            # We use the standard gemini vision function with the image bytes
            result = call_gemini_fn([image_bytes], prompt)
            
            if result and isinstance(result, list) and len(result) > 0:
                fixed_q = result[0]
            elif result and isinstance(result, dict):
                fixed_q = result
            else:
                fixed_q = None
                
            if fixed_q:
                # Security: ensure ID stays the same
                fixed_q["module"] = mod
                fixed_q["questionNumber"] = q_num
                fixed_q["sectionType"] = clean_q.get("sectionType", "")
                fixed_q["imageUrl"] = image_url
                
                # Check if it actually changed
                # Remove transient stuff before comparing
                temp_clean = {k: v for k, v in clean_q.items() if k not in ["_batch_start"]}
                temp_fixed = {k: v for k, v in fixed_q.items() if k not in ["_batch_start"]}
                
                if str(temp_fixed) != str(temp_clean):
                    print("       ✅ Validator caught and fixed a typo!")
                    fixed_count += 1
                else:
                    print("       ✨ Perfect match.")
                    
                validated.append(fixed_q)
            else:
                print("       ⚠️ Validator failed to return JSON, keeping original.")
                validated.append(clean_q)
                
        except Exception as e:
            print(f"       ❌ Validation error: {e}")
            validated.append(clean_q)
            
        # Clean up the bytes so they don't get saved to JSON/Firestore
        if "_image_bytes" in q:
            q.pop("_image_bytes", None)
            
        time.sleep(config.RATE_LIMIT_DELAY)

    # Clean up any lingering bytes
    for v in validated:
        v.pop("_image_bytes", None)

    print(f"    📊 Agent 5 Finished: Fixed {fixed_count} OCR typos.")
    
    # ─────────────────────────────────────────────
    #  Final Safety Layer: Bullet Points for Notes
    # ─────────────────────────────────────────────
    for q in validated:
        passage = q.get("passage", "")
        prompt = q.get("prompt", "")
        # If it's a notes question but missing <ul>
        if "notes" in prompt.lower() and "<ul>" not in passage.lower():
            # Heuristic: convert lines starting with dots or dashes to bullet points
            lines = passage.split("<p>")
            new_passage = []
            in_list = False
            for line in lines:
                text = line.replace("</p>", "").strip()
                if text.startswith(('-', '•', '*', '.')) or (len(text) > 0 and text[0].isdigit() and "." in text[:5]):
                    if not in_list:
                        new_passage.append("<ul>")
                        in_list = True
                    # Clean the bullet marker
                    cleaned_text = re.sub(r'^[\-\•\*\.\d\s]+', '', text).strip()
                    new_passage.append(f"<li>{cleaned_text}</li>")
                else:
                    if in_list:
                        new_passage.append("</ul>")
                        in_list = False
                    if text:
                        new_passage.append(f"<p>{text}</p>")
            if in_list:
                new_passage.append("</ul>")
            q["passage"] = "".join(new_passage)
            
    return validated
