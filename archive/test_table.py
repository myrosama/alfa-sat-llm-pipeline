import google.generativeai as genai
import json
import os
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash-lite",
    generation_config={
        "temperature": 0.0,
        "response_mime_type": "application/json",
    }
)

prompt = """Extract the math questions from this image.
RULES:
- DATA TABLES: If the question includes a data table, YOU MUST extract it completely as a native HTML `<table>`. Example: `<table><thead><tr><th>x</th><th>y</th></tr></thead><tbody><tr><td>2</td><td>4</td></tr></tbody></table>`. ABSOLUTELY NO MARKDOWN TABLES. DO NOT use pipes (|) or dashes (-). Insert the HTML table into the `passage` or `prompt` where it belongs. Apply standard table borders in HTML.
- "prompt": the full question text.
- "options": dictionary of A, B, C, D choices.

Return a JSON array like:
[{
    "prompt": "...",
    "passage": "...",
    "options": {"A": "...", "B": "...", "C": "...", "D": "..."}
}]
"""

path = "dummy_test.pdf"
print(f"Uploading {path}...")
pdf_file = genai.upload_file(path, mime_type="application/pdf")

response = model.generate_content([pdf_file, prompt])
print(response.text)
