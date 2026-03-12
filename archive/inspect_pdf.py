
import fitz
doc = fitz.open("/home/sadrikov49/Desktop/ALFA SAT PROJECT/pdfs/2025 Nov US-A @EliteXSAT.pdf")
for i in range(len(doc)):
    text = doc[i].get_text().lower()
    if "module" in text or "section" in text or "directions" in text:
        print(f"Page {i+1}:")
        if "module 1" in text: print("  - Module 1")
        if "module 2" in text: print("  - Module 2")
        if "section 1" in text: print("  - Section 1")
        if "section 2" in text: print("  - Section 2")
        if "directions" in text: print("  - Directions")
        if "reference" in text: print("  - Reference")
