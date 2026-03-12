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
        section = section = "rw" if mod <= 2 else "math"

        # Dynamic page range detection based on page_type_map
        total_pages = len(page_images)
        for q_num in missing_nums:
            if mod <= 2:
                # R&W Modules: Usually pages 0-55
                all_rw_pages = [p for p, t in page_type_map.items() if t == "rw"]
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
                if not all_math_pages or len(all_math_pages) > total_pages * 0.8:
                    all_math_pages = list(range(max(0, total_pages // 3), total_pages))
                mid = len(all_math_pages) // 2
                if q_num >= 18:
                    likely_pages = [p for p in all_math_pages if p >= 75]
                else:
                    likely_pages = [p for p in all_math_pages if p < 75]
                likely_pages = [p for p in likely_pages if p > 25]

            if not likely_pages:
                continue

            print(f"    🔎 Searching for M{mod}_Q{q_num} in pages {[p+1 for p in likely_pages]}...")

            found = False
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
                    if int(q.get("questionNumber", 0)) == q_num:
                        q["module"] = mod
                        q["questionNumber"] = q_num
                        q["sectionType"] = section
                        q["_batch_start"] = page_idx
                        recovered.append(q)
                        print(f"    ✅ Recovered M{mod}_Q{q_num} from page {page_idx+1}")
                        found = True
                        break
                
                time.sleep(config.RATE_LIMIT_DELAY)

            if not found:
                print(f"    ❌ Could not find M{mod}_Q{q_num}")

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
            
        # Red Flag 2: Truncated Sentences
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
        
        start_idx = max(0, page_idx - 1)
        end_idx = min(len(page_images), page_idx + 2)
        overlap_images = page_images[start_idx:end_idx]
        
        critic_prompt = CRITIC_PROMPT.format(
            q_num=q_num,
            flawed_json=json.dumps(q, indent=2)
        )
        
        result = call_gemini_fn(overlap_images, critic_prompt)
        
        if result and isinstance(result, str):
            try:
                json_match = re.search(r'\{.*\}', result, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(0))
                else:
                    result = json.loads(result)
            except:
                result = None

        if result and isinstance(result, dict):
            q.update(result)
            print(f"       ✅ Successfully reconstructed M{mod}_Q{q_num}")
            repaired_questions.append(q)
        else:
            print(f"       ❌ Critic failed to output valid JSON. Keeping original.")
            repaired_questions.append(q)
            
        time.sleep(config.RATE_LIMIT_DELAY)

    print(f"    📊 Agent 3 Finished: Processed {issues_found} potential issues.")
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

The user needs the EXACT, TIGHT bounding box for the mathematical diagram, graph, or data table that answers EXACTLY Question {q_num}.

CRITICAL RULES:
- Find the diagram that belongs to EXACTLY Question {q_num}. Do NOT return the bounding box for a different question's graph. If there are multiple graphs on the page, you must identify the one next to the text for Question {q_num}.
- To help you find the correct graph, here is the text of Question {q_num}: "{q_prompt}". Look for the image closest to this text.
- ONLY locate the pure diagram/image element. 
- DO NOT include ANY question text, labels (like "Question {q_num}"), answer options, or explanations in the box.
- The box should be tight to the edges of the drawing/graph axis.
- Return a JSON object with a single "image_bbox" field.
- "image_bbox": {{ "x0": float, "y0": float, "x1": float, "y1": float }} where coordinates are normalized 0-1000 relative to the page. 
  - (0,0) is top-left, (1000,1000) is bottom-right.
  - x0, y0 is top-left of the image.
  - x1, y1 is bottom-right of the image.
- If no structural image exists for this question, return an empty object {{}}.

Return ONLY a valid JSON object."""

def agent4_image_extractor(questions: List[Dict], page_images: List[bytes], call_gemini_fn, doc=None) -> List[Dict]:
    """
    Scans for questions flagged with needsImageExtraction=true.
    Uses AI vision to find the exact bounding box, then crops and uploads the image.
    Robust search across candidate pages.
    """
    print("\n  🖼️ Agent 4: Intelligent Image Extractor...")
    import fitz

    processed = []
    found_count = 0

    IMAGE_KEYWORDS = [
        "graph", "table", "scatterplot", "diagram", "figure", "coordinate plane", 
        "triangle", "perimeter", "triangle", "circle", "scatter plot", "parallelogram",
        "trapezoid", "rectangle", "square", "ellipse", "data table", "bar chart",
        "box plot", "histogram", "line graph"
    ]
    for q in questions:
        if q.get("imageUrl") or q.get("image_bbox"):
            # If it already has an image or a bbox from Pass 1, we don't NEED to flag it again,
            # but we should still process it if it has an image_bbox.
            if q.get("image_bbox") and not q.get("imageUrl"):
                q["needsImageExtraction"] = True
            continue
            
        text = (q.get("passage", "") + " " + q.get("prompt", "")).lower()
        if any(kw in text for kw in IMAGE_KEYWORDS):
            if "table" in text and "<tr>" in text: # Skip if table is already text-formatted
                continue
            q["needsImageExtraction"] = True

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
        
        image_page = q.get("imagePage", 0)
        start_page = q.get("_start_page", 0) or q.get("_batch_start", 0) or 0
        
        # COMPUTE ABSOLUTE PAGE INDEX
        # _start_page = first page of the batch sent to Gemini
        # imagePage (when > 0) = page number RELATIVE to the batch (1-indexed)
        # When imagePage == 0, we estimate based on question number
        if image_page > 0:
            # imagePage is relative to the batch — convert to absolute
            baseline_page_idx = start_page + image_page - 1
        elif mod >= 3:
            # Math: ~1-2 questions per page, estimate offset from batch start
            baseline_page_idx = start_page + max(0, (q_num - 1) // 2)
        else:
            # R&W: ~3-4 questions per page
            baseline_page_idx = start_page + max(0, (q_num - 1) // 3)
        
        # Clamp to valid range
        total_pages = len(page_images)
        baseline_page_idx = max(0, min(baseline_page_idx, total_pages - 1))

        # ROBUST SEARCH: Check baseline and neighboring pages (wider range for math)
        if mod >= 3:
            pages_to_check = [baseline_page_idx, baseline_page_idx - 1, baseline_page_idx + 1, baseline_page_idx - 2, baseline_page_idx + 2]
        else:
            pages_to_check = [baseline_page_idx, baseline_page_idx - 1, baseline_page_idx + 1]
        pages_to_check = [p for p in pages_to_check if 0 <= p < total_pages]
        pages_to_check = list(dict.fromkeys(pages_to_check))

        print(f"    🔎 Extracting image for M{mod}_Q{q_num} (checking pages {[p+1 for p in pages_to_check]})...")
        
        found_bbox = None
        target_page_idx = -1

        # Phase 1: Try vision model on candidate pages
        for p_idx in pages_to_check:
            # Strip HTML from prompt for cleaner context
            import re
            raw_prompt = re.sub('<[^<]+>', '', q.get("prompt", "")).strip()
            prompt = AGENT4_PROMPT.format(q_num=q_num, q_prompt=raw_prompt)
            try:
                result = call_gemini_fn([page_images[p_idx]], prompt)
                if result and isinstance(result, list) and len(result) > 0:
                    bbox_data = result[0].get("image_bbox")
                elif result and isinstance(result, dict):
                    bbox_data = result.get("image_bbox")
                else:
                    bbox_data = None

                if bbox_data:
                    found_bbox = bbox_data
                    target_page_idx = p_idx
                    break
            except Exception:
                continue
        
        # Phase 2: Fallback to pre-extracted bbox from Pass 1
        if not found_bbox and q.get("image_bbox"):
            found_bbox = q.get("image_bbox")
            target_page_idx = baseline_page_idx
            print(f"       ✨ Using pre-extracted bbox from Pass 1.")

        if not found_bbox:
            print("       ⚠️ Vision model could not find a distinct image.")
            q.pop("needsImageExtraction", None)
            processed.append(q)
            time.sleep(config.RATE_LIMIT_DELAY)
            continue

        # Phase 3: Extraction and Cropping
        try:
            page = doc[target_page_idx]
            rect = page.rect
            bx0 = float(found_bbox.get("x0", 0))
            by0 = float(found_bbox.get("y0", 0))
            bx1 = float(found_bbox.get("x1", 1000))
            by1 = float(found_bbox.get("y1", 1000))
            
            # COORDINATE NORMALIZATION: Always assume 0-1000 unless it looks like 0-1
            if max(bx0, by0, bx1, by1) <= 1.1:
                x0, x1 = bx0 * rect.width, bx1 * rect.width
                y0, y1 = by0 * rect.height, by1 * rect.height
            else:
                x0, x1 = (bx0 / 1000.0) * rect.width, (bx1 / 1000.0) * rect.width
                y0, y1 = (by0 / 1000.0) * rect.height, (by1 / 1000.0) * rect.height

            # Mild padding (5%)
            bw = abs(x1 - x0)
            bh = abs(y1 - y0)
            px0 = max(0.0, min(x0, x1) - bw * 0.05)
            px1 = min(rect.width, max(x0, x1) + bw * 0.05)
            py0 = max(0.0, min(y0, y1) - bh * 0.05)
            py1 = min(rect.height, max(y0, y1) + bh * 0.05)

            if (x1 - x0) < 10 or (y1 - y0) < 10:
                print("       ⚠️ Skipping: Insufficient bounding box size.")
                q.pop("needsImageExtraction", None)
                processed.append(q)
                continue

            crop_rect = fitz.Rect(x0, y0, x1, y1)
            
            # Smart Expansion
            try:
                for path in page.get_drawings():
                    path_rect = fitz.Rect(path["rect"])
                    if 10 < path_rect.width < rect.width * 0.8 and 10 < path_rect.height < rect.height * 0.8:
                        if crop_rect.intersects(path_rect):
                            inter = crop_rect & path_rect
                            if inter.get_area() > path_rect.get_area() * 0.2:
                                crop_rect.include_rect(path_rect)
            except Exception: pass
            
            try:
                for block in page.get_text("blocks"):
                    block_rect = fitz.Rect(block[:4])
                    if block_rect.width < rect.width * 0.3 and block_rect.height < rect.height * 0.1:
                        if crop_rect.intersects(block_rect):
                             inter = crop_rect & block_rect
                             if inter.get_area() > block_rect.get_area() * 0.3:
                                crop_rect.include_rect(block_rect)
            except Exception: pass

            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=crop_rect)
            img_bytes = pix.tobytes("png")
            tg_url = upload_image_to_telegram(img_bytes)
            if tg_url:
                q["imageUrl"] = tg_url
                q["_image_bytes"] = img_bytes
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
    Final QA pass. catch OCR typos.
    """
    print("\n  🎓 Agent 5: Student Validator QA Pass...")
    validated = []
    fixed_count = 0

    for q in questions:
        image_bytes = q.get("_image_bytes")
        image_url = q.get("imageUrl")
        
        if not image_url and not image_bytes:
            validated.append(q)
            continue
            
        q_num = q.get("questionNumber", 0)
        mod = q.get("module", 0)
        
        if not image_bytes:
            validated.append(q)
            continue
            
        print(f"    🧐 Validating text vs image for M{mod}_Q{q_num}...")
        clean_q = {k: v for k, v in q.items() if k != "_image_bytes"}
        prompt = AGENT5_PROMPT.format(json_data=json.dumps(clean_q, indent=2))
        
        try:
            result = call_gemini_fn([image_bytes], prompt)
            if result and (isinstance(result, dict) or (isinstance(result, list) and len(result) > 0)):
                fixed_q = result[0] if isinstance(result, list) else result
                fixed_q["module"] = mod
                fixed_q["questionNumber"] = q_num
                fixed_q["imageUrl"] = image_url
                
                temp_clean = {k: v for k, v in clean_q.items() if k not in ["_batch_start"]}
                temp_fixed = {k: v for k, v in fixed_q.items() if k not in ["_batch_start"]}
                
                if str(temp_fixed) != str(temp_clean):
                    print("       ✅ Validator fixed a typo!")
                    fixed_count += 1
                validated.append(fixed_q)
            else:
                validated.append(clean_q)
        except Exception as e:
            print(f"       ❌ Validation error: {e}")
            validated.append(clean_q)
            
        if "_image_bytes" in q: q.pop("_image_bytes", None)
        time.sleep(config.RATE_LIMIT_DELAY)

    for v in validated: v.pop("_image_bytes", None)
    
    # Final Safety: Bullet points
    for q in validated:
        passage = q.get("passage", "")
        prompt = q.get("prompt", "")
        if "notes" in prompt.lower() and "<ul>" not in passage.lower():
            lines = passage.split("<p>")
            new_passage = []
            in_list = False
            for line in lines:
                text = line.replace("</p>", "").strip()
                if text.startswith(('-', '•', '*', '.')) or (len(text) > 0 and text[0].isdigit() and "." in text[:5]):
                    if not in_list:
                        new_passage.append("<ul>")
                        in_list = True
                    cleaned_text = re.sub(r'^[\-\•\*\.\d\s]+', '', text).strip()
                    new_passage.append(f"<li>{cleaned_text}</li>")
                else:
                    if in_list:
                        new_passage.append("</ul>")
                        in_list = False
                    if text: new_passage.append(f"<p>{text}</p>")
            if in_list: new_passage.append("</ul>")
            q["passage"] = "".join(new_passage)
            
    return validated
