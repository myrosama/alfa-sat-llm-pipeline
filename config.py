import os
from dotenv import load_dotenv

load_dotenv()

# --- Gemini API ---
# Gemini 3.1 Flash Lite: 15 RPM, 500 RPD free tier (best free option!)
GEMINI_MODEL = "gemini-3.1-flash-lite-preview"
GEMINI_MODEL_FALLBACK = "gemini-2.5-flash-lite"

# Primary free-tier key
FREE_API_KEY = "AIzaSyAC7FxPtaofHzq9bnxAS0i4J1i4TjbJMEc"

# Extra free-tier keys from separate accounts (key rotation)
EXTRA_FREE_KEYS = [
    "AIzaSyBIZuBg3tFAZ-4qqp_WyF3kn7rj96i2zvU",
    "AIzaSyDRMe1DhrqjD9fuMf02mIrI_beR-7_9b-U",
    "AIzaSyAnZOdTF_twsc5yM-Qslux1qmb38FjfhXI",
    "AIzaSyCTAVlY5Fzgx1Psk0clt4rS_QsChcb3HJI",
    "AIzaSyCLKfl2CYBbc0TDosJ7fqSOZNgCm87eo34",
    "AIzaSyCycAH3QRGn9HNwX58ai4PUDTc-uIzwr1A",
]

GEMINI_API_KEYS = [FREE_API_KEY] + EXTRA_FREE_KEYS + [
    os.getenv(f"GEMINI_API_KEY_{i}") for i in range(1, 10)
    if os.getenv(f"GEMINI_API_KEY_{i}")
]
if os.getenv("AI_API_KEY"):
    GEMINI_API_KEYS.append(os.getenv("AI_API_KEY"))

# --- Free Tier Rate Limits (from AI Studio: Gemini 1.5 Flash Lite) ---
FREE_TIER_RPM = 15          # Actual limit: 15 RPM
FREE_TIER_RPD = 1500        # Actual limit: 1500 RPD
FREE_TIER_DELAY = 4.1       # Seconds between calls (60/15 = 4s)

# --- Firebase ---
SERVICE_ACCOUNT_KEY = "/home/sadrikov49/Desktop/ALFA SAT PROJECT/llm-pipeline/serviceAccountKey.json"
FIRESTORE_PROJECT_ID = "alfasatuz"
ADMIN_UID = "Kz0qlMcOk9XmPLGytEHm2nOYMhY2"

# --- Telegram (for image uploads) ---
TELEGRAM_BOT_TOKENS = [
    "8346966004:AAEjpZCJ1bdo177gQw4K_kgk8Pk8W1z0OHM",
    "8612742009:AAG19ZeeUoTF-8VRYkBtZF6yPxETD_9_8BU",
    "8479455437:AAE28dE-T2z7jzL1oVcdha0rX6sLhiUpqHg",
]
TELEGRAM_CHANNEL_ID = "-1002674756395"

# --- Pipeline Settings ---
DEFAULT_CATEGORY = "real_exam"

# --- Processing ---
PAGE_DPI = 300
BATCH_SIZE = 3
RATE_LIMIT_DELAY = 1
MAX_RETRIES = 3
