import fitz
import sys

def check_pdf(path):
    doc = fitz.open(path)
    text_len = 0
    for i in range(min(5, len(doc))):
        text_len += len(doc[i].get_text("text").strip())
    
    print(f"Total text chars in first 5 pages: {text_len}")
    
if __name__ == "__main__":
    check_pdf(sys.argv[1])
