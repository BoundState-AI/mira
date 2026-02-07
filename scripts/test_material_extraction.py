"""Quick test of material extraction on a few drawings."""

import sys
import logging
import base64
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mira.miul.v1_archive.dt_miul_builder import DTMIULBuilder

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Use builder to get properly configured client
builder = DTMIULBuilder(miul_number="TEST", project="TEST")
client = builder._get_client()

MATERIAL_PROMPT = """Extract material and process specifications from this engineering drawing.

CRITICAL - WHERE TO FIND MATERIALS:
1. MATERIALS TABLE - Look for a small table with "MATERIALS" header listing items like:
   | ITEM | DESCRIPTION | SPECIFICATION |
   |  1   | ALUMINUM    | AMS 4027      |
   |  2   | STAINLESS   | AMS 5643      |

2. FLAGGED NOTES - Look for notes with a triangle/flag symbol (▷ or △) pointing at them.
   These flags indicate important callouts including materials. Example:
   △1 MATERIAL: 6061-T6 ALUMINUM PER AMS 4027

3. TITLE BLOCK - Fields labeled MATERIAL, MAT'L, MATL, or MATERIAL SPEC

4. NUMBERED NOTES - Notes section with entries like:
   1. MATERIAL: ALUMINUM 6061-T6 PER AMS 4027
   2. FINISH: ANODIZE PER MIL-A-8625 TYPE II

5. GENERAL NOTES area - Usually bottom left or right of drawing

OUTPUT FORMAT (JSON):
{
    "materials": [
        {
            "part_number": "DRAWING-NUMBER-FROM-TITLE-BLOCK",
            "designation": "6061-T6 ALUMINUM",
            "material_spec": "AMS 4027",
            "process_spec": "ANODIZE PER MIL-A-8625 TYPE II",
            "form": "PLATE"
        }
    ]
}

RULES:
1. LOOK CAREFULLY at tables labeled "MATERIALS" - extract ALL items listed
2. LOOK for triangle/flag symbols (△ ▷) pointing at notes - these often contain material info
3. Extract the part number from the TITLE BLOCK (bottom right corner)
4. One entry per drawing document
5. Return empty strings for fields not explicitly stated on the drawing

Return ONLY valid JSON."""


def extract_materials(pdf_path: Path) -> dict:
    """Extract materials from a single PDF."""
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

    response_text = response.content[0].text

    # Parse JSON
    if "```json" in response_text:
        json_str = response_text.split("```json")[1].split("```")[0]
    elif "```" in response_text:
        json_str = response_text.split("```")[1].split("```")[0]
    else:
        json_str = response_text

    return json.loads(json_str.strip())


def main():
    # Test on 2 GPE drawings
    gpe_dir = Path(r"C:\Users\jwilde2\Desktop\GPE")
    test_files = [
        gpe_dir / "GPE-101-A (Faceplate Drawing).pdf",
        gpe_dir / "GPE-201-A (Backplate Drawing).pdf",
    ]

    logger.info("="*60)
    logger.info("MATERIAL EXTRACTION TEST - GPE")
    logger.info("="*60)

    for pdf in test_files:
        if not pdf.exists():
            logger.warning(f"File not found: {pdf}")
            continue

        logger.info(f"\n--- {pdf.name} ---")
        try:
            result = extract_materials(pdf)
            for mat in result.get("materials", []):
                logger.info(f"  Part: {mat.get('part_number', 'N/A')}")
                logger.info(f"    Designation: {mat.get('designation', '')}")
                logger.info(f"    Material Spec: {mat.get('material_spec', '')}")
                logger.info(f"    Process Spec: {mat.get('process_spec', '')}")
                logger.info(f"    Form: {mat.get('form', '')}")
        except Exception as e:
            logger.error(f"  ERROR: {e}")

    # Test on 2 DMLLV drawings
    dmllv_dir = Path(r"C:\Users\jwilde2\Desktop\DMLLV")
    test_files = [
        dmllv_dir / "MER07545-001.DRW_-.12_RELEASED.pdf",
        dmllv_dir / "MER07546-001.DRW_-.9_RELEASED.pdf",
    ]

    logger.info("\n" + "="*60)
    logger.info("MATERIAL EXTRACTION TEST - DMLLV")
    logger.info("="*60)

    for pdf in test_files:
        if not pdf.exists():
            logger.warning(f"File not found: {pdf}")
            continue

        logger.info(f"\n--- {pdf.name} ---")
        try:
            result = extract_materials(pdf)
            for mat in result.get("materials", []):
                logger.info(f"  Part: {mat.get('part_number', 'N/A')}")
                logger.info(f"    Designation: {mat.get('designation', '')}")
                logger.info(f"    Material Spec: {mat.get('material_spec', '')}")
                logger.info(f"    Process Spec: {mat.get('process_spec', '')}")
                logger.info(f"    Form: {mat.get('form', '')}")
        except Exception as e:
            logger.error(f"  ERROR: {e}")


if __name__ == "__main__":
    main()
