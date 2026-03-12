# ALFA SAT — Pipeline V2 (Gemini 2.5 Flash)

This is the fully rebuilt SAT PDF processing pipeline. It takes raw SAT practice test PDFs, extracts all Reading & Writing and Math questions strictly according to the ALFA SAT UI schema, and saves them to Firestore.

It uses the **Gemini 2.5 Flash** model for its superior speed, cost-effectiveness, and structured JSON capabilities, completely replacing the old Ollama + OpenCV method.

## Features
- **Accurate Extraction**: Driven by structured JSON schema prompts that strictly enforce HTML formatting (`<p>`, `<b>`), KaTeX (`$...$`, `$$...$$`), and domain/skill tagging.
- **Strict Validation**: Every question is thoroughly checked by `validate.py` before being saved. If a question is invalid, it is skipped and logged to prevent database corruption.
- **Dry-Run & Backups**: Run in `--dry-run` mode to safely test PDFs. All raw outputs are backed up in `.jsonl` format in the `output/` folder for easy auditing and recovery.
- **Auto-Routing**: Automatically identifies and categorizes R&W vs. Math pages, and skips direction pages.

## Setup

1. **Virtual Environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Environment Variables**:
   Ensure you have a `.env` file containing your Gemini API keys (comma-separated if using rotation) and your Firebase setup:
   ```env
   GEMINI_API_KEYS="key1,key2,key3"
   FIREBASE_CREDENTIALS_PATH="path/to/firebase-adminsdk.json"
   FIREBASE_PROJECT_ID="alfasatuz"
   ```

## Usage

### Single PDF Processing
To process a single PDF, use `pipeline.py`. It is highly recommended to start with a dry-run:
```bash
# Dry-run mode (parses, validates, and backs up to JSONL but skips Firestore)
python pipeline.py --pdf "../pdfs/Mock test 1.pdf" --dry-run
```

Once the dry-run looks good, run it normally to write to Firestore:
```bash
python pipeline.py --pdf "../pdfs/Mock test 1.pdf"
```

### Batch Processing
To process an entire folder of PDFs consecutively:
```bash
python batch_runner.py --folder "../pdfs/"
```
Batch runner features:
- **`--dry-run`**: Applies dry-run to all files.
- **`--resume`**: Skips PDFs that were already successfully completed, keeping track via `progress.json`.

### Manual Validation
If you want to re-validate an existing JSONL backup without hitting the API:
```bash
python validate.py --jsonl "output/mock_test_1.jsonl"
```

## Structure
- `config.py`: Centralized configuration (models, delays, DPI settings).
- `prompts.py`: The core instructions and schema definitions given to Gemini.
- `validate.py`: Schema enforcement engine.
- `pipeline.py`: The main orchestration script for a single PDF.
- `batch_runner.py`: Wrapper for bulk processing.
