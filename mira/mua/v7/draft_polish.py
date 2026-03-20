"""MUA v7 Draft Polish -- LLM enhancement layer using real MUA examples.

Layer 2 of the two-layer draft architecture.  The template layer
(``draft_renderer.py``) produces a correct, deterministic baseline.
This module *optionally* enhances the Rationale section using Claude,
guided by similar real MUA documents from the ``mua_precedents_v7``
corpus.

Design contract
---------------
- Template output is ALWAYS valid -- this layer is never a dependency.
- If the LLM call fails for any reason, the template ships unchanged.
- All factual claims (MUA numbers, test ratings, citations) are
  preserved verbatim.  The LLM rewrites *language*, not *facts*.
- The LLM is guided by 3-5 real MUA rationale texts matched by
  material family and environment type.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from mira.mua.v7.models import DraftSection, MUADraft

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
_MAX_TOKENS = 4096
_TEMPERATURE = 0.3  # slight creativity for natural language, but controlled

_POLISH_SYSTEM_PROMPT = """\
You are rewriting the Rationale section of a NASA Material Usage Agreement \
(MUA) per NASA-STD-6016C.

RULES — follow these exactly:
1. Preserve ALL factual claims, MUA numbers, test numbers, ratings, \
percentages, and citations EXACTLY as they appear in the input.
2. Use numbered rationale points (1, 2, 3…).  Each point should make one \
specific engineering claim backed by evidence.
3. End with a summary paragraph that synthesizes the overall risk assessment.
4. Professional NASA M&P engineering tone — concise, citation-heavy, \
risk-framing language.
5. Never claim "approved" or "approved for use" — use "may be acceptable" \
or similar hedged language.
6. Never claim authority to approve — this is an engineering assessment \
only.
7. Keep the total rationale between 150 and 500 words.
8. Reference specific standards, test numbers, and report numbers where \
available.
9. If there are gaps accepted by engineering judgment, quote the engineer's \
rationale verbatim (in quotation marks).
10. Do NOT add facts, MUA numbers, test results, or claims that are not \
in the template input.  Rewrite language only.

Output ONLY the rewritten rationale section text.  No preamble, no \
markdown headers, no explanation.
"""


# ---------------------------------------------------------------------------
# Example fetcher (queries PostgreSQL mua_precedents_v7)
# ---------------------------------------------------------------------------


def _fetch_example_rationale(
    material_family: Optional[str],
    env_type: Optional[str],
    limit: int = 3,
) -> list[dict]:
    """Fetch similar MUA rationale texts from the precedent corpus.

    Falls back gracefully to broader queries if exact match yields
    insufficient results.

    Returns a list of dicts with keys: mua_number, rationale, application.
    """
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        from mira.core.db_config import get_db_connection_params
    except ImportError:
        logger.warning("psycopg2 not available -- skipping example fetch.")
        return []

    try:
        db_config = get_db_connection_params()
        conn = psycopg2.connect(**db_config)
    except Exception:
        logger.warning("Could not connect to PostgreSQL -- skipping example fetch.", exc_info=True)
        return []

    results: list[dict] = []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Tier 1: exact family + env match, approved, with rationale
            if material_family and env_type:
                cur.execute(
                    """
                    SELECT mua_number, rationale, application
                    FROM mua_precedents_v7
                    WHERE material_family = %s
                      AND env_type = %s
                      AND determination = 'APPROVED'
                      AND rationale IS NOT NULL
                      AND LENGTH(rationale) > 50
                    ORDER BY confidence DESC
                    LIMIT %s
                    """,
                    (material_family.upper(), env_type.upper(), limit),
                )
                results = [dict(r) for r in cur.fetchall()]

            # Tier 2: family only (broaden env)
            if len(results) < limit and material_family:
                cur.execute(
                    """
                    SELECT mua_number, rationale, application
                    FROM mua_precedents_v7
                    WHERE material_family = %s
                      AND determination = 'APPROVED'
                      AND rationale IS NOT NULL
                      AND LENGTH(rationale) > 50
                    ORDER BY confidence DESC
                    LIMIT %s
                    """,
                    (material_family.upper(), limit - len(results)),
                )
                seen = {r["mua_number"] for r in results}
                for row in cur.fetchall():
                    if row["mua_number"] not in seen:
                        results.append(dict(row))
                        seen.add(row["mua_number"])

            # Tier 3: any approved with long rationale
            if len(results) < 2:
                cur.execute(
                    """
                    SELECT mua_number, rationale, application
                    FROM mua_precedents_v7
                    WHERE determination = 'APPROVED'
                      AND rationale IS NOT NULL
                      AND LENGTH(rationale) > 100
                    ORDER BY confidence DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                seen = {r["mua_number"] for r in results}
                for row in cur.fetchall():
                    if row["mua_number"] not in seen:
                        results.append(dict(row))
                        seen.add(row["mua_number"])
                        if len(results) >= limit:
                            break

    except Exception:
        logger.warning("Failed to query mua_precedents_v7 for examples.", exc_info=True)
    finally:
        conn.close()

    return results[:limit]


# ---------------------------------------------------------------------------
# LLM polish
# ---------------------------------------------------------------------------


def polish_rationale(
    draft: MUADraft,
    material_family: Optional[str] = None,
    env_type: Optional[str] = None,
    *,
    model: str = _DEFAULT_MODEL,
) -> MUADraft:
    """Polish the Rationale section (Section 4) of a rendered draft.

    Fetches similar real MUA rationale texts from PostgreSQL and uses
    Claude to rewrite the template output in professional NASA tone.

    If the LLM call fails for ANY reason, the original draft is returned
    unchanged — the template is always the safety net.

    Parameters
    ----------
    draft:
        The template-rendered MUA draft.
    material_family:
        Canonical material family for example lookup (e.g. "ALUMINUM").
    env_type:
        Canonical environment type for example lookup (e.g. "CABIN_AIR").
    model:
        Claude model ID to use.

    Returns
    -------
    MUADraft
        The draft with polished Rationale section (or unchanged on failure).
    """
    # Find the rationale section (section_number == 4)
    rationale_section: Optional[DraftSection] = None
    rationale_idx: Optional[int] = None
    for idx, section in enumerate(draft.sections):
        if section.section_number == 4:
            rationale_section = section
            rationale_idx = idx
            break

    if rationale_section is None:
        logger.debug("No Section 4 found in draft -- skipping polish.")
        return draft

    # Fetch similar real MUA rationale texts
    examples = _fetch_example_rationale(material_family, env_type, limit=3)

    if not examples:
        logger.info(
            "No example MUA rationale found (family=%s, env=%s) -- "
            "shipping template as-is.",
            material_family,
            env_type,
        )
        return draft

    # Build the user prompt
    example_block = "\n\n".join(
        f"--- Real MUA {ex['mua_number']} ---\n"
        f"APPLICATION: {ex.get('application', 'N/A')}\n"
        f"RATIONALE: {ex['rationale']}"
        for ex in examples
    )

    user_prompt = (
        f"STYLE EXAMPLES FROM REAL NASA MUAs:\n\n"
        f"{example_block}\n\n"
        f"---\n\n"
        f"TEMPLATE RATIONALE TO REWRITE:\n\n"
        f"{rationale_section.content}\n\n"
        f"Rewrite the rationale above as professional numbered points. "
        f"Preserve all facts. Improve the language only."
    )

    # Call Claude
    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not set -- skipping LLM polish.")
            return draft

        from anthropic import Anthropic

        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            temperature=_TEMPERATURE,
            system=_POLISH_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        polished_text = response.content[0].text.strip()

        if not polished_text or len(polished_text) < 50:
            logger.warning(
                "LLM polish returned too-short response (%d chars) -- "
                "keeping template.",
                len(polished_text),
            )
            return draft

        logger.info(
            "LLM polish applied to Section 4. Template: %d chars -> Polished: %d chars.",
            len(rationale_section.content),
            len(polished_text),
        )

        # Build new sections list with polished rationale
        new_sections = list(draft.sections)
        new_sections[rationale_idx] = DraftSection(
            section_number=4,
            title=rationale_section.title,
            content=polished_text,
            editable=True,
        )

        # Reassemble full_text
        parts: list[str] = []
        divider = "=" * 64
        for section in new_sections:
            parts.append(divider)
            parts.append(
                f"SECTION {section.section_number}: {section.title.upper()}"
            )
            parts.append(divider)
            parts.append(section.content)
            parts.append("")

        return MUADraft(
            mua_id=draft.mua_id,
            sections=new_sections,
            category=draft.category,
            evidence_strength=draft.evidence_strength,
            fact_check_results=draft.fact_check_results,
            cited_precedents=draft.cited_precedents,
            full_text="\n".join(parts),
        )

    except Exception:
        logger.warning(
            "LLM polish failed -- shipping template as-is.", exc_info=True
        )
        return draft
