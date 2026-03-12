"""
Standalone test for the hybrid image cropping algorithm.
Tests cropping on known diagram pages from a real SAT PDF without making any API calls.
Saves cropped images locally so we can visually inspect quality.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import fitz
import config

# Import the upload function
from pipeline import upload_image_to_telegram

PDF_PATH = "../pdfs/2024 Nov US-A @EliteXSAT.pdf"

# Simulated AI bounding boxes — we pretend the AI told us these pages have images
# These are normalized 0.0-1.0 coordinates
SIMULATED_QUESTIONS = [
    {"questionNumber": 11, "module": 3, "page": 66, "x0": 0.05, "y0": 0.05, "x1": 0.75, "y1": 0.75},
    {"questionNumber": 12, "module": 3, "page": 67, "x0": 0.05, "y0": 0.05, "x1": 0.75, "y1": 0.75},
    {"questionNumber": 18, "module": 3, "page": 73, "x0": 0.05, "y0": 0.05, "x1": 0.75, "y1": 0.75},
    {"questionNumber": 22, "module": 3, "page": 77, "x0": 0.05, "y0": 0.05, "x1": 0.75, "y1": 0.75},
    {"questionNumber": 15, "module": 4, "page": 92, "x0": 0.05, "y0": 0.05, "x1": 0.75, "y1": 0.75},
    {"questionNumber": 17, "module": 4, "page": 94, "x0": 0.05, "y0": 0.05, "x1": 0.75, "y1": 0.75},
]

os.makedirs("test_crops", exist_ok=True)

doc = fitz.open(PDF_PATH)

for sq in SIMULATED_QUESTIONS:
    page_num = sq["page"] - 1  # 0-indexed
    page = doc[page_num]
    rect = page.rect
    page_area = rect.width * rect.height

    print(f"\n📸 M{sq['module']} Q{sq['questionNumber']} on page {sq['page']}...")
    print(f"   Page: {rect.width:.0f}×{rect.height:.0f}")

    # Convert AI bbox
    bx0, by0, bx1, by1 = sq["x0"], sq["y0"], sq["x1"], sq["y1"]
    x0, x1 = sorted([bx0 * rect.width, bx1 * rect.width])
    y0, y1 = sorted([by0 * rect.height, by1 * rect.height])
    ai_rect = fitz.Rect(x0, y0, x1, y1)
    print(f"   AI bbox: ({x0:.0f},{y0:.0f}) to ({x1:.0f},{y1:.0f})")

    # LAYER 1: Find native images (skip full-page scans >80%)
    native_rects = []
    for img_info in page.get_image_info():
        img_rect = fitz.Rect(img_info["bbox"])
        img_area = img_rect.width * img_rect.height
        pct = img_area / page_area * 100
        if img_rect.width > 20 and img_rect.height > 20 and img_area < page_area * 0.40:
            native_rects.append(img_rect)
            print(f"   Native image: {img_rect.width:.0f}×{img_rect.height:.0f} ({pct:.0f}% of page) ✅ kept")
        else:
            print(f"   Native image: {img_rect.width:.0f}×{img_rect.height:.0f} ({pct:.0f}% of page) ❌ skipped")

    # LAYER 2: Match
    best_match = None
    best_overlap = 0.0
    for nr in native_rects:
        intersection = ai_rect & nr
        if intersection.is_empty:
            continue
        overlap_area = intersection.width * intersection.height
        ai_area = max(1.0, ai_rect.width * ai_rect.height)
        overlap_ratio = overlap_area / ai_area
        if overlap_ratio > best_overlap:
            best_overlap = overlap_ratio
            best_match = nr

    if best_match and best_overlap > 0.1:
        crop_base = fitz.Rect(best_match)
        print(f"   🎯 Snapped to native image ({best_overlap:.0%} overlap)")
    else:
        crop_base = fitz.Rect(ai_rect)
        print(f"   📐 Using AI bbox (no native match)")

    # LAYER 3: Smart expansion (drawings + text)
    drawing_count = 0
    for path in page.get_drawings():
        path_rect = fitz.Rect(path["rect"])
        if path_rect.width > 0 and path_rect.height > 0 and crop_base.intersects(path_rect):
            crop_base.include_rect(path_rect)
            drawing_count += 1

    text_count = 0
    for block in page.get_text("blocks"):
        block_rect = fitz.Rect(block[:4])
        if block_rect.width < rect.width * 0.45 and block_rect.height < rect.height * 0.15:
            if crop_base.intersects(block_rect):
                crop_base.include_rect(block_rect)
                text_count += 1

    print(f"   Expanded: +{drawing_count} drawings, +{text_count} text blocks")

    # Padding
    cw, ch = crop_base.width, crop_base.height
    pad_x = max(12.0, cw * 0.10)
    pad_y = max(12.0, ch * 0.10)
    crop_rect = fitz.Rect(
        max(0, crop_base.x0 - pad_x),
        max(0, crop_base.y0 - pad_y),
        min(rect.width, crop_base.x1 + pad_x),
        min(rect.height, crop_base.y1 + pad_y)
    )

    crop_w = crop_rect.width
    crop_h = crop_rect.height
    print(f"   Final crop: {crop_w:.0f}×{crop_h:.0f}pt")

    # Validation
    if crop_w < 50 or crop_h < 50:
        print(f"   ⚠️ Too small, skipping")
        continue
    if crop_w > rect.width * 0.92 and crop_h > rect.height * 0.92:
        print(f"   ⚠️ Covers entire page, skipping")
        continue
    aspect = max(crop_w, crop_h) / max(1, min(crop_w, crop_h))
    if aspect > 6.0:
        print(f"   ⚠️ Bad aspect ratio ({aspect:.1f}:1), skipping")
        continue

    # Render at 3x
    pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=crop_rect)
    img_bytes = pix.tobytes("png")

    # Blank check
    samples = pix.samples
    if len(samples) > 100:
        avg_val = sum(samples[:3000:3]) / min(1000, len(samples) // 3)
        if avg_val > 252:
            print(f"   ⚠️ Blank crop (avg: {avg_val:.0f}), skipping")
            continue
        print(f"   Pixel avg: {avg_val:.0f} (good)")

    # Save locally
    fname = f"test_crops/M{sq['module']}_Q{sq['questionNumber']}.png"
    with open(fname, "wb") as f:
        f.write(img_bytes)
    print(f"   💾 Saved: {fname} ({len(img_bytes)//1024}KB)")

    # Upload to Telegram
    tg_url = upload_image_to_telegram(img_bytes)
    if tg_url:
        print(f"   ✅ Telegram: {tg_url}")
    else:
        print(f"   ⚠️ Telegram upload failed")

doc.close()
print("\n🏁 Done! Check test_crops/ folder for visual inspection.")
