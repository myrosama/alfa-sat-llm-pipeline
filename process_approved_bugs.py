"""
ALFA SAT — Local PDF Sync Tool
==============================
Processes bug reports that require extracting missing passages or images 
from local PDFs. Runs completely locally.

Usage: python process_approved_bugs.py
"""

import os
import json
import time
from typing import Dict, List
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

import config
from pipeline import call_gemini_vision, pdf_to_images, slice_pdf

# Initialize Firebase using local service account key
def init_firebase():
    if not firebase_admin._apps:
        try:
            cred = credentials.Certificate(config.SERVICE_ACCOUNT_KEY)
            firebase_admin.initialize_app(cred)
            print("✅ Firebase initialized locally")
        except Exception as e:
            print(f"❌ Firebase init error: {e}")
            return None
    return firestore.client()

db = init_firebase()

SYNC_PROMPT = """You are an expert SAT question extraction system.
We are recovering a missing or broken question from the original PDF test.

We need EXACTLY Question {q_num} from Module {module} ({section} Section).

The student reported: "{user_msg}"
The AI analysis was: "{analysis}"

Please look at this page from the test, find Question {q_num}, and extract it perfectly.
Return a complete JSON object following this format:
{{
  "questionNumber": {q_num},
  "sectionType": "{section}",
  "passage": "The HTML formatted passage text, or empty if it's math without a word problem.",
  "prompt": "The question text itself",
  "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
  "correctAnswer": "A",
  "domain": "...",
  "skill": "...",
  "explanation": "..."
}}

CRITICAL: Fix the exact issue the student reported!
If it's reading, ensure the full passage is extracted.
If it's math, ensure all formulas use LaTeX $...$ delimiters.
Return ONLY valid JSON.
"""

def process_pending_bugs():
    print("\n🔍 Scanning for approved bugs requiring PDF sync...")
    reports = db.collection("bug_reports").where("status", "==", "approved_pending_sync").get()
    
    if not reports:
        print("✅ No pending bug reports require local sync.")
        return

    print(f"📌 Found {len(reports)} reports to process.")

    for report_doc in reports:
        report_id = report_doc.id
        data = report_doc.to_dict()
        
        test_id = data.get("testId")
        q_num = data.get("questionNumber")
        mod = data.get("module")
        section = data.get("section")
        user_msg = data.get("userMessage")
        analysis = data.get("aiAnalysis")
        
        print(f"\n──────────────────────────────────────")
        print(f"🐛 Processing Report: {report_id}")
        print(f"   Test: {test_id} | M{mod} Q{q_num}")
        print(f"   Issue: {user_msg}")
        
        q_doc_id = f"m{mod}_q{q_num}"
        q_ref = db.collection("tests").document(test_id).collection("questions").document(q_doc_id)
        
        # 1. Fetch current question to know what page we are looking for
        q_doc = q_ref.get()
        if not q_doc.exists:
            print(f"   ❌ Could not find question {q_doc_id} in Firestore.")
            db.collection("bug_reports").document(report_id).update({"status": "failed_sync_no_q"})
            continue
            
        q_data = q_doc.to_dict()
        start_page = q_data.get("_start_page")
        if start_page is None: start_page = q_data.get("_batch_start")
        
        # 2. Find local PDF
        # Try to map test ID back to PDF file. E.g. "2024_aug_int_a" -> "2024 Aug Int-A @EliteXSAT.pdf"
        possible_names = [
            test_id.replace("_", " ").title() + " @EliteXSAT.pdf",
            test_id.replace("_", " ").title() + ".pdf",
        ]
        
        pdf_path = None
        for name in possible_names:
            path = os.path.join("pdfs", name)
            if os.path.exists(path):
                pdf_path = path
                break
                
        # Handle strict conversion issues
        if not pdf_path:
            # Let's search the directory for a rough match
            for filename in os.listdir("pdfs"):
                clean_name = filename.lower().replace(" ", "_").replace("-", "_").replace("@elitexsat.pdf", "")
                if clean_name.startswith(test_id.lower().replace("-", "_")):
                    pdf_path = os.path.join("pdfs", filename)
                    break

        if not pdf_path:
            print(f"   ❌ Could not locate local PDF for {test_id}. Tried: {possible_names[0]}")
            db.collection("bug_reports").document(report_id).update({"status": "failed_sync_no_pdf"})
            continue
            
        print(f"   📄 Found PDF: {pdf_path}")
        
        # 3. Read PDF and prepare images
        # We don't want to convert the whole PDF, just 3 pages around the start_page
        import fitz
        try:
            doc = fitz.open(pdf_path)
            target_pages = []
            
            if start_page is not None:
                # Math: ~1-2 questions per page
                # R&W: ~3-4 questions per page
                if int(mod) >= 3:
                    estimated_idx = start_page + max(0, (int(q_num) - 1) // 2)
                else:
                    estimated_idx = start_page + max(0, (int(q_num) - 1) // 3)
                
                # Grab a window of 3 pages to be safe
                for p in [estimated_idx - 1, estimated_idx, estimated_idx + 1]:
                    if 0 <= p < len(doc):
                        page = doc.load_page(p)
                        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                        target_pages.append(pix.tobytes("jpeg"))
                        
            if not target_pages:
                # Fallback: couldn't guess the page, grab the whole module range if possible, or fail
                print("   ❌ Could not determine which pages to scan.")
                db.collection("bug_reports").document(report_id).update({"status": "failed_sync_no_pages"})
                continue
                
            print(f"   📸 Extracted {len(target_pages)} candidate pages around index {start_page}...")
            
            # 4. Call Gemini Vision
            prompt = SYNC_PROMPT.format(q_num=q_num, module=mod, section=section, user_msg=user_msg, analysis=analysis)
            print("   🤖 Running AI Extraction...")
            
            result_list = call_gemini_vision(target_pages, prompt)
            
            if result_list and len(result_list) > 0:
                fixed_q = result_list[0]
                
                # Critical safety: Ensure we're not overwriting internal fields
                safe_update = {}
                for k in ["passage", "prompt", "options", "correctAnswer", "explanation"]:
                    if k in fixed_q:
                        safe_update[k] = fixed_q[k]
                
                if safe_update:
                    q_ref.update(safe_update)
                    db.collection("bug_reports").document(report_id).update({"status": "resolved"})
                    print("   ✅ Sync successful! Firestore updated.")
                else:
                    print("   ❌ AI returned empty update fields.")
                    db.collection("bug_reports").document(report_id).update({"status": "failed_sync_ai_empty"})
            else:
                print("   ❌ AI extraction failed or returned invalid format.")
                db.collection("bug_reports").document(report_id).update({"status": "failed_sync_ai_error"})
                
        except Exception as e:
            print(f"   ❌ Error processing PDF: {e}")
            db.collection("bug_reports").document(report_id).update({"status": "failed_sync_exception"})
            
        time.sleep(config.RATE_LIMIT_DELAY)

if __name__ == "__main__":
    process_pending_bugs()
