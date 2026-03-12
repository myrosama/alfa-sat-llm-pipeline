"""
ALFA SAT — Local LLM Pipeline (Ollama Edition)
================================================
Drop-in replacement for pipeline.py that uses a local Ollama vision model
instead of Google Gemini API. No rate limits. No safety filters. No costs.

Requirements:
  - Ollama running locally: `ollama serve`
  - Vision model pulled: `ollama pull llava:7b`  (or set LOCAL_VISION_MODEL in config)
  - All other deps same as before (pymupdf, firebase-admin, requests, python-dotenv)

Usage:
  python pipeline_local.py --pdf path/to/exam.pdf --test-name "2024 Dec" --test-id "2024_dec"
"""

import os
import json
import time
import base64
import re
from pathlib import Path
from typing import List, Dict, Optional, Any

import fitz  # PyMuPDF
import firebase_admin
from firebase_admin import credentials, firestore
import requests
import cv2
import numpy as np
import config

# --- GLOBALS ---
db = None
_bot_index = 0


# ─────────────────────────────────────────────
#  Firebase
# ─────────────────────────────────────────────

def init_firebase():
    """Initialize Firebase Admin SDK."""
    global db
    if db is not None:
        return db
    key_path = Path(config.SERVICE_ACCOUNT_KEY)
    if not key_path.exists():
        print(f"❌ Firebase service account key not found: {key_path}")
        return None
    try:
        cred = credentials.Certificate(str(key_path))
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        db = firestore.client()
        return db
    except Exception as e:
        print(f"❌ Failed to initialize Firebase: {e}")
        return None


# ─────────────────────────────────────────────
#  PDF → Images
# ─────────────────────────────────────────────

def pdf_to_images(pdf_path: str, dpi: int = config.PAGE_DPI) -> List[tuple[int, bytes]]:
    """
    Convert PDF pages to JPEG byte arrays. 
    Uses OpenCV to slice dense pages into horizontal blocks (e.g. 1 question per block)
    to prevent the Vision LLM from downsampling full pages into blurry, unreadable noise.
    Returns: List of (page_num, image_bytes)
    """
    try:
        doc = fitz.open(pdf_path)
        chunks = []
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            pix = page.get_pixmap(matrix=matrix)
            
            # Convert to OpenCV format
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            if pix.n == 4:
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            elif pix.n == 3:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            # Thresholding to ignore light gray watermarks (like "Eljan Ahmadi SAT")
            # Text is black (0), watermark is light gray (~200), background is white (255)
            _, thresh = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)
            
            # Sum pixels horizontally to find blank rows
            row_sums = np.sum(thresh, axis=1)
            blank_rows = row_sums < 500  # Threshold for noise
            
            splits = [0]
            in_blank = True
            for i, is_blank in enumerate(blank_rows):
                if is_blank and not in_blank:
                    in_blank = True
                elif not is_blank and in_blank:
                    # Transition from blank to text. Only split if we have a sizable chunk
                    if i - splits[-1] > 250:
                        splits.append(max(0, i - 15)) # 15px top-padding
                    in_blank = False
            splits.append(img.shape[0])
            
            for i in range(len(splits) - 1):
                y0, y1 = splits[i], splits[i+1]
                # Filter out tiny useless slices (page numbers, borders)
                if y1 - y0 < 100:
                    continue
                
                chunk_img = img[y0:y1, :]
                success, buffer = cv2.imencode(".jpeg", chunk_img)
                if success:
                    chunks.append((page_num + 1, buffer.tobytes()))
                    
        doc.close()
        return chunks
    except Exception as e:
        print(f"❌ Error rendering PDF: {e}")
        return []


# ─────────────────────────────────────────────
#  Local LLM helpers
# ─────────────────────────────────────────────

VISION_PROMPT_BASE = """You are a precise SAT Test Parsing Agent.

You are analyzing page(s) starting at page START_PAGE of a Digital SAT practice test PDF.
Hint: CONTEXT_HINT

CRITICAL RULES:

1. **SECTION DETECTION (YOU decide):**
   - Look at the page content to determine if this is a Reading & Writing section or a Math section.
   - Reading & Writing pages: text passages, literary excerpts, grammar questions, vocabulary-in-context.
   - Math pages: equations, numbers, graphs, geometry, calculation-based word problems.
   - Set "sectionType" to "rw" for Reading & Writing, or "math" for Math.

2. **REQUIRED JSON SCHEMA FOR EACH QUESTION:**
   - `questionNumber`: (int) The *printed* question number visible on the page (1, 2, 3...).
   - `sectionType`: (string) "rw" or "math".
   - `passage`: (string) The main text/context before the question. For RW, this is the passage. For Math, there is usually no passage, but sometimes there is a common context. Leave "" if none.
   - `prompt`: (string) The actual question text being asked.
   - `options`: (object) Answer choices: {"A": "...", "B": "...", "C": "...", "D": "..."}. If it is a grid-in (math), omit this field or leave empty.
   - `explanation`: (string) Leave "" as this will be generated later.
   - `domain`: (string) The Question Type selector.
     - RW: "Information and Ideas", "Craft and Structure", "Expression of Ideas", "Standard English Conventions".
     - Math: "Algebra", "Advanced Math", "Problem-Solving and Data Analysis", "Geometry and Trigonometry".
   - `skill`: (string) A specific SAT skill string (e.g., "Transitions", "Linear Equations").

3. **PHOTOS / IMAGES / CHARTS (BE VERY STRICT):**
   - If a question has an ACTUAL standalone image, table, chart, or graph, include an `image_bbox` object with keys:
     `x0`, `y0`, `x1`, `y1` (NORMALIZED 0.0-1.0 floats), `page_index` (0-based int), `type` (table/chart/diagram), and `position` ("above" or "below" the prompt).
   - ⚠️ CRITICAL: NEVER draw an `image_bbox` around a text passage, a paragraph, or a normal question. ONLY use it for actual visual data (graphs, tables, pictures). If there is no photo, omit `image_bbox` entirely.

4. **FORMATTING RULES:**
   - **Reading & Writing:** PURE TEXT ONLY. No LaTeX, no KaTeX. For blanks: "________" (8 underscores). Use HTML: <b>, <i>, <u>.
   - **Math:** ALL math MUST use KaTeX wrapper: <span class="ql-formula" data-value="LATEX_CODE">\ufeff<span contenteditable="false"><span class="katex">LATEX_CODE</span></span>\ufeff</span>

5. **GENERAL (MULTIPLE QUESTIONS PER PAGE):**
   - ⚠️ CRITICAL: A single page very often contains 2, 3, or even 4 COMPLETELY INDEPENDENT questions.
   - You MUST extract EACH question as its own separate JSON object in the array.
   - Do NOT merge 3 different questions into 1 giant question. Each question number (e.g. 7, 8, 9) gets its own separate object with its own `passage`, `prompt`, and `options`.
   - If a page is merely DIRECTIONS, TITLE, or ANSWER KEY return an empty array [].
   - Do NOT invent questions or hallucinate.

OUTPUT: Return ONLY a valid JSON array of question objects, no markdown, no commentary."""


def _build_vision_prompt(start_page: int, context_hint: str) -> str:
    """Build the vision prompt safely without using str.format() on JSON-containing template."""
    return (VISION_PROMPT_BASE
            .replace("START_PAGE", str(start_page))
            .replace("CONTEXT_HINT", context_hint))


def _call_ollama(prompt: str, images_b64: List[str] = None, model: str = None) -> str:
    """Low-level call to the Ollama HTTP API. Returns raw text response."""
    endpoint = getattr(config, "LOCAL_LLM_ENDPOINT", "http://localhost:11434/api/generate")
    if model is None:
        model = getattr(config, "LOCAL_VISION_MODEL", "llava:7b")

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 8192,
        }
    }
    if images_b64:
        payload["images"] = images_b64

    resp = requests.post(endpoint, json=payload, timeout=600)  # 10 min — llava is slow on laptop GPU
    resp.raise_for_status()
    return resp.json().get("response", "")


def _parse_json_response(raw: str) -> Any:
    """Strip markdown fences and parse JSON from LLM response."""
    cleaned = raw.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    # Try direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to extract first JSON array or object
    match = re.search(r'(\[.*\]|\{.*\})', cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from response: {cleaned[:200]}")


# ─────────────────────────────────────────────
#  Vision extraction (replaces call_gemini_vision)
# ─────────────────────────────────────────────

def call_local_vision(image_chunks: List[tuple[int, bytes]], context_hint: str) -> List[Dict]:
    """
    Send high-res page chunks to local Ollama vision model to extract questions.
    Processes ONE image chunk at a time to stay within GPU memory on laptop cards.
    """
    model = getattr(config, "LOCAL_VISION_MODEL", "llava:7b")
    endpoint = getattr(config, "LOCAL_LLM_ENDPOINT", "http://localhost:11434/api/generate")
    all_questions: List[Dict] = []

    for img_offset, (page_num, img_bytes) in enumerate(image_chunks):
        prompt = _build_vision_prompt(page_num, context_hint)
        img_b64 = [base64.b64encode(img_bytes).decode("utf-8")]

        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                print(f"    🤖 [{model}] page {page_num} (attempt {attempt})...")
                raw = _call_ollama(prompt, img_b64, model=model)

                data = _parse_json_response(raw)
                if isinstance(data, dict):
                    data = [data]
                if isinstance(data, list):
                    # Tag with relative offset so _batch_start downstream logic works
                    for q in data:
                        q.setdefault("_page_offset", img_offset)
                    all_questions.extend(data)
                    break  # success — move to next image
                print(f"  ⚠️ Unexpected response shape (page {page_num}, attempt {attempt})")

            except requests.exceptions.Timeout:
                print(f"  ⚠️ Timeout page {page_num} attempt {attempt}. Waiting 20s...")
                time.sleep(20)
            except requests.exceptions.ConnectionError:
                print(f"  ❌ Cannot reach Ollama at {endpoint}. Is `ollama serve` running?")
                time.sleep(5)
            except ValueError as e:
                print(f"  ⚠️ JSON parse error page {page_num} attempt {attempt}: {str(e)[:120]}")
                if attempt >= config.MAX_RETRIES:
                    break
            except Exception as e:
                print(f"  ⚠️ Error page {page_num} attempt {attempt}: {str(e)[:120]}")
                if attempt >= config.MAX_RETRIES:
                    break
                time.sleep(3)

    return all_questions


# ─────────────────────────────────────────────
#  AI Critic & Repair (2-Pass Quality Control)
# ─────────────────────────────────────────────

def critic_and_repair_questions(questions: List[Dict], context_hint: str) -> List[Dict]:
    """
    Quality > Quantity. 
    A secondary local text model acts as a harsh critic. It reviews the raw JSON
    extracted by the vision model, checks for cut-off text, bad formatting, and 
    logical errors, and repairs the JSON.
    """
    if not questions:
        return []

    text_model = getattr(config, "LOCAL_TEXT_MODEL", "alfasat:latest")
    print(f"\n  🕵️‍♀️ CRITIC PASS: Using {text_model} to review {len(questions)} extracted questions...")

    # Strip large image byte payloads to save context window
    clean_input = []
    for q in questions:
        # Keep bbox for reference but strip raw bytes if they exist
        clean_q = {k: v for k, v in q.items() if k not in ["imageUrl"]}
        clean_input.append(clean_q)

    # Process in small chunks so the critic has room to think
    CHUNK = 5
    repaired_all = []

    for i in range(0, len(clean_input), CHUNK):
        chunk = clean_input[i:i + CHUNK]
        original_chunk = questions[i:i + CHUNK]
        
        prompt = f"""You are the ALFA SAT Chief Quality Control Officer.
Your job is to review the following JSON array of SAT questions extracted from a {context_hint}.
The initial extraction often makes mistakes: cutting off text midway, breaking JSON structures, or missing answer choices.

CRITIC CHECKLIST:
1. Is the `passage` text cut off mid-sentence? Try to logically complete it or fix broken trailing characters. Note: Math often has an empty passage, but sometimes has a context passage.
2. Is the `prompt` (question text) complete and correctly formatted?
3. Are the `options` (A, B, C, D) complete? Are any missing or clearly truncated?
4. Are `domain` and `skill` populated realistically?
5. Formatting: Does the Math section use KaTeX properly? Has KaTeX bled into Reading & Writing by mistake?
6. Are there any hanging strings or broken JSON syntax?

Review the questions and return a REPAIRED, perfectly valid JSON sub-array matching the original length.
DO NOT ADD NEW QUESTIONS. DO NOT DELETE QUESTIONS. Just fix the broken text and ensure all required schema fields (passage, prompt, options, domain) are present and well-formed.

RAW EXTRACTED JSON:
{json.dumps(chunk, indent=2)}

OUTPUT:
Return ONLY the repaired JSON array. No markdown fences, no explanations. Just valid JSON."""

        for attempt in range(1, 3):
            try:
                print(f"    🔎 Reviewing chunk {i//CHUNK + 1} (attempt {attempt})...")
                raw = _call_ollama(prompt, model=text_model)
                fixed_chunk = _parse_json_response(raw)
                
                if isinstance(fixed_chunk, list) and len(fixed_chunk) > 0:
                    # Merge fixes while retaining necessary underlying data like image_bbox
                    for orig, fixed in zip(original_chunk, fixed_chunk):
                        for k, v in fixed.items():
                            if k not in ["image_bbox", "imageUrl", "_page_offset"]:
                                orig[k] = v
                    repaired_all.extend(original_chunk)
                    print(f"      ✅ Chunk {i//CHUNK + 1} repaired and approved.")
                    break
                else:
                    raise ValueError("Critic returned invalid structure.")
            except Exception as e:
                print(f"      ⚠️ Critic error on chunk {i//CHUNK + 1}: {e}")
                if attempt == 2:
                    print("      ➡️ Keeping original chunk due to critic failure.")
                    repaired_all.extend(original_chunk)

    return repaired_all


# ─────────────────────────────────────────────
#  Generate missing questions (replaces Gemini version)
# ─────────────────────────────────────────────

def generate_missing_questions(missing_nums: List[int], module: int, is_math: bool) -> List[Dict]:
    """Use local text LLM to generate SAT-style fill-in questions for gaps."""
    if not missing_nums:
        return []

    text_model = getattr(config, "LOCAL_TEXT_MODEL", "alfasat:latest")
    print(f"  ⚠️ Missing {len(missing_nums)} questions in M{module}: {missing_nums}. Generating with {text_model}...")

    prompt = f"""You are a precise SAT Test Generator.
Generate {len(missing_nums)} missing questions for SAT Module {module} ({'Math' if is_math else 'EBRW'}).
The missing question numbers are: {missing_nums}.

CRITICAL INSTRUCTIONS:
1. Generate authentic SAT-style questions.
2. Format rules:
   - No KaTeX in EBRW.
   - Mandatory KaTeX wrapping for ALL math expressions in Math sections.
3. Return ONLY a valid JSON array matching this schema per question:
   {{
     "questionNumber": <int>,
     "module": {module},
     "sectionType": "{"math" if is_math else "rw"}",
     "passage": "",
     "prompt": "<question text>",
     "format": "mcq",
     "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
     "correctAnswer": "A",
     "explanation": "...",
     "domain": "<domain>",
     "skill": "<skill>"
   }}
Output ONLY the JSON array. No markdown fences."""

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            raw = _call_ollama(prompt, model=text_model)
            data = _parse_json_response(raw)
            if isinstance(data, dict):
                data = [data]
            if isinstance(data, list):
                for i, q in enumerate(data):
                    if i < len(missing_nums):
                        q["questionNumber"] = missing_nums[i]
                        q["module"] = module
                return data
        except Exception as e:
            print(f"  ⚠️ Generation attempt {attempt} failed: {e}")
            if attempt >= config.MAX_RETRIES:
                break
            time.sleep(3)

    print(f"  ❌ Failed to generate missing questions after {config.MAX_RETRIES} attempts.")
    return []


# ─────────────────────────────────────────────
#  QA Self-Review (replaces Gemini version)
# ─────────────────────────────────────────────

def review_and_fix_questions(questions: List[Dict]) -> List[Dict]:
    """Local LLM QA pass to fix KaTeX/formatting issues."""
    if not questions:
        return questions

    text_model = getattr(config, "LOCAL_TEXT_MODEL", "alfasat:latest")
    print(f"\n  🔍 Starting local QA Self-Review for {len(questions)} questions ({text_model})...")

    # Strip images and truncate passages to save context
    qa_input = []
    for q in questions:
        clean_q = {k: v for k, v in q.items() if k not in ["imageUrl", "imageWidth", "imagePosition"]}
        if clean_q.get("passage") and len(clean_q["passage"]) > 500:
            clean_q["passage"] = clean_q["passage"][:500] + "... [TRUNCATED]"
        qa_input.append(clean_q)

    # Process in chunks of 20 to stay within context window
    CHUNK = 20
    fixed_all = []
    for i in range(0, len(qa_input), CHUNK):
        chunk = qa_input[i:i + CHUNK]
        original_chunk = questions[i:i + CHUNK]

        prompt = f"""You are ALFA SAT's strict Quality Assurance Reviewer.
Review this JSON array of SAT questions and FIX any formatting errors.

CHECK FOR:
1. Math sections (modules 3 & 4) MUST have KaTeX wrapping <span class="ql-formula"...> around ALL math.
2. Reading (modules 1 & 2) MUST NOT have any KaTeX.
3. Ensure 'options' object has A, B, C, D properties without answer-letter prefixes like "A) ".
4. Ensure correct answer is a single letter A, B, C, or D.

Return ONLY the FULL JSON array with fixes applied. No markdown fences.

QUESTIONS:
{json.dumps(chunk, indent=2)}"""

        try:
            raw = _call_ollama(prompt, model=text_model)
            fixed_chunk = _parse_json_response(raw)
            if isinstance(fixed_chunk, list) and len(fixed_chunk) == len(original_chunk):
                for orig, fixed in zip(original_chunk, fixed_chunk):
                    for k, v in fixed.items():
                        if k not in ["passage", "imageUrl", "imageWidth", "imagePosition", "image_bbox"]:
                            orig[k] = v
                fixed_all.extend(original_chunk)
                print(f"  ✅ QA chunk {i // CHUNK + 1} done.")
            else:
                print(f"  ⚠️ QA chunk {i // CHUNK + 1}: mismatched length. Keeping originals.")
                fixed_all.extend(original_chunk)
        except Exception as e:
            print(f"  ⚠️ QA chunk {i // CHUNK + 1} failed: {e}. Keeping originals.")
            fixed_all.extend(original_chunk)

    return fixed_all


# ─────────────────────────────────────────────
#  Module assignment (identical to pipeline.py)
# ─────────────────────────────────────────────

def assign_modules_via_restart(questions: List[Dict]) -> List[Dict]:
    """Assign module numbers using question-number-restart detection."""
    if not questions:
        return questions

    rw_qs = [q for q in questions if q.get("sectionType") == "rw"]
    math_qs = [q for q in questions if q.get("sectionType") == "math"]
    unknown_qs = [q for q in questions if q.get("sectionType") not in ("rw", "math")]

    print(f"  RW: {len(rw_qs)}, Math: {len(math_qs)}, Unknown: {len(unknown_qs)}")

    for q in unknown_qs:
        prompt_text = q.get("prompt", "") + " " + q.get("passage", "")
        if "ql-formula" in prompt_text or any(kw in prompt_text.lower() for kw in ["equation", "solve", "graph", "x =", "f(x)"]):
            q["sectionType"] = "math"
            math_qs.append(q)
        else:
            q["sectionType"] = "rw"
            rw_qs.append(q)

    _detect_restart_and_assign(rw_qs, mod1=1, mod2=2)
    _detect_restart_and_assign(math_qs, mod1=3, mod2=4)

    all_qs = rw_qs + math_qs
    for q in all_qs:
        q.pop("_batch_start", None)
        q.pop("sectionType", None)
    return all_qs


def _detect_restart_and_assign(questions: List[Dict], mod1: int, mod2: int):
    """Sort by extraction order, detect restart, assign modules."""
    if not questions:
        return
    questions.sort(key=lambda q: (q.get("_batch_start", 0), q.get("questionNumber", 0)))

    restart_index = -1
    max_q_num = 0
    for i, q in enumerate(questions):
        try:
            q_num = int(q.get("questionNumber", 0) or 0)
        except (ValueError, TypeError):
            q_num = 0
        if max_q_num >= 5 and q_num <= 3 and q_num < max_q_num * 0.5:
            restart_index = i
            break
        max_q_num = max(max_q_num, q_num)

    section_name = "RW" if mod1 <= 2 else "Math"
    if restart_index == -1:
        for q in questions:
            q["module"] = mod1
        print(f"  {section_name}: No restart detected → all {len(questions)} questions → Module {mod1}")
    else:
        for i, q in enumerate(questions):
            q["module"] = mod1 if i < restart_index else mod2
        print(f"  {section_name}: Restart at index {restart_index} → M{mod1}:{restart_index}, M{mod2}:{len(questions)-restart_index}")


# ─────────────────────────────────────────────
#  Telegram image upload (unchanged)
# ─────────────────────────────────────────────

def upload_image_to_telegram(img_bytes: bytes) -> Optional[str]:
    """Upload image to Telegram channel, return tg://file_id URL."""
    global _bot_index
    if not config.TELEGRAM_BOT_TOKENS or not config.TELEGRAM_CHANNEL_ID:
        return None
    token = config.TELEGRAM_BOT_TOKENS[_bot_index % len(config.TELEGRAM_BOT_TOKENS)]
    _bot_index += 1
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    files = {"photo": ("question.png", img_bytes, "image/png")}
    data = {"chat_id": config.TELEGRAM_CHANNEL_ID}
    for attempt in range(2):
        try:
            response = requests.post(url, files=files, data=data, timeout=30)
            result = response.json()
            if result.get("ok"):
                file_id = result["result"]["photo"][-1]["file_id"]
                return f"tg://{file_id}"
            else:
                print(f"  ⚠️ Telegram Error: {result.get('description')}")
        except Exception as e:
            print(f"  ⚠️ Telegram upload failed: {e}")
            time.sleep(2)
    return None


# ─────────────────────────────────────────────
#  Firestore write (unchanged)
# ─────────────────────────────────────────────

def write_to_firestore(test_id: str, test_name: str, questions: List[Dict], category: str):
    """Write test and questions to Firestore."""
    if not db:
        init_firebase()
    if not db:
        return
    print(f"\n📤 Writing to Firestore: {test_id} ({len(questions)} questions)")

    test_ref = db.collection("tests").document(test_id)
    test_ref.set({
        "name": test_name,
        "createdAt": firestore.SERVER_TIMESTAMP,
        "status": "completed",
        "visibility": "hide",
        "whitelist": [],
        "createdBy": config.ADMIN_UID,
        "testCategory": category,
        "questionCount": len(questions),
        "totalPages": 98
    })

    batch = db.batch()
    batch_count = 0
    for q in questions:
        q_num = q.get("questionNumber", 0)
        mod = q.get("module", 1)
        doc_id = f"m{mod}_q{q_num}"
        doc_ref = test_ref.collection("questions").document(doc_id)

        data = {
            "passage": q.get("passage", ""),
            "prompt": q.get("prompt", ""),
            "explanation": q.get("explanation", ""),
            "imageUrl": q.get("imageUrl", ""),
            "imageWidth": q.get("imageWidth", "100%"),
            "imagePosition": q.get("imagePosition", "above"),
            "module": mod,
            "questionNumber": q_num,
            "domain": q.get("domain", ""),
            "skill": q.get("skill", ""),
            "format": q.get("format", "mcq"),
            "lastUpdated": firestore.SERVER_TIMESTAMP
        }

        if data["format"] == "mcq":
            opts = q.get("options", {})
            parsed_opts = {"A": "", "B": "", "C": "", "D": ""}
            if isinstance(opts, dict):
                parsed_opts["A"] = str(opts.get("A", opts.get("a", "")))
                parsed_opts["B"] = str(opts.get("B", opts.get("b", "")))
                parsed_opts["C"] = str(opts.get("C", opts.get("c", "")))
                parsed_opts["D"] = str(opts.get("D", opts.get("d", "")))
            elif isinstance(opts, list) and len(opts) >= 4:
                for i, letter in enumerate(["A", "B", "C", "D"]):
                    if isinstance(opts[i], dict):
                        possible = [str(v) for v in opts[i].values() if isinstance(v, str) and v.upper() != letter]
                        parsed_opts[letter] = max(possible, key=len) if possible else ""
                    else:
                        parsed_opts[letter] = str(opts[i])
            for k in parsed_opts:
                val = parsed_opts[k].strip()
                if val.startswith(f"{k}) ") or val.startswith(f"{k}. "):
                    parsed_opts[k] = val[3:].strip()
                elif val.startswith(f"{k})") or val.startswith(f"{k}."):
                    parsed_opts[k] = val[2:].strip()
            data["options"] = parsed_opts
            ans = str(q.get("correctAnswer", "A")).strip().upper()
            data["correctAnswer"] = ans if ans in ["A", "B", "C", "D"] else "A"
        else:
            data.pop("options", None)
            data["fillInAnswer"] = q.get("fillInAnswer", "")
            data["correctAnswer"] = str(q.get("correctAnswer", ""))

        batch.set(doc_ref, data)
        batch_count += 1
        if batch_count >= 400:
            batch.commit()
            batch = db.batch()
            batch_count = 0

    if batch_count > 0:
        batch.commit()
    print(f"✅ Test '{test_name}' written successfully.")


# ─────────────────────────────────────────────
#  Main PDF processing (same structure as pipeline.py)
# ─────────────────────────────────────────────

def process_pdf(pdf_path: str, test_name: str, test_id: str):
    """Process a single PDF end-to-end using a local vision LLM."""
    print(f"\n📄 Processing: {test_name}")
    print(f"📁 Path: {pdf_path}")
    vision_model = getattr(config, "LOCAL_VISION_MODEL", "llava:7b")
    print(f"🤖 Vision model: {vision_model}")

    print("  -> Slicing PDF into isolated question rectangles using OpenCV...")
    chunk_tuples = pdf_to_images(pdf_path)
    if not chunk_tuples:
        return
    print(f"  -> Generated {len(chunk_tuples)} high-res question blocks.")

    all_questions = []
    total = len(chunk_tuples)

    # Note: BATCH_SIZE controls how many chunks we process before saving a checkpoint
    for chunk_start in range(0, total, config.BATCH_SIZE):
        chunk_end = min(chunk_start + config.BATCH_SIZE, total)
        current_chunks = chunk_tuples[chunk_start:chunk_end]
        
        chunk_pages = [page for page, _ in current_chunks]
        pages_str = f"pages {min(chunk_pages)} to {max(chunk_pages)}"

        if chunk_start < total * 0.45:
            context_hint = f"Likely Reading & Writing section, {pages_str}"
        else:
            context_hint = f"Likely Math section, {pages_str}"

        print(f"\n  🕵️ Analyzing block {chunk_start+1} to {chunk_end} ({pages_str})...")
        questions = call_local_vision(current_chunks, context_hint)

        if questions:
            # ---> AI CRITIC PASS: Review and Repair raw extraction before finalizing
            questions = critic_and_repair_questions(questions, context_hint)

            for q in questions:
                q_num = q.get("questionNumber")
                sec = q.get("sectionType", "?")
                if q_num:
                    print(f"    ✅ Confirmed {sec.upper()}_Q{q_num}")

                q["_batch_start"] = chunk_start

                # Handle image cropping if model identified a bounding box
                if "image_bbox" in q:
                    bbox = q["image_bbox"]
                    try:
                        p_idx = bbox.get("page_index", 0)
                        if p_idx < len(current_chunks):
                            print(f"      📸 Cropping image for Q{q_num}...")
                            doc = fitz.open(pdf_path)
                            actual_page_num = current_chunks[p_idx][0] - 1
                            if 0 <= actual_page_num < len(doc):
                                page = doc[actual_page_num]
                                rect = page.rect

                                bx0, by0, bx1, by1 = bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"]
                                if max(bx0, by0, bx1, by1) > 1.0:
                                    bx0, by0, bx1, by1 = bx0/1000.0, by0/1000.0, bx1/1000.0, by1/1000.0

                                x0, x1 = sorted([bx0 * rect.width, bx1 * rect.width])
                                y0, y1 = sorted([by0 * rect.height, by1 * rect.height])
                                width = x1 - x0
                                height = y1 - y0

                                if width <= 0.01 or height <= 0.01:
                                    print(f"      ⚠️ Skipping: zero-area bbox")
                                    del q["image_bbox"]
                                else:
                                    pad_x = max(10.0, width * 0.08)
                                    pad_y = max(15.0, height * 0.15)
                                    crop_rect = fitz.Rect(
                                        max(0, x0 - pad_x), max(0, y0 - pad_y),
                                        min(rect.width, x1 + pad_x), min(rect.height, y1 + pad_y)
                                    )
                                    matrix = fitz.Matrix(3.0, 3.0)
                                    pix = page.get_pixmap(matrix=matrix, clip=crop_rect)
                                    img_bytes = pix.tobytes("png")
                                    tg_url = upload_image_to_telegram(img_bytes)
                                    if tg_url:
                                        q["imageUrl"] = tg_url
                                        q["imageWidth"] = "100%"
                                        img_type = bbox.get("type", "diagram")
                                        q["imagePosition"] = q.get("imagePosition", "below" if img_type in ["table", "chart"] else "above")
                                        print(f"      ☁️ Uploaded: {tg_url}")
                            doc.close()
                    except Exception as e:
                        print(f"      ⚠️ Failed to crop image: {e}")
                    q.pop("image_bbox", None)

            all_questions.extend(questions)
        else:
            print(f"    ⚠️ No questions found for {pages_str}")

        # Small pause between chunks (no rate limits needed, but avoid GPU OOM)
        time.sleep(1)

    if not all_questions:
        print("❌ No questions extracted from entire PDF.")
        return

    # Assign modules via question-number-restart detection
    print("\n  🧠 Assigning modules via content detection...")
    all_questions = assign_modules_via_restart(all_questions)

    # Deduplication
    print("  🧹 Deduplicating...")
    unique_qs = {}
    for q in all_questions:
        try:
            key = f"M{int(q.get('module', 0))}_Q{int(q.get('questionNumber', 0))}"
        except (ValueError, TypeError):
            key = f"M{q.get('module')}_Q{q.get('questionNumber')}"
        if key not in unique_qs or len(str(q)) > len(str(unique_qs[key])):
            unique_qs[key] = q
    final_qs = list(unique_qs.values())

    # Fill missing questions
    for mod in range(1, 5):
        expected_max = 27 if mod <= 2 else 22
        mod_nums = []
        for q in final_qs:
            try:
                if int(q.get("module", 0)) == mod:
                    mod_nums.append(int(q.get("questionNumber", 0)))
            except (ValueError, TypeError):
                pass
        if not mod_nums:
            continue
        missing = [i for i in range(1, expected_max + 1) if i not in mod_nums]
        if missing:
            gen_qs = generate_missing_questions(missing, mod, is_math=(mod > 2))
            final_qs.extend(gen_qs)

    # QA pass
    final_qs = review_and_fix_questions(final_qs)
    print(f"  -> Final count: {len(final_qs)} questions ready.")

    # Write to Firestore
    init_firebase()
    write_to_firestore(test_id, test_name, final_qs, config.DEFAULT_CATEGORY)


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys
    import logging
    import traceback

    log_file = "pipeline_local.log"
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter('%(message)s'))
    logging.getLogger('').addHandler(console)

    def custom_print(*args, **kwargs):
        logging.info(" ".join(map(str, args)))

    import builtins
    builtins.print = custom_print

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.error("💥 Uncaught exception:", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception

    parser = argparse.ArgumentParser(description="ALFA SAT Local LLM PDF Pipeline")
    parser.add_argument("--pdf", required=True, help="Path to a single PDF file")
    parser.add_argument("--test-name", required=True, help="Display name for the test")
    parser.add_argument("--test-id", required=True, help="Firestore document ID")
    parser.add_argument("--category", default=config.DEFAULT_CATEGORY)
    parser.add_argument("--vision-model", default=None, help="Override Ollama vision model (default: from config)")

    args = parser.parse_args()

    # Allow CLI override of vision model
    if args.vision_model:
        config.LOCAL_VISION_MODEL = args.vision_model

    print("🚀 ALFA SAT Local LLM Pipeline starting...")
    vision_model = getattr(config, "LOCAL_VISION_MODEL", "llava:7b")
    print(f"🤖 Vision model: {vision_model}")
    print(f"🔗 Ollama endpoint: {getattr(config, 'LOCAL_LLM_ENDPOINT', 'http://localhost:11434/api/generate')}")

    # Quick connectivity check
    try:
        ping = requests.get("http://localhost:11434", timeout=5)
        print("✅ Ollama is running.")
    except Exception:
        print("❌ CRITICAL: Cannot reach Ollama at http://localhost:11434")
        print("   Run: ollama serve")
        sys.exit(1)

    process_pdf(args.pdf, args.test_name, args.test_id)
