
import fitz
doc = fitz.open("/home/sadrikov49/Desktop/ALFA SAT PROJECT/pdfs/2025 Nov US-A @EliteXSAT.pdf")
for i in range(16, min(24, len(doc))):
    text = doc[i].get_text()
    print(f"--- Page {i+1} ---")
    print(text[:500].replace("\n", " "))
    print("-" * 20)
