import os
import time
import requests
from dotenv import load_dotenv
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY_1")
genai.configure(api_key=api_key)

print(f"Testing with key starting: {api_key[:10]}...")

model = genai.GenerativeModel("gemini-2.0-flash")

# Try sending a 5MB payload of dummy text to see if it deadlocks
dummy_data = "a" * (5 * 1024 * 1024)

print(f"Sending 5MB payload to Gemini...")
t0 = time.time()
try:
    response = model.generate_content(
        [dummy_data[:100], dummy_data],
        generation_config={"temperature": 0.1}
    )
    print(f"Success! Took {time.time() - t0:.2f}s. Response: {response.text[:50]}")
except Exception as e:
    print(f"Failed! Exception: {e}")
