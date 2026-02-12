#!/usr/bin/env python3
"""
Shall Statement Extractor - Local-Only Processing

Extracts obligation statements from PDF text:
  Pass 1: PyMuPDF text extraction + regex
  Pass 2: Local Ollama LLM classification (optional)

Output is always written to JSON + summary text.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import socket
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


# ============================================================================
# Models
# ============================================================================

OBLIGATION_KEYWORDS = {
    "shall": "mandatory",
    "shall not": "prohibition",
    "must": "mandatory",
    "must not": "prohibition",
    "is required to": "mandatory",
    "is required": "mandatory",
    "required": "mandatory",
    "is prohibited": "prohibition",
    "prohibited": "prohibition",
    "will": "intent",
    "should": "recommendation",
    "should not": "recommendation",
    "may": "permission",
    "may not": "prohibition",
}

OBLIGATION_PATTERN = re.compile(
    r"(?:^|(?<=\.\s)|(?<=\n))"
    r"([^.;\n]*?"
    r"\b(shall not|shall|must not|must|is required to|is required|required|"
    r"is prohibited|prohibited|should not|should|may not|may|will)\b"
    r"[^.;\n]*)"
    r"[.;]?",
    re.IGNORECASE | re.MULTILINE,
)

SECTION_PATTERN = re.compile(
    r"(?:^|\n)\s*"
    r"(\d+(?:\.\d+)*)"
    r"[\s.:\-]+"
    r"([A-Z][^\n]{0,80})",
    re.MULTILINE,
)


@dataclass
class ShallStatement:
    id: int
    page: int
    section: str
    obligation_keyword: str
    obligation_type: str
    statement_text: str
    subject: str
    requirement: str
    context: str
    category: str = ""
    confidence: float = 1.0


@dataclass
class ExtractionResult:
    source_file: str
    total_pages: int
    extraction_date: str
    total_statements: int
    by_type: dict = field(default_factory=dict)
    statements: list[ShallStatement] = field(default_factory=list)


# ============================================================================
# Pass 1 extraction
# ============================================================================

NOISE_TERMS = (
    "page ",
    "table of contents",
    "revision history",
    "export controlled",
    "proprietary",
)


def _detect_current_section(text: str, char_pos: int) -> str:
    best_section = ""
    for match in SECTION_PATTERN.finditer(text):
        if match.start() <= char_pos:
            best_section = match.group(1).strip()
        else:
            break
    return best_section


def _extract_subject_requirement(statement: str, keyword: str) -> tuple[str, str]:
    match = re.search(r"\b" + re.escape(keyword) + r"\b", statement, re.IGNORECASE)
    if not match:
        return "", statement
    subject = statement[: match.start()].strip().rstrip(",").strip()
    requirement = statement[match.end() :].strip().lstrip(",").strip()
    if len(subject) < 2:
        subject = "(implicit)"
    return subject, requirement


def extract_pass1(pdf_path: Path) -> ExtractionResult:
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    statements: list[ShallStatement] = []
    stmt_id = 0

    logger.info("Pass 1: extracting from %s (%d pages)", pdf_path.name, total_pages)

    for page_idx in range(len(doc)):
        text = doc[page_idx].get_text()
        if not text or len(text.strip()) < 20:
            continue

        for match in OBLIGATION_PATTERN.finditer(text):
            sentence = match.group(1).strip()
            keyword = match.group(2).lower()
            if len(sentence) < 15:
                continue
            if any(noise in sentence.lower() for noise in NOISE_TERMS):
                continue

            obligation_type = OBLIGATION_KEYWORDS.get(keyword, "mandatory")
            section = _detect_current_section(text, match.start())
            subject, requirement = _extract_subject_requirement(sentence, keyword)
            ctx_start = max(0, match.start() - 80)
            ctx_end = min(len(text), match.end() + 80)
            context = text[ctx_start:ctx_end].strip()

            stmt_id += 1
            statements.append(
                ShallStatement(
                    id=stmt_id,
                    page=page_idx + 1,
                    section=section,
                    obligation_keyword=keyword,
                    obligation_type=obligation_type,
                    statement_text=sentence,
                    subject=subject,
                    requirement=requirement,
                    context=context,
                )
            )

    doc.close()

    by_type: dict[str, int] = {}
    for s in statements:
        by_type[s.obligation_type] = by_type.get(s.obligation_type, 0) + 1

    result = ExtractionResult(
        source_file=pdf_path.name,
        total_pages=total_pages,
        extraction_date=datetime.now().isoformat(),
        total_statements=len(statements),
        by_type=by_type,
        statements=statements,
    )

    logger.info("Pass 1 complete: %d statements", result.total_statements)
    return result


# ============================================================================
# Pass 2 classification
# ============================================================================

CLASSIFY_PROMPT_SYSTEM = (
    'You classify "shall" statements into categories. '
    "Return strict JSON only."
)
CLASSIFY_PROMPT_USER = """Classify these statements.
Return JSON object with key "results", array of objects:
{{"id":<int>,"cat":"<design|testing|inspection|documentation|handling|cleaning|materials|safety|process|approval|prohibition|general>","subj":"<who>","req":"<what they must do>","conf":<0.0-1.0>}}

{statements_json}
"""


def _call_ollama(
    prompt: str,
    model: str,
    *,
    system: str = "",
    timeout: int = 300,
    num_predict: int = 512,
    retries: int = 1,
) -> str:
    import urllib.error
    import urllib.request

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps(
        {
            "model": model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
                "num_predict": num_predict,
            },
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        "http://localhost:11434/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                content = data.get("message", {}).get("content", "")
                if not str(content).strip():
                    raise ValueError("Empty content from Ollama")
                return str(content)
        except (TimeoutError, socket.timeout) as e:
            if attempt < retries:
                logger.warning(
                    "Ollama timeout (attempt %d/%d), retrying...",
                    attempt + 1,
                    retries + 1,
                )
                time.sleep(1.5 * (attempt + 1))
                continue
            raise TimeoutError(
                f"Ollama timed out after {timeout}s (model={model})"
            ) from e
        except urllib.error.URLError as e:
            msg = str(e).lower()
            if "timed out" in msg:
                if attempt < retries:
                    logger.warning(
                        "Ollama timeout/URLError (attempt %d/%d), retrying...",
                        attempt + 1,
                        retries + 1,
                    )
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise TimeoutError(
                    f"Ollama timed out after {timeout}s (model={model})"
                ) from e
            raise ConnectionError(
                "Ollama not reachable at localhost:11434. Start with: ollama serve"
            ) from e


def _parse_llm_classifications(response_text: str) -> list[dict]:
    text = (response_text or "").strip()
    if not text:
        return []

    if "```" in text:
        first = text.find("```")
        first_nl = text.find("\n", first)
        last = text.rfind("```")
        if first_nl != -1 and last > first_nl:
            text = text[first_nl + 1 : last].strip()

    parsed: object
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
        for opener, closer in [("{", "}"), ("[", "]")]:
            start = text.find(opener)
            end = text.rfind(closer)
            if start != -1 and end > start:
                try:
                    parsed = json.loads(text[start : end + 1])
                    break
                except json.JSONDecodeError:
                    continue
        if parsed is None:
            logger.warning("Could not parse LLM JSON payload (prefix=%r)", text[:120])
            return []

    if isinstance(parsed, dict):
        for key in ("results", "items", "classifications", "data"):
            if isinstance(parsed.get(key), list):
                parsed = parsed[key]
                break
        else:
            parsed = [parsed]

    if not isinstance(parsed, list):
        return []

    out: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "id": item.get("id"),
                "category": item.get("cat") or item.get("category", ""),
                "subject_refined": item.get("subj")
                or item.get("subject_refined", ""),
                "requirement_refined": item.get("req")
                or item.get("requirement_refined", ""),
                "confidence": item.get("conf")
                if item.get("conf") is not None
                else item.get("confidence", 1.0),
            }
        )
    return out


def extract_pass2(
    result: ExtractionResult,
    *,
    model: str = "llama3.1:8b-instruct-q4_K_M",
    batch_size: int = 5,
    timeout: int = 300,
    num_predict: int = 512,
    retries: int = 1,
    max_consecutive_failures: int = 3,
    max_statements: int = 0,
) -> ExtractionResult:
    statements = result.statements
    if max_statements and max_statements > 0:
        statements = statements[:max_statements]

    total = len(statements)
    if total == 0:
        logger.info("Pass 2 skipped: no statements")
        return result

    total_batches = (total + batch_size - 1) // batch_size
    logger.info(
        "Pass 2: classifying %d statements with %s (%d batches x %d)",
        total,
        model,
        total_batches,
        batch_size,
    )

    classified_count = 0
    failed_count = 0
    consecutive_failures = 0
    started = time.time()

    for batch_start in range(0, total, batch_size):
        batch = statements[batch_start : batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        batch_started = time.time()

        batch_json = json.dumps(
            [
                {"id": s.id, "statement": s.statement_text[:200], "section": s.section}
                for s in batch
            ],
            ensure_ascii=False,
        )
        prompt = CLASSIFY_PROMPT_USER.format(statements_json=batch_json)

        try:
            response = _call_ollama(
                prompt,
                model,
                system=CLASSIFY_PROMPT_SYSTEM,
                timeout=timeout,
                num_predict=num_predict,
                retries=retries,
            )
            classes = _parse_llm_classifications(response)
            by_id = {c.get("id"): c for c in classes if c.get("id") is not None}

            for stmt in batch:
                c = by_id.get(stmt.id)
                if c:
                    stmt.category = str(c.get("category", "") or "")
                    stmt.confidence = float(c.get("confidence", 1.0) or 1.0)
                    if c.get("subject_refined"):
                        stmt.subject = str(c["subject_refined"])
                    if c.get("requirement_refined"):
                        stmt.requirement = str(c["requirement_refined"])
                    classified_count += 1
                else:
                    failed_count += 1

            consecutive_failures = 0
            elapsed = time.time() - batch_started
            avg = (time.time() - started) / batch_num
            rem = max(0, total_batches - batch_num)
            eta_min = int((avg * rem) / 60)
            logger.info(
                "  Batch %d/%d: %d/%d OK (%d/%d total, %d%%, %.1fs, ETA ~%dm)",
                batch_num,
                total_batches,
                len(classes),
                len(batch),
                classified_count,
                total,
                int((classified_count * 100) / total),
                elapsed,
                eta_min,
            )

        except ConnectionError:
            logger.error("Ollama not available - aborting pass 2")
            break
        except TimeoutError as e:
            failed_count += len(batch)
            consecutive_failures += 1
            logger.error(
                "  Batch %d/%d timeout: %s (%d/%d total)",
                batch_num,
                total_batches,
                e,
                classified_count,
                total,
            )
            if consecutive_failures >= max_consecutive_failures:
                logger.error(
                    "Stopping pass 2 after %d consecutive failures.",
                    consecutive_failures,
                )
                break
        except Exception as e:
            failed_count += len(batch)
            consecutive_failures += 1
            logger.error(
                "  Batch %d/%d failed: %s (%d/%d total)",
                batch_num,
                total_batches,
                e,
                classified_count,
                total,
            )
            if consecutive_failures >= max_consecutive_failures:
                logger.error(
                    "Stopping pass 2 after %d consecutive failures.",
                    consecutive_failures,
                )
                break

    logger.info(
        "Pass 2 complete: %d/%d classified, %d failed",
        classified_count,
        total,
        failed_count,
    )
    return result


# ============================================================================
# Output
# ============================================================================


def save_results(result: ExtractionResult, output_dir: Path) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(result.source_file).stem

    json_path = output_dir / f"{stem}_shall_statements.json"
    summary_path = output_dir / f"{stem}_shall_summary.txt"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(asdict(result), f, indent=2, ensure_ascii=False)

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("SHALL STATEMENT EXTRACTION REPORT\n")
        f.write("=" * 60 + "\n")
        f.write(f"Source: {result.source_file}\n")
        f.write(f"Pages: {result.total_pages}\n")
        f.write(f"Date: {result.extraction_date}\n")
        f.write(f"Total Statements: {result.total_statements}\n\n")

        f.write("BREAKDOWN BY TYPE:\n")
        for typ, count in sorted(result.by_type.items(), key=lambda x: -x[1]):
            f.write(f"  {typ:20s}: {count}\n")
        f.write("\n" + "=" * 60 + "\n\n")

        by_section: dict[str, list[ShallStatement]] = {}
        for s in result.statements:
            by_section.setdefault(s.section or "(no section)", []).append(s)

        for section, stmts in sorted(by_section.items(), key=lambda kv: kv[0]):
            f.write(f"SECTION {section}\n")
            f.write("-" * 40 + "\n")
            for s in stmts:
                cat = f" [{s.category}]" if s.category else ""
                f.write(f"  [{s.obligation_type.upper()}]{cat} p.{s.page}\n")
                f.write(f"    {s.statement_text[:200]}\n")
                if s.subject and s.subject != "(implicit)":
                    f.write(f"    Subject: {s.subject}\n")
                f.write(f"    Requirement: {s.requirement[:150]}\n\n")

    logger.info("Saved: %s", json_path)
    logger.info("Saved: %s", summary_path)
    return {"json": json_path, "summary": summary_path}


# ============================================================================
# CLI
# ============================================================================


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Extract shall/must/required statements from a PDF"
    )
    parser.add_argument("pdf", type=str, help="Path to PDF file")
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Output directory (default: same as PDF)",
    )
    parser.add_argument(
        "--classify",
        action="store_true",
        help="Run pass 2 with local Ollama model",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="llama3.1:8b-instruct-q4_K_M",
        help="Ollama model name",
    )
    parser.add_argument(
        "--mandatory-only",
        action="store_true",
        help="Only keep mandatory/prohibition statements",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5,
        help="Statements per LLM batch (default: 5)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout per LLM call in seconds (default: 300)",
    )
    parser.add_argument(
        "--num-predict",
        type=int,
        default=512,
        help="Max generated tokens per LLM call (default: 512)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="Retries per failed LLM call (default: 1)",
    )
    parser.add_argument(
        "--max-consecutive-failures",
        type=int,
        default=3,
        help="Abort pass 2 after this many consecutive failures (default: 3)",
    )
    parser.add_argument(
        "--max-statements",
        type=int,
        default=0,
        help="Cap number of statements sent to pass 2 (0 = no cap)",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    output_dir = Path(args.output) if args.output else pdf_path.parent

    result = extract_pass1(pdf_path)

    if args.mandatory_only:
        before = len(result.statements)
        result.statements = [
            s
            for s in result.statements
            if s.obligation_type in ("mandatory", "prohibition")
        ]
        result.total_statements = len(result.statements)
        result.by_type = {}
        for s in result.statements:
            result.by_type[s.obligation_type] = result.by_type.get(s.obligation_type, 0) + 1
        logger.info("Filtered to mandatory/prohibition: %d -> %d", before, result.total_statements)

    # Always checkpoint pass 1 immediately so caller gets JSON even if pass 2 is slow.
    checkpoint = save_results(result, output_dir)
    logger.info("Pass 1 checkpoint written: %s", checkpoint["json"])

    if args.classify:
        result = extract_pass2(
            result,
            model=args.model,
            batch_size=args.batch_size,
            timeout=args.timeout,
            num_predict=args.num_predict,
            retries=args.retries,
            max_consecutive_failures=args.max_consecutive_failures,
            max_statements=args.max_statements,
        )

    paths = save_results(result, output_dir)

    print("\n" + "=" * 60)
    print("EXTRACTION COMPLETE")
    print("=" * 60)
    print(f"Source:     {result.source_file}")
    print(f"Pages:      {result.total_pages}")
    print(f"Statements: {result.total_statements}")
    print()
    for typ, count in sorted(result.by_type.items(), key=lambda x: -x[1]):
        print(f"  {typ:20s}: {count}")
    print()
    print(f"JSON:    {paths['json']}")
    print(f"Summary: {paths['summary']}")


if __name__ == "__main__":
    main()
