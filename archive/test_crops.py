import json, fitz

if __name__ == "__main__":
    with open("output/debug_raw.json", "r") as f:
        content = f.read()
        blocks = content.split("--- RAW LLM RESPONSE ---")
        rw_block = [b for b in blocks if "questionNumber" in b][0]
        start = rw_block.find("[")
        end = rw_block.rfind("]") + 1
        data = json.loads(rw_block[start:end])
    
    doc = fitz.open("../pdfs/2023 Oct Int-B @EliteXSAT.pdf")
    
    for q in data:
        if "image_bbox" in q:
            bbox = q["image_bbox"]
            page_num = bbox.get("page", 1) - 1
            page = doc[page_num]
            rect = page.rect
            
            bx0, by0, bx1, by1 = bbox.get("x0", 0), bbox.get("y0", 0), bbox.get("x1", 1), bbox.get("y1", 1)
            # Normalize
            if max(bx0, by0, bx1, by1) > 1.0:
                if max(bx0, bx1) > 1000 or max(by0, by1) > 1000:
                    bx0 = bx0 / rect.width
                    bx1 = bx1 / rect.width
                    by0 = by0 / rect.height
                    by1 = by1 / rect.height
                else:
                    bx0, by0, bx1, by1 = bx0/1000.0, by0/1000.0, bx1/1000.0, by1/1000.0

            # Smart Padding
            bw = bx1 - bx0
            bh = by1 - by0
            bx0 -= bw * 0.00
            bx1 += bw * 0.08
            by0 -= bh * 0.05
            by1 += bh * 1.34

            bx0, by0 = max(0.0, min(1.0, bx0)), max(0.0, min(1.0, by0))
            bx1, by1 = max(0.0, min(1.0, bx1)), max(0.0, min(1.0, by1))

            x0, x1 = sorted([bx0 * rect.width, bx1 * rect.width])
            y0, y1 = sorted([by0 * rect.height, by1 * rect.height])
            
            crop_base = fitz.Rect(x0, y0, x1, y1)
            
            # Expansion logic
            try:
                for path in page.get_drawings():
                    path_rect = fitz.Rect(path["rect"])
                    if path_rect.width > 0 and path_rect.height > 0:
                        if crop_base.intersects(path_rect):
                            crop_base.include_rect(path_rect)
            except Exception: pass
            
            try:
                text_blocks = page.get_text("blocks")
                for block in text_blocks:
                    block_rect = fitz.Rect(block[:4])
                    if crop_base.intersects(block_rect):
                        overlap = abs(crop_base & block_rect)
                        b_area = block_rect.width * block_rect.height
                        if b_area > 0 and (overlap / b_area) > 0.3:
                            crop_base.include_rect(block_rect)
            except Exception: pass

            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=crop_base)
            out_file = f"/home/sadrikov49/.gemini/antigravity/brain/83407ecb-c803-401d-a895-a05013b60df3/final_crop_Q{q.get('questionNumber')}.png"
            pix.save(out_file)
            print("Saved", out_file)
