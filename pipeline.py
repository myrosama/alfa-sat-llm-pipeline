"""
ALFA SAT — LLM PDF Pipeline (V5.0 — PDF Upload)
===================================================
Uses Gemini's native PDF upload to process entire SAT PDFs in 2 API calls.
Free tier: 20 RPD → 89 PDFs in ~9 days (or faster with multiple keys).

Pass 1: Extract-only (2 calls per PDF)
Pass 2+: Fix gaps with fix_runner.py (run repeatedly)
"""

import os
import json
import re
import time
import base64
import datetime
from typing import List, Dict
from pathlib import Path

import fitz  # PyMuPDF
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import firebase_admin
from firebase_admin import credentials, firestore

import config
import prompts

# --- Global state ---
db = None
_key_index = 0
PROGRESS_FILE = os.path.join(os.path.dirname(__file__), "progress.json")
USAGE_FILE = os.path.join(os.path.dirname(__file__), "key_usage.json")

def load_key_usage():
    global _key_usage
    if os.path.exists(USAGE_FILE):
        try:
            with open(USAGE_FILE, "r") as f:
                _key_usage = json.load(f)
        except:
            _key_usage = {}

def save_key_usage():
    try:
        with open(USAGE_FILE, "w") as f:
            json.dump(_key_usage, f, indent=2)
    except:
        pass


# --- Initial Load ---
_key_usage = {}
load_key_usage()

def init_firebase():
    global db
    if not firebase_admin._apps:
        try:
            cred = credentials.Certificate(config.SERVICE_ACCOUNT_KEY)
            firebase_admin.initialize_app(cred)
            print(f"✅ Firebase initialized")
        except Exception as e:
            print(f"❌ Firebase init error: {e}")
            return
    db = firestore.client()


# ─────────────────────────────────────────────
#  Progress Tracking
# ─────────────────────────────────────────────

def load_progress() -> Dict:
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    return {"completed": [], "failed": []}


def save_progress(progress: Dict):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


# ─────────────────────────────────────────────
#  Free Tier Rate Limiter
# ─────────────────────────────────────────────

def _rate_limit_wait(key: str):
    """Enforce free-tier rate limits per key: RPM and RPD."""
    global _key_usage

    now = datetime.datetime.now()
    today = now.strftime("%Y-%m-%d")

    # Initialize key usage if not exists
    if key not in _key_usage:
        _key_usage[key] = {"daily_count": 0, "day": today, "rpm_last": 0}

    # Reset if new day
    if _key_usage[key]["day"] != today:
        _key_usage[key]["daily_count"] = 0
        _key_usage[key]["day"] = today

    # Check daily limit for this specific key
    if _key_usage[key]["daily_count"] >= config.FREE_TIER_RPD:
        return False  # Key exhausted

    # Enforce RPM delay (per key)
    elapsed = time.time() - _key_usage[key]["rpm_last"]
    if elapsed < config.FREE_TIER_DELAY:
        time.sleep(config.FREE_TIER_DELAY - elapsed)

    return True

def _increment_usage(key: str):
    """Increment the usage count and update last call time."""
    global _key_usage
    if key not in _key_usage:
        _key_usage[key] = {"daily_count": 0, "day": datetime.datetime.now().strftime("%Y-%m-%d"), "rpm_last": 0}
    _key_usage[key]["daily_count"] += 1
    _key_usage[key]["rpm_last"] = time.time()
    save_key_usage()

def get_total_daily_calls_remaining() -> int:
    """Return total remaining calls across ALL keys."""
    total = 0
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    for key in config.GEMINI_API_KEYS:
        usage = _key_usage.get(key, {"daily_count": 0, "day": today})
        if usage["day"] == today:
            total += max(0, config.FREE_TIER_RPD - usage["daily_count"])
        else:
            total += config.FREE_TIER_RPD
    return total


def get_daily_calls_remaining() -> int:
    """Return total remaining calls across ALL keys."""
    return get_total_daily_calls_remaining()


def detect_section_pages(pdf_path: str) -> dict:
    doc = fitz.open(pdf_path)
    total = len(doc)
    math_start = None
    is_scanned = len(doc[1].get_text().strip()) < 100
    for i in range(len(doc)):
        page_text = doc[i].get_text().lower()
        if is_scanned and i < 40:
            try:
                import pytesseract
                from PIL import Image
                pix = doc[i].get_pixmap()
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                page_text = pytesseract.image_to_string(img).lower()
            except: pass
        if ("math directions" in page_text or "calculator is allowed" in page_text or ("math" in page_text and "module" in page_text and "directions" in page_text and i > 15)):
            math_start = i
            break
    doc.close()
    if math_start is None: math_start = total // 2 + 1
    return {"rw": (1, math_start - 1), "math": (math_start, total), "total": total, "is_scanned": is_scanned}


def slice_pdf(pdf_path: str, start: int, end: int) -> str:
    """Creates a temporary PDF with only the specified page range (1-indexed)."""
    temp_path = f"/tmp/sliced_{os.path.basename(pdf_path)}_{start}_{end}.pdf"
    try:
        doc = fitz.open(pdf_path)
        new_doc = fitz.open()
        # fitz uses 0-indexed pages
        new_doc.insert_pdf(doc, from_page=start-1, to_page=end-1)
        new_doc.save(temp_path)
        new_doc.close()
        doc.close()
        return temp_path
    except Exception as e:
        print(f"  ⚠️ Error slicing PDF: {e}")
        return pdf_path

def _choose_key_and_wait():
    """Rotate keys and wait for quota."""
    global _key_index, _key_usage
    keys = config.GEMINI_API_KEYS
    
    for _ in range(len(keys)):
        candidate_key = keys[_key_index % len(keys)]
        if _rate_limit_wait(candidate_key):
            key = candidate_key
            _increment_usage(key)
            return key, _key_index % len(keys)
        else:
            _key_index += 1

    # If all exhausted
    now = datetime.datetime.now()
    tomorrow = now.replace(hour=0, minute=0, second=0) + datetime.timedelta(days=1)
    wait_secs = (tomorrow - now).total_seconds()
    print(f"\n  ⏸️  ALL KEYS EXHAUSTED ({len(keys)} keys used today).")
    print(f"  ⏸️  Sleeping until midnight. Leave running!")
    time.sleep(wait_secs + 10)
    _key_index = 0
    return _choose_key_and_wait()

def call_gemini_with_pdf(pdf_path: str, prompt: str, page_hint: str = "", start: int = 1, end: int = None, model_name: str = config.GEMINI_MODEL) -> List[Dict]:
    """
    Upload entire PDF to Gemini and extract questions in a SINGLE call.
    """
    global _key_index, _key_usage
    key, kidx = _choose_key_and_wait()

    # Isolation: Slice PDF if range provided
    effective_pdf = pdf_path
    if end:
        effective_pdf = slice_pdf(pdf_path, start, end)

    try:
        genai.configure(api_key=key)
        model = genai.GenerativeModel(model_name)

        # Upload the PDF file
        print(f"  📤 [Key {kidx}] Uploading PDF to Gemini... {page_hint} (pages {start}-{end if end else 'all'})")
        uploaded_file = genai.upload_file(effective_pdf, mime_type="application/pdf")

        # Cleanup temp file
        if effective_pdf != pdf_path and os.path.exists(effective_pdf):
            try: os.remove(effective_pdf)
            except: pass

        response = model.generate_content(
            [uploaded_file, prompt],
            generation_config={
                "temperature": 0.1,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 65536,  # Need large output for all questions
            },
            safety_settings={
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
        )

        # Clean up uploaded file
        try:
            genai.delete_file(uploaded_file.name)
        except:
            pass

        text = response.text.strip()
        
        # DEBUG LOGGING FOR RAW JSON
        try:
            with open("output/debug_raw.json", "a") as f:
                f.write(f"\\n\\n--- RAW LLM RESPONSE ---\\n{text}\\n")
        except:
            pass
            
        if text.startswith("```json"):
            text = text[7:-3].strip()
        elif text.startswith("```"):
            text = text[3:-3].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            print(f"  ⚠️ JSON parse error: {e}. Trying regex recovery...")
            results = []
            
            # Step 1: Look for any cohesive [...] block first
            match = re.search(r'\[\s*\{.*\}\s*\]', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except:
                    pass
            
            # Step 2: Aggressively hunt for complete {...} objects
            # Using a custom brace-matching algorithm to avoid regex recursion limits
            brace_count = 0
            start_idx = -1
            for i, char in enumerate(text):
                if char == '{':
                    if brace_count == 0:
                        start_idx = i
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0 and start_idx != -1:
                        obj_str = text[start_idx:i+1]
                        try:
                            # Try to clean up common trailing commas before parsing
                            obj_str = re.sub(r',\s*\}', '}', obj_str)
                            obj = json.loads(obj_str)
                            if "questionNumber" in obj:
                                results.append(obj)
                        except:
                            pass
                        start_idx = -1
            
            if results:
                print(f"  ⚠️ Recovered {len(results)} individual questions via strict brace-matching")
                return results
                
            print(f"  ❌ Could not parse any objects. First 300 chars: {text[:300]}")
            return []

    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "quota" in err_str.lower() or "resource" in err_str.lower():
            print(f"  ⚠️ Rate limited! Waiting 65s and rotating key...")
            _key_index += 1
            time.sleep(65)
            return call_gemini_with_pdf(pdf_path, prompt, page_hint, start=start, end=end, model_name=model_name)
        print(f"  ❌ Gemini Error: {e}")
        return []


# Also keep the old image-based call for fix_runner.py (gap filling needs specific pages)
def call_gemini_vision(images: List[bytes], prompt: str) -> List[Dict]:
    """Call Gemini with images (used by fix_runner for targeted gap fills)."""
    global _key_index, _key_usage
    key, kidx = _choose_key_and_wait()

    try:
        genai.configure(api_key=key)
        model = genai.GenerativeModel(config.GEMINI_MODEL)

        contents = [prompt]
        for img_bytes in images:
            contents.append({
                "mime_type": "image/jpeg",
                "data": base64.b64encode(img_bytes).decode("utf-8")
            })

        response = model.generate_content(
            contents,
            generation_config={"temperature": 0.1, "top_p": 0.95, "top_k": 40},
            safety_settings={
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
        )

        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:-3].strip()
        elif text.startswith("```"):
            text = text[3:-3].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\[\s*\{.*\}\s*\]', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return []

    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "quota" in err_str.lower():
            _key_index += 1
            time.sleep(65)
            return call_gemini_vision(images, prompt)
        print(f"  ❌ Gemini Error: {e}")
        return []


def pdf_to_images(pdf_path: str) -> List[bytes]:
    """Convert PDF pages to JPEG bytes (for fix_runner gap fills)."""
    if not os.path.exists(pdf_path):
        return []
    images = []
    try:
        doc = fitz.open(pdf_path)
        for i in range(len(doc)):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            images.append(pix.tobytes("jpeg"))
        doc.close()
    except Exception as e:
        print(f"  ❌ Error rendering PDF: {e}")
    return images


def build_page_type_map(pdf_path: str) -> Dict[int, str]:
    """Build page type map (for fix_runner)."""
    doc = fitz.open(pdf_path)
    type_map = {}
    current_section = "rw"
    for i in range(len(doc)):
        page_text = doc[i].get_text().lower()
        if "reading and writing directions" in page_text:
            current_section = "rw"
        elif "math directions" in page_text or "calculator is allowed" in page_text:
            current_section = "math"
        
        # Use simple heuristics for skip pages (directions, title)
        if "directions" in page_text or ("practice test" in page_text and i < 2) or "reference sheet" in page_text:
            type_map[i] = "skip"
        else:
            type_map[i] = current_section
    doc.close()
    return type_map


# ─────────────────────────────────────────────
#  Module Assignment
# ─────────────────────────────────────────────

def assign_modules(questions: List[Dict]) -> List[Dict]:
    """Assign module numbers using question-number restart detection."""
    if not questions:
        return questions

    rw_qs = [q for q in questions if q.get("sectionType", "").lower() == "rw"]
    math_qs = [q for q in questions if q.get("sectionType", "").lower() == "math"]

    # Unknowns — classify by content
    for q in questions:
        if q.get("sectionType", "").lower() not in ("rw", "math"):
            text = (q.get("prompt", "") + " " + q.get("passage", "")).lower()
            if any(kw in text for kw in ["$", "equation", "solve", "f(x)", "graph"]):
                q["sectionType"] = "math"
                math_qs.append(q)
            else:
                q["sectionType"] = "rw"
                rw_qs.append(q)

    _detect_restart_and_assign(rw_qs, mod1=1, mod2=2)
    _detect_restart_and_assign(math_qs, mod1=3, mod2=4)

    all_qs = rw_qs + math_qs
    return all_qs


def _detect_restart_and_assign(questions: List[Dict], mod1: int, mod2: int):
    if not questions:
        return
    # DO NOT sort questions by questionNumber yet!
    # The API returns them in roughly page order (M1 then M2). 
    # If we sort them globally, we mix M1 Q1 with M2 Q1, rendering restart detection impossible.

    max_q = 0
    restart_idx = -1
    for i, q in enumerate(questions):
        num = int(q.get("questionNumber", 0) or 0)
        if max_q > 15 and num < 5 and num < max_q - 5:
            restart_idx = i
            break
        max_q = max(max_q, num)

    for i, q in enumerate(questions):
        q["module"] = mod1 if (restart_idx == -1 or i < restart_idx) else mod2


# ─────────────────────────────────────────────
#  Math Formula Formatting
# ─────────────────────────────────────────────

def wrap_formulas_in_quill(text: str) -> str:
    if not text or not isinstance(text, str):
        return text

    # Helper to clean up any nested p tags afterwards
    def clean_html(html: str) -> str:
        # Remove empty paragraphs or doubled paragraphs
        html = re.sub(r'<p>\s*<p', '<p', html)
        html = re.sub(r'</p>\s*</p>', '</p>', html)
        # Fix the "unwanted space after function" issue
        # Often occurs as </span> </p> or </span> ,
        html = re.sub(r'<\/span>\s+([,.?;:])', r'</span>\1', html)
        return html

    def repl(match, force_block=False):
        latex = match.group(1).strip()
        if 'class="ql-formula"' in latex:
            return match.group(0)
        
        # 1. Strip internal whitespace
        latex = latex.replace("  ", " ").strip()
        
        # 2. Centering heuristic
        # If it's explicitly double $$ or very long/structural
        is_block = force_block or r"\frac" in latex or r"\sum" in latex or r"\sqrt" in latex or len(latex) > 50
            
        formula_span = f'<span class="ql-formula" data-value="{latex}">&#xFEFF;<span contenteditable="false"><span class="katex">{latex}</span></span>&#xFEFF;</span>'
        
        if is_block:
            # If we are already in a paragraph, we might need a better way, 
            # but for now, we follow the user's rule for centered block math.
            return f'</p><p class="ql-align-center">{formula_span}</p><p>'
        return formula_span

    # 1. Block math: $$...$$
    text = re.sub(r'\$\$(.*?)\$\$', lambda m: repl(m, True), text, flags=re.DOTALL)
    
    # 2. Inline math: $...$
    text = re.sub(r'\$([^\$]+?)\$', lambda m: repl(m, False), text)
    
    # 3. Escaped parens: \( ... \)
    text = re.sub(r'\\\( (.*?) \\\)', lambda m: repl(m, False), text)

    return clean_html(text)

    # 4. Final safety: Catch naked LaTeX commands
    def naked_repl(match):
        found_latex = match.group(0)
        if 'class="ql-formula"' in text[max(0, match.start()-60):match.end()+60]:
            return found_latex
        class MockMatch:
            def __init__(self, val): self.val = val
            def group(self, n): return self.val
        return repl(MockMatch(found_latex))

    text = re.sub(r'(\\[a-z]+\{.*?\})', naked_repl, text)

    # Clean up paragraph nesting
    text = text.replace('<p><p class="ql-align-center">', '<p class="ql-align-center">')
    text = text.replace('</p></p>', '</p>')
    
    # Trim redundancy
    text = re.sub(r' +', ' ', text)
    text = text.replace(' </p>', '</p>').replace('<p> ', '<p>')

    return text


# ─────────────────────────────────────────────
#  Firestore Write
# ─────────────────────────────────────────────

def write_to_firestore(test_id, test_name, questions, category):
    if not db:
        init_firebase()
    if not db:
        print("❌ Cannot write to Firestore — not initialized")
        return

    test_ref = db.collection("tests").document(test_id)
    test_ref.set({
        "name": test_name,
        "testCategory": category,
        "visibility": "show",
        "createdBy": config.ADMIN_UID,
        "questionCount": len(questions),
        "createdAt": firestore.SERVER_TIMESTAMP
    })

    batch = db.batch()
    count = 0
    for q in questions:
        doc_id = f"m{q.get('module')}_q{q.get('questionNumber')}"
        batch.set(test_ref.collection("questions").document(doc_id), q, merge=True)
        count += 1
        if count >= 400:
            batch.commit()
            batch = db.batch()
            count = 0
    if count > 0:
        batch.commit()

    print(f"🎉 Written to Firestore: {test_id} ({len(questions)} questions)")


# ─────────────────────────────────────────────
#  Save JSON Backup
# ─────────────────────────────────────────────

def save_json_backup(test_id: str, questions: List[Dict], output_dir: str = "output"):
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{test_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(questions, f, indent=2, ensure_ascii=False)
    print(f"  💾 Saved: {path}")


# ─────────────────────────────────────────────
#  FULL PDF EXTRACTION PROMPT
# ─────────────────────────────────────────────

FULL_PDF_RW_PROMPT = """You are an expert SAT question parser. This PDF contains a complete Digital SAT Practice Test.

EXTRACT ALL READING & WRITING QUESTIONS (PAGES __START__-__END__).
Skip: title pages, directions pages, answer keys, math sections.

For EACH question, return a JSON object with:
- "questionNumber": (int) printed question number
- "sectionType": "rw"
- "passage": The reading passage text. HTML formatted (<p>, <b>, <i>, <u>). For "Notes" questions, include the full bulleted list as <ul><li>. If two texts, label "Text 1" and "Text 2".
- "prompt": The question text only. HTML formatted.
- "options": {"A": "...", "B": "...", "C": "...", "D": "..."} — NO letter prefixes
- "correctAnswer": "A"|"B"|"C"|"D" — infer from visual cues or pick most defensible
- "format": "mcq"
- "domain": STRICTLY infer based on question number:
    - Q1 - Q4: "Craft and Structure" (Vocabulary)
    - Q5 - Q14: "Information and Ideas" or "Craft and Structure" (Reading)
    - Q15 - Q19: "Standard English Conventions" (Writing boundaries/form)
    - Q20 - Q27: "Expression of Ideas" (Transitions and Notes)
- "skill": """ + str(list(prompts.RW_TAXONOMY.values())) + """
- "explanation": 2-3 sentence explanation. HTML formatted.
- "needsImageExtraction": true ONLY IF the question relies on a chart, graph, table, or visual diagram to be solved. If you see ANY visual element other than pure text, set this to TRUE.
- "imagePage": (int) the 1-indexed page number of the PDF where the required image/chart/graph is actually located. If needsImageExtraction is true, you MUST provide this exact page number. If false, set it to 0.

CRITICAL RULES:
- PURE TEXT + HTML. No LaTeX, no KaTeX, no $ delimiters.
- For blanks: "________" (8 underscores)
- Each question is its own JSON object — do NOT merge multiple questions
- Do NOT invent questions — only extract what's printed
- If a question spans two pages, combine the text seamlessly

Return ONLY a valid JSON array. No markdown, no commentary."""

FULL_PDF_MATH_PROMPT = """You are an expert SAT question parser. This PDF contains a complete Digital SAT Practice Test.

EXTRACT ALL MATH QUESTIONS (PAGES __START__-__END__).
Skip: title pages, directions pages, reference sheets, R&W sections.

For EACH question, return a JSON object with:
- "questionNumber": (int) printed question number
- "sectionType": "math"
- "passage": Usually empty "". Only fill if there's a shared data table or word problem setup.
- "prompt": Full question text. ALL math wrapped in LaTeX: $...$. Example: "If $2x + 3 = 7$, what is $x$?"
- "options": {"A": "...", "B": "...", "C": "...", "D": "..."} — math in $...$, NO letter prefixes. For fill-in: {"A": "", "B": "", "C": "", "D": ""}
- "correctAnswer": Letter for mcq, numeric string for fill-in (e.g. "4", "3/2")
- "fillInAnswer": Same as correctAnswer for fill-in, empty "" for mcq
- "format": "mcq" or "fill-in"
- "domain": EXACTLY one of: "Algebra", "Advanced Math", "Problem-Solving and Data Analysis", "Geometry and Trigonometry". Note that questions naturally progress from easier difficulty (Q1) to harder difficulty (Q22).
- "skill": """ + str(list(prompts.MATH_TAXONOMY.values())) + """
- "explanation": step-by-step solution with $...$. HTML formatted.
- "needsImageExtraction": true ONLY IF the question relies on a complex visual scatterplot, geometry diagram, graph, or complex data table.
- CRITICAL: NEVER set needsImageExtraction to true for mathematical equations, standalone formulas, fractions, or simply formatted text. Wrap all math in $...$ instead.
- "imagePage": (int) the 1-indexed page number of the PDF where the required image/diagram is actually located. If needsImageExtraction is true, you MUST provide this exact page number. If false, set it to 0.
- "imageWidth": if needsImageExtraction is true, estimate size needed: "small" (simple geometry), "medium" (graph), or "full" (wide table). If false, set to "".

CRITICAL RULES:
- ALL math expressions MUST use $...$ LaTeX delimiters
- Each question is its own JSON object
- Do NOT invent questions
- If a question spans pages, combine seamlessly

Return ONLY a valid JSON array. No markdown, no commentary."""

FULL_PDF_MATH_PROMPT_SCANNED = """You are an expert SAT question parser. This PDF is a NEW, PREVIOUSLY UNSEEN Digital SAT Practice Test (Created in 2026).
DO NOT use questions from your training data or memory. Only extract what is VISIBLY PRESENT in this PDF.

EXTRACT ALL MATH QUESTIONS (PAGES __START__-__END__).
CRITICAL RULES FOR SCANNED PDF:
1. Transcribe the text and math expressions as accurately as possible.
2. If a pure graphic/diagram/table is present, describe it briefly in the "passage" or "prompt" field AND provide its visual bounding box.

For EACH question, return a JSON object with:
- "questionNumber": (int) printed number
- "sectionType": "math"
- "passage": Any shared context (tables/text) or diagram description.
- "prompt": The question text with LaTeX $...$
- "options": {"A": "...", "B": "...", "C": "...", "D": "..."}
- "correctAnswer": Letter or numeric answer
- "fillInAnswer": Same as correctAnswer for fill-in, else ""
- "format": "mcq" or "fill-in"
- "domain": EXACTLY one of: "Algebra", "Advanced Math", "Problem-Solving and Data Analysis", "Geometry and Trigonometry"
- "skill": "Descriptive skill name"
- "explanation": Brief step-by-step solution.
- "needsImageExtraction": true ONLY IF the question relies on a pure visual scatterplot, geometry diagram, or complex data table.
- CRITICAL: NEVER set needsImageExtraction to true for mathematical equations, geometric notation without pictures, fractions, or basic shapes like a single empty circle.
- "imagePage": (int) the 1-indexed page number of the PDF where the required image/diagram is actually located. If needsImageExtraction is true, you MUST provide this exact page number. If false, set it to 0.
- "imageWidth": if needsImageExtraction is true, estimate size needed: "small" (simple geometry), "medium" (graph), or "full" (wide table). If false, set to "".

Return ONLY a valid JSON array."""







# ─────────────────────────────────────────────
#  Main Pipeline (PDF Upload — 2 calls per PDF)
# ─────────────────────────────────────────────

def process_pdf(pdf_path: str, test_name: str, test_id: str,
                extract_only: bool = False, dry_run: bool = False,
                output_dir: str = "output"):
    """
    Process a single PDF using direct PDF upload.
    Only 2 API calls: one for R&W, one for Math.
    """
    init_firebase()

    if not os.path.exists(pdf_path):
        print(f"❌ PDF not found: {pdf_path}")
        return

    # Detect section page ranges
    sections = detect_section_pages(pdf_path)
    print(f"\n📄 {test_name}")
    print(f"   Pages: {sections['total']} | R&W: {sections['rw'][0]}-{sections['rw'][1]} | Math: {sections['math'][0]}-{sections['math'][1]}")
    print(f"   API calls remaining today: {get_daily_calls_remaining()}")

    all_questions = []

    rw_start_page, rw_end_page = sections["rw"]
    rw_midpoint = rw_start_page + ((rw_end_page - rw_start_page) // 2)

    # R&W Module 1 (First Half)
    print(f"\n  📚 Call 1/X: Extracting R&W Module 1 (pages {rw_start_page}-{rw_midpoint})...")
    rw_m1_prompt = FULL_PDF_RW_PROMPT.replace("__START__", str(rw_start_page)).replace("__END__", str(rw_midpoint))
    rw_m1_qs = call_gemini_with_pdf(pdf_path, rw_m1_prompt, "R&W M1", start=rw_start_page, end=rw_midpoint)
    if rw_m1_qs:
        for q in rw_m1_qs:
            q["sectionType"] = "rw"
            q["_start_page"] = rw_start_page
        all_questions.extend(rw_m1_qs)
        print(f"  ✅ Got {len(rw_m1_qs)} R&W Module 1 questions")
        
    # R&W Module 2 (Second Half)
    print(f"\n  📚 Call 2/X: Extracting R&W Module 2 (pages {rw_midpoint + 1}-{rw_end_page})...")
    rw_m2_prompt = FULL_PDF_RW_PROMPT.replace("__START__", str(rw_midpoint + 1)).replace("__END__", str(rw_end_page))
    rw_m2_qs = call_gemini_with_pdf(pdf_path, rw_m2_prompt, "R&W M2", start=rw_midpoint + 1, end=rw_end_page)
    if rw_m2_qs:
        for q in rw_m2_qs:
            q["sectionType"] = "rw"
            q["_start_page"] = rw_midpoint + 1
        all_questions.extend(rw_m2_qs)
        print(f"  ✅ Got {len(rw_m2_qs)} R&W Module 2 questions")

    # --- Call 2: Math ---
    math_start_page, math_end_page = sections["math"]
    is_scanned = sections.get("is_scanned", False)
    print(f"   Scanned PDF detected: {is_scanned}")

    if is_scanned:
        math_midpoint = math_start_page + ((math_end_page - math_start_page) // 2)

        # Scanned Module 1
        print("\n  🔢 Call 2/3: Extracting Scanned Math M1 (Pages %d-%d)..." % (math_start_page, math_midpoint))
        m1_prompt = FULL_PDF_MATH_PROMPT_SCANNED.replace(
            "__START__-__END__", f"{math_start_page}-{math_midpoint}"
        ).replace("EXTRACT ALL MATH QUESTIONS", "EXTRACT ONLY MATH MODULE 1 QUESTIONS (Questions 1-22)")
        m1_qs = call_gemini_with_pdf(pdf_path, m1_prompt, page_hint="Math Scanned M1", start=math_start_page, end=math_midpoint)
        if m1_qs:
            for q in m1_qs: 
                q["sectionType"] = "math"
                q["_start_page"] = math_start_page
            print(f"  ✅ Got {len(m1_qs)} Scanned Math M1 questions")

        # Scanned Module 2
        print("\n  🔢 Call 3/3: Extracting Scanned Math M2 (Pages %d-%d)..." % (math_midpoint + 1, math_end_page))
        m2_prompt = FULL_PDF_MATH_PROMPT_SCANNED.replace(
            "__START__-__END__", f"{math_midpoint + 1}-{math_end_page}"
        ).replace("EXTRACT ALL MATH QUESTIONS", "EXTRACT ONLY MATH MODULE 2 QUESTIONS (Questions 1-22)")
        m2_qs = call_gemini_with_pdf(pdf_path, m2_prompt, page_hint="Math Scanned M2", start=math_midpoint+1, end=math_end_page)
        if m2_qs:
            for q in m2_qs: 
                q["sectionType"] = "math"
                q["_start_page"] = math_midpoint + 1
            print(f"  ✅ Got {len(m2_qs)} Scanned Math M2 questions")

        math_questions = (m1_qs or []) + (m2_qs or [])
    else:
        # -- Native PDF: Math Module 1 + Module 2 separately due to high token density
        math_midpoint = math_start_page + ((math_end_page - math_start_page) // 2)

        # Math Module 1 (First Half)
        math_m1_prompt = FULL_PDF_MATH_PROMPT.replace(
            "__START__-__END__", f"{math_start_page}-{math_midpoint}"
        ).replace(
            "EXTRACT ALL MATH QUESTIONS", "EXTRACT ONLY MATH MODULE 1 QUESTIONS (Questions 1-22)"
        )
        
        # Math Module 2 (Second Half)
        math_m2_prompt = FULL_PDF_MATH_PROMPT.replace(
            "__START__-__END__", f"{math_midpoint + 1}-{math_end_page}"
        ).replace(
            "EXTRACT ALL MATH QUESTIONS", "EXTRACT ONLY MATH MODULE 2 QUESTIONS (Questions 1-22)"
        )

        print("\n  🔢 Call 2/3: Extracting Math Module 1 (Pages %d-%d)..." % (math_start_page, math_midpoint))
        math_m1_qs = call_gemini_with_pdf(pdf_path, math_m1_prompt, page_hint="Math M1", start=math_start_page, end=math_midpoint)
        if math_m1_qs:
            for q in math_m1_qs:
                q["sectionType"] = "math"
                q["_start_page"] = math_start_page
            print(f"  ✅ Got {len(math_m1_qs)} Math Module 1 questions")
        else:
            print(f"  ⚠️ No Math Module 1 questions returned")

        print("\n  🔢 Call 3/3: Extracting Math Module 2 (Pages %d-%d)..." % (math_midpoint + 1, math_end_page))
        math_m2_qs = call_gemini_with_pdf(pdf_path, math_m2_prompt, page_hint="Math M2", start=math_midpoint+1, end=math_end_page)
        if math_m2_qs:
            for q in math_m2_qs:
                q["sectionType"] = "math"
                q["_start_page"] = math_midpoint + 1
            print(f"  ✅ Got {len(math_m2_qs)} Math Module 2 questions")
        else:
            print(f"  ⚠️ No Math Module 2 questions returned")

        math_questions = (math_m1_qs or []) + (math_m2_qs or [])
        
    all_questions.extend(math_questions)
    print(f"  ✅ Total Math Questions Extracted: {len(math_questions)}")


    if not all_questions:
        print(f"❌ No questions extracted from {pdf_path}")
        return

    # Assign modules
    print(f"\n  🧠 Assigning modules...")
    all_questions = assign_modules(all_questions)

    # Deduplicate
    unique = {}
    for q in all_questions:
        key = f"M{q.get('module')}_Q{q.get('questionNumber')}"
        if key not in unique or len(str(q)) > len(str(unique[key])):
            unique[key] = q
    final_list = list(unique.values())
    
    # ─── No Image Cropping in Pass 1 ───
    # Phase 3 Algorithm: pipeline.py only focuses on text extraction and structure.
    # Image formatting and OCR verification are deferred to quality_agents.py (Agent 4 & 5).
    # We keep image_bbox if the AI provided it, as it might be useful for Agent 4.
    pass

    # Completeness check (free — no API)
    if not extract_only:
        import quality_agents
        quality_agents.agent1_check_completeness(final_list)
    else:
        _quick_completeness_check(final_list)

    # Wrap math formulas
    for q in final_list:
        q.pop("_batch_start", None)
        q["prompt"] = wrap_formulas_in_quill(q.get("prompt", ""))
        q["explanation"] = wrap_formulas_in_quill(q.get("explanation", ""))
        opts = q.get("options", {})
        if isinstance(opts, dict):
            for k in opts:
                opts[k] = wrap_formulas_in_quill(opts[k])

    # Save JSON backup
    save_json_backup(test_id, final_list, output_dir)

    # Write to Firestore
    if not dry_run:
        write_to_firestore(test_id, test_name, final_list, "real_exam")
    else:
        print("  🔒 Dry run — skipped Firestore write")

    print(f"\n  📊 Total: {len(final_list)} questions | API calls remaining: {get_daily_calls_remaining()}")
    return final_list


def _quick_completeness_check(questions: List[Dict]):
    """Quick local check — no API calls."""
    expected = {1: 27, 2: 27, 3: 22, 4: 22}
    for mod in range(1, 5):
        found = [q for q in questions if q.get("module") == mod]
        nums = sorted([int(q.get("questionNumber", 0)) for q in found])
        missing = [i for i in range(1, expected[mod] + 1) if i not in nums]
        section = "R&W" if mod <= 2 else "Math"
        if missing:
            print(f"    ⚠️  M{mod} ({section}): {len(found)}/{expected[mod]} — missing {missing}")
        else:
            print(f"    ✅ M{mod} ({section}): {len(found)}/{expected[mod]} — complete!")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ALFA SAT PDF Pipeline (Free Tier — PDF Upload)")
    parser.add_argument("pdf", help="Path to PDF file")
    parser.add_argument("name", help="Test display name")
    parser.add_argument("id", help="Firestore test ID")
    parser.add_argument("--extract-only", action="store_true",
                        help="Skip critic/gap-filler (Pass 1 mode)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't write to Firestore")
    parser.add_argument("--output-dir", default="output",
                        help="Directory for JSON backups")
    args = parser.parse_args()
    process_pdf(args.pdf, args.name, args.id,
                extract_only=args.extract_only,
                dry_run=args.dry_run,
                output_dir=args.output_dir)
