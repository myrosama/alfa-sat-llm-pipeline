import pipeline
import json

pdf_path = '../TESTS/Test 1.pdf'
pipeline.init_firebase()

sections = pipeline.detect_section_pages(pdf_path)
print(f"Math Pages: {sections['math']}")

math_prompt = pipeline.FULL_PDF_MATH_PROMPT.replace('__START__', str(sections['math'][0])).replace('__END__', str(sections['math'][1]))

print('Running isolated Math Extraction...')
res = pipeline.call_gemini_with_pdf(pdf_path, math_prompt, 'Math testing')
print(f'Result length: {len(res) if res else 0}')
with open('debug_math_output.json', 'w', encoding='utf-8') as f:
    json.dump(res, f, indent=2)
print('Wrote output to debug_math_output.json')
