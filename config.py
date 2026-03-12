import os
from dotenv import load_dotenv

load_dotenv()

# --- Gemini API ---
# Gemini 3.1 Flash Lite: 15 RPM, 500 RPD free tier (best free option!)
GEMINI_MODEL = "gemini-3.1-flash-lite-preview"
GEMINI_MODEL_FALLBACK = "gemini-2.5-flash-lite"

# Gemini API Keys (Loaded from .env)
# The .env file should contain: GEMINI_API_KEYS="key1,key2,key3"
raw_keys = os.getenv("GEMINI_API_KEYS", "")
if raw_keys:
    GEMINI_API_KEYS = [k.strip() for k in raw_keys.split(",") if k.strip()]
else:
    # Fallback to individual keys if provided
    GEMINI_API_KEYS = [
        os.getenv(f"GEMINI_API_KEY_{i}") for i in range(1, 11)
        if os.getenv(f"GEMINI_API_KEY_{i}")
    ]

if not GEMINI_API_KEYS:
    print("⚠️ WARNING: No GEMINI_API_KEYS found in .env!")

# --- Free Tier Rate Limits (from AI Studio: Gemini 1.5 Flash Lite) ---
FREE_TIER_RPM = 15          # Actual limit: 15 RPM
FREE_TIER_RPD = 1500        # Actual limit: 1500 RPD
FREE_TIER_DELAY = 4.1       # Seconds between calls (60/15 = 4s)

# --- Firebase ---
SERVICE_ACCOUNT_KEY = "/home/sadrikov49/Desktop/ALFA SAT PROJECT/llm-pipeline/serviceAccountKey.json"
FIRESTORE_PROJECT_ID = "alfasatuz"
ADMIN_UID = "Kz0qlMcOk9XmPLGytEHm2nOYMhY2"

# --- Telegram (for image uploads) ---

TELEGRAM_CHANNEL_ID = "-1002674756395"

# --- Pipeline Settings ---
DEFAULT_CATEGORY = "real_exam"

# --- Processing ---
PAGE_DPI = 300
BATCH_SIZE = 3
RATE_LIMIT_DELAY = 1
MAX_RETRIES = 3
