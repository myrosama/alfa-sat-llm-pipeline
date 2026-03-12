# ALFA SAT — Pipeline Handover Report (Day 2 End)

**To the Next AI Agent / Dev:**  
Welcome! You are picking up where we left off. Today we successfully transitioned the entire local Ollama pipeline to a robust, fully-cloud **Gemini 2.5 Flash** pipeline and optimized the frontend for speed and strict cost controls.

## 1. What We Accomplished Today

### A. The LLM Pipeline (`llm-pipeline/`)
- **Gemini 2.5 Flash Replacement**: We completely removed the old OpenCV + Ollama setup. The pipeline (`pipeline.py`) now sends high-res, full-page PDFs to Gemini 2.5 Flash natively. This solved layout hallucinations perfectly.
- **Strict Validation**: Added `validate.py` to enforce the ALFA UI schema and math KaTeX formatting. 
- **Free Tier Configuration**: The user's 8 API keys in `.env` are Free Tier (15 RPM limits). We updated `config.py` with `RATE_LIMIT_DELAY = 5` to ensure the `batch_runner.py` stays under the 15 RPM limit, making processing 100% free.
- **Ollama Removal**: We ran `remove_ollama.sh` to purge all local Ollama binaries and models to free up disk space.

### B. Frontend Code (`ALFA_SAT/`)
- **Telegram Fallback**: `telegram-images.js` was refactored to read tokens synchronously from `js/config.js` and implement a round-robin fallback. If one bot token hits a 401/429, it instantly retries the next.
- **Results & Review Navigation (Cost Optimization)**: 
  - `results.js` now uses an in-document `reviewIndex` to render the grid, dropping Firestore reads from ~99 to 1.
  - `question-review.js` was rewritten as a **Single Page Application (SPA)** with an invisible background prefetcher. Clicking "Next/Back" changes the URL and loads the next question instantly via RAM cache with *zero* page reloads. This guarantees the strict 2-read limit per question.
- **Cache-Busting and Deploy**: All `index.html` headers have robust hardcoded cache-busters (`?v=2.2`). `firebase.json` headers were also upgraded. We successfully ran `firebase deploy`.

## 2. Current State & Where We Left Off
- The `batch_runner.py` is safely **stopped**. No extraction is currently running.
- The user noted that the 8 API keys in `.env` are Free Tier and currently exhausted.
- The `gemini-api-dev` skill was installed globally so future agents have up-to-date Gemini API knowledge.

## 3. Next Steps for You
1. **API Keys**: The user needs to provide new, fresh Free Tier API keys (or Tier 1 paid keys if they prefer speed). Update `llm-pipeline/.env` with these new keys.
2. **Run the Batch**: Once fresh keys are in place, navigate to `llm-pipeline/` and run `python batch_runner.py --folder "../pdfs"` to process the remaining 89 PDFs.
3. **Verify Deployment**: The frontend is stable and deployed. The next major frontend task is finalizing the "Add Test from PDF" admin dashboard feature to auto-trigger this pipeline from the UI.

Good luck!
