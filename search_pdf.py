import fitz
doc = fitz.open("pdfs/2025 Nov Int-A @EliteXSAT.pdf")
for i in range(len(doc)):
    text = doc[i].get_text().lower()
    if "question 12" in text and "module 3" in text:
        print(f"M3 Q12 found on Page {i+1}")
    if "module 3" in text and "question 1" in text:
        print(f"M3 Q1 found on Page {i+1}")
doc.close()
