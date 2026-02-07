"""Debug material extraction - show raw response."""

import sys
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mira.miul.v1_archive.dt_miul_builder import DTMIULBuilder

builder = DTMIULBuilder(miul_number="TEST", project="TEST")
client = builder._get_client()

MATERIAL_PROMPT = """Extract material and process specifications from this engineering drawing.

CRITICAL - WHERE TO FIND MATERIALS:
1. MATERIALS TABLE - Look for a small table with "MATERIALS" header
2. FLAGGED NOTES - Notes with a triangle/flag symbol (▷ or △)
3. TITLE BLOCK - Fields labeled MATERIAL, MAT'L, MATL
4. NUMBERED NOTES - Notes section with material info
5. GENERAL NOTES area

OUTPUT FORMAT (JSON):
{
    "materials": [
        {
            "part_number": "DRAWING-NUMBER",
            "designation": "MATERIAL NAME",
            "material_spec": "SPECIFICATION",
            "process_spec": "FINISH/COATING",
            "form": "FORM"
        }
    ]
}

Return ONLY valid JSON."""

# Test GPE-101
pdf_path = Path(r"C:\Users\jwilde2\Desktop\GPE\GPE-101-A (Faceplate Drawing).pdf")
pdf_bytes = pdf_path.read_bytes()
pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=2000,
    messages=[{
        "role": "user",
        "content": [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": pdf_base64,
                }
            },
            {"type": "text", "text": MATERIAL_PROMPT}
        ]
    }]
)

print("="*60)
print("RAW RESPONSE FROM GPE-101:")
print("="*60)
print(response.content[0].text)
