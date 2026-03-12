"""
ALFA SAT — Centralized Gemini Prompts & Taxonomy
=================================================
All prompts and valid domain/skill mappings in one place.
"""

# ─────────────────────────────────────────────
#  Domain → Skill Taxonomy (MUST match exactly)
# ─────────────────────────────────────────────

RW_TAXONOMY = {
    "Information and Ideas": [
        "Central Ideas and Details",
        "Command of Evidence",
        "Inferences",
    ],
    "Craft and Structure": [
        "Words in Context",
        "Text Structure and Purpose",
        "Cross-Text Connections",
    ],
    "Expression of Ideas": [
        "Rhetorical Synthesis",
        "Transitions",
    ],
    "Standard English Conventions": [
        "Boundaries",
        "Form, Structure, and Sense",
    ],
}

MATH_TAXONOMY = {
    "Algebra": [
        "Linear equations in one variable",
        "Linear functions",
        "Systems of two linear equations in two variables",
        "Linear inequalities in one or two variables",
    ],
    "Advanced Math": [
        "Equivalent expressions",
        "Nonlinear equations in one variable and systems of equations in two variables",
        "Nonlinear functions",
    ],
    "Problem-Solving and Data Analysis": [
        "Ratios, rates, proportional relationships, and units",
        "Percentages",
        "One-variable data: distributions and measures of center and spread",
        "Two-variable data: models and scatterplots",
        "Probability and conditional probability",
        "Inference from sample statistics and margin of error",
    ],
    "Geometry and Trigonometry": [
        "Area and volume",
        "Lines, angles, and triangles",
        "Right triangles and trigonometry",
        "Circles",
    ],
}


def get_taxonomy_for_module(module: int) -> dict:
    """Return the correct taxonomy dict for a given module number."""
    if module <= 2:
        return RW_TAXONOMY
    return MATH_TAXONOMY


def format_taxonomy_for_prompt(taxonomy: dict) -> str:
    """Format taxonomy dict into a readable string for the prompt."""
    lines = []
    for domain, skills in taxonomy.items():
        lines.append(f'  "{domain}"')
        for skill in skills:
            lines.append(f'    → "{skill}"')
    return "\n".join(lines)


# ─────────────────────────────────────────────
#  Extraction Prompts
# ─────────────────────────────────────────────

RW_EXTRACTION_PROMPT = """You are an expert SAT question parser. You will receive an image of one or more SAT Reading & Writing questions. Extract each question precisely.

RULES:
- "passage" = the reading passage text (often on the LEFT side of the page). Format with HTML tags: <p>, <b>, <i>, <u>. Preserve all original formatting, line breaks within paragraphs, italicized titles, etc. If no passage exists, return empty string "".
- NOTES QUESTIONS (Rhetorical Synthesis): If the question contains a list of bulleted notes (e.g., "While researching a topic, a student has taken the following notes:"), YOU MUST extract the entire bulleted list as a clean HTML `<ul>` with `<li>` tags for each bullet. DO NOT use plain dashes or stars. This is MANDATORY.
- If a question references "Text 1" and "Text 2", the passage field must include BOTH texts, clearly labeled with <b>Text 1</b> and <b>Text 2</b>.
- "prompt" = the question text ONLY (on the RIGHT side). HTML formatted with <p> tags. Do NOT include the answer choices in the prompt.
- Options A, B, C, D = HTML formatted answer choices. Never include the letter prefix itself (no "A)", "B.", etc.).
- "correctAnswer" = infer from visual cues (checkmark, circle, bolding, highlighting). If no visual cue, pick the most defensible answer based on SAT standards.
- "domain" and "skill" = must EXACTLY match one of the values below. Do not paraphrase or abbreviate.
- "format" = always "mcq" for Reading & Writing unless you see a box for student-produced response.
- "explanation" = write a clear 2-3 sentence explanation of WHY the correct answer is right. HTML formatted.
- "hasImage" = set to true ONLY if the question contains a chart, graph, table as an image, or diagram that cannot be represented as text. Data tables that CAN be represented as text should be included in the passage field instead.
- IMAGE BOUNDING BOX (CRITICAL): If hasImage is true, you MUST provide the "image_bbox" object. This is MANDATORY. Do not omit it. Provide the page number and normalized coordinates (0.0 to 1.0, where 0,0 is top-left and 1,0 is top-right) of the visual element. Draw the box TIGHTLY around ONLY the image/chart/graph — exclude surrounding question text or white space.
- MULTI-PAGE QUESTIONS: If a question spans across two pages, combine the text (passage/prompt) into a single continuous HTML string. Identify the `imagePage` as the page where the visual element actually resides.
- INTERNAL NUMBERING (CRITICAL): Regardless of the number printed in the PDF (e.g., if you see Question 56 in Module 2), always map it to the relative question number for that module starting from 1. For example, the first question in Module 2 should always be "questionNumber": 1.
- If the image contains multiple questions, return an array with one object per question.
- If the page is a directions page, title page, or reference sheet, return an empty array [].
- Do NOT invent or fabricate any questions.

CRITICAL FORMATTING:
- PURE TEXT + HTML ONLY. No LaTeX, no KaTeX, no $ delimiters.
- For blanks in sentences: use "________" (8 underscores).

TAXONOMY (use EXACTLY these strings):
""" + format_taxonomy_for_prompt(RW_TAXONOMY) + """

Return a JSON array of objects with these fields (CRITICAL: Do not omit image_bbox if hasImage is true):
[{
  "questionNumber": <int>,
  "sectionType": "rw",
  "passage": "<p>...</p>",
  "prompt": "<p>...</p>",
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
  "correctAnswer": "A"|"B"|"C"|"D",
  "format": "mcq",
  "domain": "...",
  "skill": "...",
  "explanation": "<p>...</p>",
  "hasImage": false,
  "image_bbox": {"page": 1, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
}]
"""

MATH_EXTRACTION_PROMPT = """You are an expert SAT Math question parser. You will receive an image of one or more SAT Math questions. Extract each question precisely.

RULES:
- "passage" = STIMULUS area. If the question has a preamble, a large centered equation, a function definition (e.g. "The function $f$ is defined by..."), or a data table description, PLACE IT HERE. This balances the UI (Left: Stimulus, Right: Prompt).
- "prompt" = the specific question being asked (e.g., "What is the value of $x$?").
- FORMULAS: ALL mathematical expressions, variables, and formulas MUST be wrapped in LaTeX delimiters $...$.
- Example: "If $2x + 3 = 7$, what is the value of $x$?"
- Options A-D = Wrap math in $...$ where needed. NEITHER include the letter prefix (NO "A)", "B.", etc.) NOR any trailing/leading spaces.
- "format" = "mcq" if there are A/B/C/D options. "fill-in" if the question says "enter your answer" or has a grid-in box with NO options.
- "correctAnswer" = letter for mcq ("A","B","C","D"), or the numeric value as a string for fill-in (e.g., "4", "3/2", "0.75").
- "fillInAnswer" = for fill-in questions, same as correctAnswer. For mcq, empty string "".
- "explanation" = step-by-step solution. Use $...$ for all math. HTML formatted with <p> tags.
- "hasImage" = set to true if the question has a graph, geometric figure, coordinate plane, or complex table. 
- CRITICAL: NEVER try to represent geometry or coordinate planes as text. If an image exists, set hasImage: true and provide the bbox.
- IMAGE BOUNDING BOX (CRITICAL): If hasImage is true, you MUST provide the "image_bbox" object. This is MANDATORY. Do not omit it. Provide the page number (1-indexed) and normalized coordinates (0.0 to 1.0, where 0,0 is top-left and 1,0 is top-right) of the visual element. 
- TIGHT CROPPING: Draw the "image_bbox" TIGHTLY around ONLY the diagram, graph, or chart. DO NOT include any part of the question text, options, or page numbers in the bbox. This is for visual display only.
- MULTI-PAGE QUESTIONS: If a question spans across two pages, combine the text (passage/prompt) into a single continuous string with LaTeX. Identify the `imagePage` as the page where the visual element actually resides.
- INTERNAL NUMBERING (CRITICAL): Regardless of the number printed in the PDF (e.g., if you see Question 45 in Module 2), always map it to the relative question number for that module starting from 1. For example, the first question in the second Math module should be "questionNumber": 1.
- "domain" and "skill" = must EXACTLY match one of the values below.
- If the page shows a math reference sheet or directions page, return an empty array [].
- Do NOT invent or fabricate any questions.

TAXONOMY (use EXACTLY these strings):
""" + format_taxonomy_for_prompt(MATH_TAXONOMY) + """

Return a JSON array of objects with these fields (CRITICAL: Do not omit image_bbox if hasImage is true):
[{
  "questionNumber": <int>,
  "sectionType": "math",
  "passage": "<p>...</p>",
  "prompt": "<p>...</p>",
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
  "correctAnswer": "A"|"B"|"C"|"D",
  "fillInAnswer": "",
  "format": "mcq",
  "domain": "...",
  "skill": "...",
  "explanation": "<p>...</p>",
  "hasImage": false,
  "image_bbox": {"page": 1, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
}]

For fill-in questions, set options to {"A": "", "B": "", "C": "", "D": ""} and format to "fill-in".
If hasImage is false, you may omit the image_bbox field entirely. BUT IF IT IS TRUE, YOU MUST INCLUDE IT.
"""


CRITIC_PROMPT = """You are Agent 3: The SAT Quality Critic. 
Your job is to fix a broken or incomplete SAT question that was likely truncated due to a PDF page break or poor initial extraction.

You will receive:
1. The currently flawed JSON extraction for Question {q_num}.
2. The images of the pages where this question occurs (usually overlapping two pages).

YOUR TASK:
Reconstruct the ENTIRE question perfectly from the images. 
- If the `passage` or `prompt` was cut off mid-sentence, find the rest of the sentence on the next page and connect them smoothly.
- If this is a "Notes" question and the bullet points are missing from the `passage`, you MUST extract the full bulleted list as HTML `<ul>` and place it inside the `passage` field.
- Ensure the `prompt` and all `options` (A, B, C, D) are complete.
- Keep the exact same JSON format as the original extraction, but with the corrected, full text.

CRITICAL RULES:
- Output ONLY valid JSON representing the single corrected question object.
- DO NOT wrap the output in markdown blocks like ```json.
- Maintain all HTML tags (<p>, <b>, <ul>, <li>).
- For Math, maintain strict KaTeX delimiters: $...$.

Here is the flawed extraction you need to fix:
{flawed_json}
"""


GAP_FILL_PROMPT_RW = """You are Agent 2: The Gap Filler. 
Find Reading & Writing Question {q_num} (Module {module}) from the provided images and extract it. 
CRITICAL RULE: Return ONLY a valid JSON array containing this single question. Do not wrap in ```json.

Return a JSON array of objects with these fields:
[{{
  "questionNumber": {q_num},
  "sectionType": "rw",
  "passage": "<p>...</p>",
  "prompt": "<p>...</p>",
  "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
  "correctAnswer": "A"|"B"|"C"|"D",
  "format": "mcq",
  "domain": "...",
  "skill": "...",
  "explanation": "<p>...</p>",
  "hasImage": false
}}]
"""

GAP_FILL_PROMPT_MATH = """You are Agent 2: The Gap Filler. 
Find Math Question {q_num} (Module {module}) from the provided images and extract it. 
CRITICAL RULES: 
- Return ONLY a valid JSON array containing this single question. Do not wrap in ```json.
- All mathematical expressions, variables, and formulas MUST be wrapped in KaTeX delimiters $...$.

Return a JSON array of objects with these fields:
[{{
  "questionNumber": {q_num},
  "sectionType": "math",
  "passage": "",
  "prompt": "<p>...</p>",
  "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
  "correctAnswer": "A"|"B"|"C"|"D",
  "fillInAnswer": "",
  "format": "mcq",
  "domain": "...",
  "skill": "...",
  "explanation": "<p>...</p>",
  "hasImage": false
}}]

For fill-in questions, set options to {{"A": "", "B": "", "C": "", "D": ""}} and format to "fill-in".
"""
