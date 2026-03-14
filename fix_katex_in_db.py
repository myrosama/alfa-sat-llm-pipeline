import firebase_admin
from firebase_admin import credentials, firestore
import re
from bs4 import BeautifulSoup
import sys
import os

# Ensure the script runs with correct path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from config import SERVICE_ACCOUNT_KEY
except ImportError:
    SERVICE_ACCOUNT_KEY = "/home/sadrikov49/Desktop/ALFA SAT PROJECT/llm-pipeline/serviceAccountKey.json"

# Initialize Firebase
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate(SERVICE_ACCOUNT_KEY)
        firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"Error initializing Firebase: {e}")
    sys.exit(1)

db = firestore.client()

def clean_html(text):
    if not text or not isinstance(text, str): 
        return text
    
    # 1. Quick byte-order-mark replacements
    text = text.replace('&#xFEFF;', '')
    text = text.replace('\\ufeff', '')
    text = text.replace('\ufeff', '')
    
    soup = BeautifulSoup(text, 'html.parser')
    
    # 2. Extract inner text from existing (possibly nested) ql-formula spans and replace with $ math $
    for span in soup.find_all('span', class_='ql-formula'):
        latex = span.get_text().strip()
        span.replace_with(f'${latex}$')
        
    # 3. Un-center small inline fractions that got accidentally wrapped in <p class="ql-align-center">
    for p in soup.find_all('p', class_='ql-align-center'):
        content = p.get_text().strip()
        # If it's pure math (and relatively short), un-center it
        if ('\\' in content or '^' in content or '_' in content) and len(content) < 50:
            if not p.find('img'): # Don't destroy image centering
                p.replace_with(f'${content}$')
                
    cleaned = str(soup)
    
    # 4. Standardize paragraph spacing
    cleaned = cleaned.replace('</p><p>', '</p> <p>')
    
    # 5. Re-wrap math correctly
    def format_repl(match):
        latex = match.group(1).strip()
        return f'<span class="ql-formula" data-value="{latex}">\ufeff<span contenteditable="false"><span class="katex">{latex}</span></span>\ufeff</span>'

    cleaned = re.sub(r'\$\$(.*?)\$\$', lambda m: format_repl(m), cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'\$([^\$]+?)\$', lambda m: format_repl(m), cleaned)
    
    return cleaned

def fix_katex_for_test(test_id):
    questions_ref = db.collection('tests').doc(test_id).collection('questions')
    docs = questions_ref.stream()
    
    updated_count = 0
    total_count = 0
    
    for doc in docs:
        total_count += 1
        data = doc.to_dict()
        needs_update = False
        
        # Check all text fields
        fields_to_check = ['passage', 'prompt', 'explanation']
        for field in fields_to_check:
            original = data.get(field, '')
            if original:
                cleaned = clean_html(original)
                if cleaned != original:
                    data[field] = cleaned
                    needs_update = True
                    
        # Check options
        options = data.get('options', {})
        if options and isinstance(options, dict):
            for k, original_opt in options.items():
                if original_opt and isinstance(original_opt, str):
                    cleaned_opt = clean_html(original_opt)
                    if cleaned_opt != original_opt:
                        options[k] = cleaned_opt
                        needs_update = True
            data['options'] = options
            
        if needs_update:
            questions_ref.doc(doc.id).update(data)
            updated_count += 1
            print(f"Updated question {data.get('questionNumber', 'Unknown')} in module {data.get('module', 'Unknown')}.")
            
    print(f"Finished processing test {test_id}. Updated {updated_count} out of {total_count} questions.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 fix_katex_in_db.py <test_id>")
        sys.exit(1)
    
    test_id = sys.argv[1]
    print(f"Starting KaTeX fix for test: {test_id}")
    fix_katex_for_test(test_id)
