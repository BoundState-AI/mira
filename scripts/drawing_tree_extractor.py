"""
Drawing Tree Extractor - Uses Claude Vision to extract hierarchical drawing trees from PDFs.

This tool sends PDF files directly to Claude's vision API and extracts the drawing tree
structure as JSON, with iterative validation until the extraction is correct.
"""

import anthropic
import base64
import json
import sys
from pathlib import Path


def load_pdf_as_base64(pdf_path: str) -> str:
    """Load a PDF file and return its base64 encoding."""
    with open(pdf_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def extract_drawing_tree(client: anthropic.Anthropic, pdf_base64: str, filename: str, previous_attempt: dict | None = None, feedback: str | None = None) -> dict:
    """
    Use Claude Vision to extract drawing tree structure from a PDF.

    Args:
        client: Anthropic client
        pdf_base64: Base64 encoded PDF content
        filename: Name of the PDF file for context
        previous_attempt: Previous extraction attempt for correction
        feedback: Feedback on what was wrong with previous attempt

    Returns:
        Extracted drawing tree as a dictionary
    """

    system_prompt = """You are an expert at analyzing engineering drawing trees (also called parts lists or assembly trees).
Your task is to extract the hierarchical structure from drawing tree PDFs into structured JSON.

A drawing tree shows:
- A root assembly at the top
- Sub-assemblies and parts branching below
- Each item has a part number (P/N) and description/name
- The hierarchy shows what parts belong to which assemblies

Output JSON schema:
{
    "document_info": {
        "drawing_number": "string - the document/drawing number",
        "title": "string - title of the drawing tree",
        "revision": "string - revision letter/number",
        "organization": "string - organization name if visible"
    },
    "root": {
        "part_number": "string",
        "name": "string - description/name of the part",
        "status": "string - status indicator if any (e.g., 'released', 'under development')",
        "children": [
            {
                "part_number": "string",
                "name": "string",
                "status": "string or null",
                "children": []  // recursive structure
            }
        ]
    },
    "legend": {
        "description": "any legend items explaining symbols/colors"
    }
}

IMPORTANT:
- Capture ALL parts visible in the tree - do not skip any
- Preserve the exact hierarchy shown by the connecting lines
- Part numbers must be exact - do not modify them
- Names/descriptions should be complete
- If a part has no children, use an empty array []
"""

    messages_content = [
        {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": pdf_base64
            }
        }
    ]

    user_prompt = f"Extract the complete drawing tree hierarchy from this PDF: {filename}\n\nReturn ONLY valid JSON matching the schema - no markdown, no explanation."

    if previous_attempt and feedback:
        user_prompt += f"\n\nPREVIOUS ATTEMPT HAD ERRORS:\n{feedback}\n\nPrevious JSON:\n{json.dumps(previous_attempt, indent=2)}\n\nPlease correct these issues and return the fixed JSON."

    messages_content.append({"type": "text", "text": user_prompt})

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        system=system_prompt,
        messages=[
            {"role": "user", "content": messages_content}
        ]
    )

    # Extract JSON from response
    response_text = response.content[0].text.strip()

    # Handle potential markdown code blocks
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        # Remove first and last lines (```json and ```)
        json_lines = []
        in_json = False
        for line in lines:
            if line.startswith("```") and not in_json:
                in_json = True
                continue
            elif line.startswith("```") and in_json:
                break
            elif in_json:
                json_lines.append(line)
        response_text = "\n".join(json_lines)

    return json.loads(response_text)


def validate_drawing_tree(client: anthropic.Anthropic, pdf_base64: str, extracted_tree: dict, filename: str) -> tuple[bool, str]:
    """
    Validate the extracted drawing tree against the PDF.

    Returns:
        Tuple of (is_valid, feedback_message)
    """

    system_prompt = """You are a quality assurance expert validating drawing tree extractions.
Compare the extracted JSON against the original PDF and identify any discrepancies.

Check for:
1. Missing parts - any parts in the PDF not in the JSON
2. Extra parts - any parts in the JSON not in the PDF
3. Wrong hierarchy - parts placed under wrong parent
4. Typos in part numbers or names
5. Missing or incorrect status indicators

Be thorough but fair - minor formatting differences are acceptable.
Minor punctuation differences (commas, etc.) are NOT issues.
Part number suffix conventions (like -001) are acceptable if consistent."""

    messages_content = [
        {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": pdf_base64
            }
        },
        {
            "type": "text",
            "text": f"""Validate this extracted drawing tree JSON against the PDF ({filename}).

EXTRACTED JSON:
{json.dumps(extracted_tree, indent=2)}

You MUST respond in EXACTLY this format (no other text before or after):
VALID: true
or
VALID: false
ISSUES:
- issue 1
- issue 2

If no real issues exist, respond with VALID: true
"""
        }
    ]

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        system=system_prompt,
        messages=[
            {"role": "user", "content": messages_content}
        ]
    )

    response_text = response.content[0].text.strip()

    # More robust parsing
    lines = response_text.split('\n')
    is_valid = False
    for line in lines:
        if line.strip().upper().startswith("VALID:"):
            val = line.split(":", 1)[1].strip().lower()
            is_valid = val == "true"
            break

    # Extract issues section
    if "ISSUES:" in response_text:
        issues = response_text.split("ISSUES:")[1].strip()
    elif "ISSUES" in response_text:
        issues = response_text.split("ISSUES")[1].strip()
    else:
        issues = response_text

    # If issues say "None" or similar, treat as valid
    if issues.lower().strip() in ["none", "none.", "no issues", "no issues found", ""]:
        is_valid = True

    return is_valid, issues


def count_parts(node: dict) -> int:
    """Count total parts in a tree node recursively."""
    count = 1
    for child in node.get("children", []):
        count += count_parts(child)
    return count


def process_pdf(pdf_path: str, max_iterations: int = 3) -> dict:
    """
    Process a single PDF and extract its drawing tree with validation loop.

    Args:
        pdf_path: Path to the PDF file
        max_iterations: Maximum correction iterations

    Returns:
        Validated drawing tree JSON
    """
    client = anthropic.Anthropic()

    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    print(f"\n{'='*60}")
    print(f"Processing: {path.name}")
    print(f"{'='*60}")

    pdf_base64 = load_pdf_as_base64(pdf_path)

    extracted_tree = None
    feedback = None

    for iteration in range(max_iterations):
        print(f"\n--- Iteration {iteration + 1}/{max_iterations} ---")

        # Extract
        print("Extracting drawing tree...")
        extracted_tree = extract_drawing_tree(
            client, pdf_base64, path.name,
            previous_attempt=extracted_tree if iteration > 0 else None,
            feedback=feedback if iteration > 0 else None
        )

        part_count = count_parts(extracted_tree.get("root", {}))
        print(f"Extracted {part_count} parts")

        # Validate
        print("Validating extraction...")
        is_valid, issues = validate_drawing_tree(client, pdf_base64, extracted_tree, path.name)

        if is_valid:
            print("[OK] Validation PASSED")
            return extracted_tree
        else:
            print("[X] Validation FAILED")
            print(f"Issues: {issues[:500]}...")  # Truncate long feedback
            feedback = issues

    print(f"\nMax iterations reached. Returning best effort extraction.")
    return extracted_tree


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python drawing_tree_extractor.py <pdf_path> [pdf_path2 ...]")
        print("\nExample:")
        print('  python drawing_tree_extractor.py "C:\\path\\to\\drawing.pdf"')
        sys.exit(1)

    results = {}

    for pdf_path in sys.argv[1:]:
        try:
            tree = process_pdf(pdf_path)
            results[Path(pdf_path).name] = tree

            # Save individual result
            output_path = Path(pdf_path).with_suffix(".json")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(tree, f, indent=2)
            print(f"\nSaved: {output_path}")

        except Exception as e:
            print(f"\nError processing {pdf_path}: {e}")
            results[Path(pdf_path).name] = {"error": str(e)}

    # Print summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for name, tree in results.items():
        if "error" in tree:
            print(f"  {name}: ERROR - {tree['error']}")
        else:
            part_count = count_parts(tree.get("root", {}))
            print(f"  {name}: {part_count} parts extracted")

    return results


if __name__ == "__main__":
    main()
