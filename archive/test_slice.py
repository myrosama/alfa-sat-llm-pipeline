import cv2
import numpy as np
import fitz
import sys

def slice_page(pdf_path, page_num):
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    
    # Render at high DPI
    zoom = 2.0
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    if pix.n == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    elif pix.n == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Thresholding: text is black (0), background is white (255)
    # Also removes the light gray watermark
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    
    # Sum pixels horizontally to find blank rows
    row_sums = np.sum(thresh, axis=1)
    
    # Find rows with absolutely no text
    blank_rows = row_sums < 1000  # very low threshold to allow some noise
    
    splits = [0]
    in_blank = True
    for i, is_blank in enumerate(blank_rows):
        if is_blank and not in_blank:
            in_blank = True
        elif not is_blank and in_blank:
            # Transition from blank to text: this could be a split point
            # Only if it's somewhat far from previous split (min height of a block)
            if i - splits[-1] > 200:
                splits.append(i - 20) # step back a little for padding
            in_blank = False
            
    splits.append(img.shape[0])
    
    print(f"Page {page_num} slice points: {splits}")
    for i in range(len(splits) - 1):
        y0, y1 = splits[i], splits[i+1]
        if y0 < 0: y0 = 0
        if y1 > img.shape[0]: y1 = img.shape[0]
        
        chunk = img[y0:y1, :]
        if chunk.shape[0] > 100:  # Ignore tiny slivers (like page numbers)
            cv2.imwrite(f"slice_{page_num}_{i}.png", chunk)
            print(f"Saved slice_{page_num}_{i}.png, size {chunk.shape}")

if __name__ == "__main__":
    slice_page(sys.argv[1], int(sys.argv[2]))
