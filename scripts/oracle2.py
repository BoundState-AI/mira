#!/usr/bin/env python3
"""
Module: Oracle2
Purpose: Multi-oracle review system for specs, plans, and architecture docs.

Flow:
  Round 0: Beth (Opus 4.6) writes or accepts the canonical draft
  Round 1: Fran (GPT-5.4), Codex (GPT-5.4), Grok (xAI) review independently (blind)
  Round 1.5: Sonnet (Claude Sonnet 4.6) normalizes/deduplicates findings
  Round 2: Beth classifies findings, revises draft
  Round 3+: Re-review changed sections until convergence

Convergence:
  - No new critical findings
  - New high findings <= 1
  - Delta in accepted defects < 10%
  - Same unresolved tradeoff repeats twice

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

LOGGER = logging.getLogger("oracle2")

# ---------------------------------------------------------------------------
# Shared review contract — every oracle gets this preamble
# ---------------------------------------------------------------------------

SHARED_CONTRACT = """\
You are part of a multi-oracle review system.

Task:
Review the supplied draft and return only atomic, actionable review findings.

Hard rules:
1. Do not rewrite the full document.
2. Do not praise, summarize, or soften.
3. Only report defects, risks, ambiguities, contradictions, omissions, or concrete improvements.
4. Every finding must be atomic: one issue, one claim.
5. Prefer high-severity findings over style comments.
6. Cite the exact section, heading, paragraph, line span, or quoted snippet that triggered the finding.
7. If a concern is speculative, label it as speculative.
8. If you have fewer than 3 real findings, return fewer than 3. Do not invent filler.
9. Do not repeat obvious points already stated in the draft unless they are still defective.
10. Output valid JSON only.

Severity scale:
- critical: likely to cause failure, unsafe behavior, invalid architecture, legal/compliance break, or impossible implementation
- high: major design flaw, major ambiguity, missing requirement, likely downstream rework
- medium: meaningful weakness, edge-case gap, weak testability, unclear ownership
- low: non-blocking improvement

Confidence scale:
0.0 to 1.0

Return schema:
{
  "oracle_name": "...",
  "role": "...",
  "document_type": "...",
  "overall_verdict": "approve_with_minor_changes | revise | major_revision",
  "findings": [
    {
      "title": "...",
      "severity": "critical|high|medium|low",
      "category": "ambiguity|contradiction|omission|feasibility|testability|security|performance|governance|scope|data_model|api_contract|operational_risk|other",
      "location": "Section ...",
      "evidence": "...",
      "problem": "...",
      "why_it_matters": "...",
      "proposed_fix": "...",
      "confidence": 0.0
    }
  ],
  "top_3_must_fix": ["...", "...", "..."]
}\
"""

# ---------------------------------------------------------------------------
# Individual oracle system prompts
# ---------------------------------------------------------------------------

BETH_COORDINATOR_PROMPT = """\
You are Beth, the coordinator oracle in a multi-oracle review system.

Your job:
1. Write the initial draft when asked.
2. Maintain the canonical version.
3. After reviewers respond, classify each finding into:
   - accepted_defect
   - rejected_claim
   - preference_only
   - unresolved_question
4. Revise the draft only for accepted_defect items and explicitly chosen unresolved questions.
5. Preserve architecture integrity. Do not average conflicting advice.
6. Prefer coherence and correctness over compromise.

When synthesizing reviews:
- Deduplicate similar findings.
- Reject comments that lack evidence or are merely stylistic.
- Do not accept conflicting changes without resolving the underlying principle.
- If two reviewers disagree, identify the governing tradeoff and decide.

Output JSON only:
{
  "oracle_name": "Beth",
  "role": "coordinator",
  "revision_decisions": [
    {
      "finding_title": "...",
      "decision": "accepted_defect|rejected_claim|preference_only|unresolved_question",
      "reason": "..."
    }
  ],
  "architectural_risks_remaining": ["..."],
  "revised_sections": ["..."],
  "open_questions": ["..."]
}\
"""

FRAN_ADVERSARIAL_PROMPT = """\
You are Fran, the adversarial logic reviewer.

Primary job:
Find hidden assumptions, false precision, vague abstractions, contradictions, hand-wavy logic, unstated dependencies, and places where the document sounds stronger than it is.

Bias:
- Be skeptical of elegant language.
- Attack the plan where reality will attack it.
- Prefer structural defects over implementation trivia.
- Ask: what has to be true for this to work, and did the author actually state it?

Extra focus:
- ambiguous terms
- unclear ownership
- invalid reasoning jumps
- missing decision criteria
- undefined inputs/outputs
- failure modes not accounted for
- "this will work" claims with no mechanism

Do not focus on prose polish unless wording creates real ambiguity.
Return JSON only.\
"""

CODEX_FEASIBILITY_PROMPT = """\
You are Codex, the implementation-feasibility reviewer.

Primary job:
Determine whether this document can actually be built, tested, deployed, and maintained.

Focus:
- missing interfaces
- untestable requirements
- vague API contracts
- hidden state assumptions
- migration traps
- caching/session issues
- concurrency/failure handling gaps
- missing schemas/types
- bad separation of concerns
- repo-shape realism
- observability and rollback omissions

Questions to ask internally:
- What code modules would exist?
- What contracts are implied but unspecified?
- What breaks first during implementation?
- What cannot be verified?
- What would create integration churn?

Do not suggest broad rewrites unless the architecture is genuinely broken.
Return JSON only.\
"""

GROK_CONTRARIAN_PROMPT = """\
You are Grok, the contrarian reviewer.

Primary job:
Challenge the framing, surface edge cases, and identify where the document may be overengineered, under-scoped, or blind to alternatives.

Focus:
- edge cases
- alternative interpretations
- adversarial scenarios
- misuse/abuse conditions
- "what if the opposite assumption is true?"
- complexity inflation
- scope drift
- brittle dependencies on external actors or perfect data

Do not behave like an editor.
Do not restate obvious points.
Find what the others may miss because they accepted the frame too early.
Return JSON only.\
"""

SONNET_REFEREE_PROMPT = """\
You are Sonnet, the referee oracle.

You do not review the document directly unless explicitly asked.
Your primary job is to normalize and score findings from other oracles.

Input:
- canonical draft
- reviewer JSON outputs

Tasks:
1. Deduplicate overlapping findings.
2. Merge semantically equivalent findings into one atomic issue.
3. Assign final severity based on impact, not wording.
4. Flag unsupported or weak findings.
5. Detect direct conflicts between reviewers.
6. Produce a normalized issue ledger for the coordinator.

Rules:
- Do not invent new issues unless a cross-review contradiction reveals one.
- Keep each merged issue atomic.
- Preserve reviewer attribution.
- Be conservative with severity inflation.

Output JSON:
{
  "oracle_name": "Sonnet",
  "role": "referee",
  "normalized_issues": [
    {
      "issue_id": "ISSUE-001",
      "title": "...",
      "severity": "critical|high|medium|low",
      "category": "...",
      "merged_from": [
        {"oracle": "Fran", "title": "..."},
        {"oracle": "Codex", "title": "..."}
      ],
      "core_problem": "...",
      "best_evidence": "...",
      "recommended_fix": "...",
      "conflict_flag": false,
      "weak_signal": false
    }
  ],
  "dropped_findings": [
    {
      "oracle": "...",
      "title": "...",
      "reason": "duplicate|unsupported|style_only|too_vague"
    }
  ]
}\
"""


# ---------------------------------------------------------------------------
# LLM client abstraction
# ---------------------------------------------------------------------------

@dataclass
class OracleConfig:
    """Configuration for one oracle."""
    name: str
    role: str
    provider: str       # "anthropic" | "openai" | "xai"
    model: str
    system_prompt: str
    temperature: float = 0.0
    max_tokens: int = 8192


# Default oracle roster
ORACLE_ROSTER: dict[str, OracleConfig] = {
    "beth": OracleConfig(
        name="Beth",
        role="coordinator",
        provider="anthropic",
        model=os.environ.get("ORACLE_BETH_MODEL", "claude-opus-4-6"),
        system_prompt=BETH_COORDINATOR_PROMPT,
        temperature=0.0,
        max_tokens=16384,
    ),
    "fran": OracleConfig(
        name="Fran",
        role="adversarial_logic",
        provider="openai",
        model=os.environ.get("ORACLE_FRAN_MODEL", "gpt-5.4"),
        system_prompt=FRAN_ADVERSARIAL_PROMPT,
    ),
    "codex": OracleConfig(
        name="Codex",
        role="implementation_feasibility",
        provider="openai",
        model=os.environ.get("ORACLE_CODEX_MODEL", "gpt-5.4"),
        system_prompt=CODEX_FEASIBILITY_PROMPT,
    ),
    "grok": OracleConfig(
        name="Grok",
        role="contrarian",
        provider="xai",
        model=os.environ.get("ORACLE_GROK_MODEL", "grok-4"),
        system_prompt=GROK_CONTRARIAN_PROMPT,
    ),
    "sonnet": OracleConfig(
        name="Sonnet",
        role="referee",
        provider="anthropic",
        model=os.environ.get("ORACLE_SONNET_MODEL", "claude-sonnet-4-6"),
        system_prompt=SONNET_REFEREE_PROMPT,
    ),
}


def _call_anthropic(config: OracleConfig, user_message: str) -> dict:
    """Call Anthropic Messages API (Beth / Sonnet)."""
    from anthropic import Anthropic

    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=config.model,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        system=config.system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    text = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text = block.text
            break
    return _parse_json(text, config.name)


def _call_openai(config: OracleConfig, user_message: str) -> dict:
    """Call OpenAI Chat Completions API (Fran / Codex)."""
    from openai import OpenAI

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        messages=[
            {"role": "system", "content": config.system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    text = response.choices[0].message.content or ""
    return _parse_json(text, config.name)


def _call_xai(config: OracleConfig, user_message: str) -> dict:
    """Call xAI/Grok API (OpenAI-compatible endpoint)."""
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ.get("XAI_API_KEY"),
        base_url="https://api.x.ai/v1",
    )
    response = client.chat.completions.create(
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        messages=[
            {"role": "system", "content": config.system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    text = response.choices[0].message.content or ""
    return _parse_json(text, config.name)


PROVIDER_DISPATCH = {
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "xai": _call_xai,
}


def call_oracle(config: OracleConfig, user_message: str) -> dict:
    """Route to the correct provider and return parsed JSON."""
    dispatch = PROVIDER_DISPATCH.get(config.provider)
    if not dispatch:
        raise ValueError(f"Unknown provider: {config.provider}")
    LOGGER.info(f"[{config.name}] Calling {config.provider}/{config.model}...")
    t0 = time.time()
    result = dispatch(config, user_message)
    elapsed = time.time() - t0
    LOGGER.info(
        f"[{config.name}] Done in {elapsed:.1f}s — "
        f"{len(result.get('findings', result.get('normalized_issues', [])))} findings"
    )
    return result


def _parse_json(text: str, oracle_name: str) -> dict:
    """Extract JSON from LLM response, tolerating markdown fences."""
    import re

    text = text.strip()
    # Strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError as e:
            LOGGER.error(f"[{oracle_name}] JSON parse error: {e}")
            LOGGER.debug(f"[{oracle_name}] Raw text: {text[:500]}")
    return {"oracle_name": oracle_name, "error": "Failed to parse JSON", "raw": text[:2000]}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

@dataclass
class ReviewRound:
    """State for one review round."""
    round_number: int
    reviewer_outputs: dict[str, dict] = field(default_factory=dict)
    normalized_issues: dict = field(default_factory=dict)
    coordinator_decisions: dict = field(default_factory=dict)
    revised_draft: str = ""


@dataclass
class OracleSession:
    """Full oracle review session."""
    session_id: str
    document_path: str
    original_draft: str
    canonical_draft: str
    rounds: list[ReviewRound] = field(default_factory=list)
    converged: bool = False
    convergence_reason: str = ""


def _build_review_message(draft: str, round_number: int, changed_sections: list[str] | None = None) -> str:
    """Build the user message for reviewers."""
    msg = f"{SHARED_CONTRACT}\n\n---\n\n## Document to Review (Round {round_number})\n\n{draft}"
    if changed_sections:
        msg += f"\n\n## Changed Sections Since Last Round\n\n" + "\n".join(f"- {s}" for s in changed_sections)
        msg += "\n\nFocus your review on the changed sections and any unresolved issues from prior rounds."
    return msg


def _build_referee_message(draft: str, reviews: dict[str, dict]) -> str:
    """Build the message for Sonnet referee."""
    msg = f"## Canonical Draft\n\n{draft}\n\n## Reviewer Outputs\n\n"
    for name, output in reviews.items():
        msg += f"### {name}\n```json\n{json.dumps(output, indent=2)}\n```\n\n"
    return msg


def _build_coordinator_message(
    draft: str,
    normalized: dict,
    round_number: int,
    prior_decisions: list[dict] | None = None,
) -> str:
    """Build the message for Beth coordinator."""
    msg = (
        f"## Current Canonical Draft\n\n{draft}\n\n"
        f"## Normalized Issue Ledger (Round {round_number})\n"
        f"```json\n{json.dumps(normalized, indent=2)}\n```\n\n"
        f"Classify each finding and revise the draft for accepted defects.\n"
        f"Return your revision decisions JSON AND the revised draft text.\n"
        f"Format: JSON block first, then `---REVISED DRAFT---` marker, then full revised draft."
    )
    if prior_decisions:
        msg += (
            f"\n\n## Prior Round Decisions\n"
            f"```json\n{json.dumps(prior_decisions, indent=2)}\n```\n"
            f"Do not re-accept findings already resolved. Focus on new/changed issues."
        )
    return msg


def _check_convergence(session: OracleSession) -> tuple[bool, str]:
    """Check if the review loop should stop."""
    if len(session.rounds) < 2:
        return False, ""

    current = session.rounds[-1]
    previous = session.rounds[-2]

    issues = current.normalized_issues.get("normalized_issues", [])
    prev_issues = previous.normalized_issues.get("normalized_issues", [])

    # No new critical findings
    critical = [i for i in issues if i.get("severity") == "critical"]
    if critical:
        return False, f"{len(critical)} critical findings remain"

    # New high findings <= 1
    high = [i for i in issues if i.get("severity") == "high"]
    if len(high) > 1:
        return False, f"{len(high)} high findings remain"

    # Delta in accepted defects < 10%
    current_accepted = sum(
        1 for d in current.coordinator_decisions.get("revision_decisions", [])
        if d.get("decision") == "accepted_defect"
    )
    prev_accepted = sum(
        1 for d in previous.coordinator_decisions.get("revision_decisions", [])
        if d.get("decision") == "accepted_defect"
    )
    if prev_accepted > 0 and current_accepted / max(prev_accepted, 1) > 0.1:
        return False, f"Accepted defect delta too high: {current_accepted} vs {prev_accepted}"

    # Same unresolved tradeoff repeats
    current_open = set(
        q for q in current.coordinator_decisions.get("open_questions", [])
    )
    prev_open = set(
        q for q in previous.coordinator_decisions.get("open_questions", [])
    )
    repeated = current_open & prev_open
    if len(repeated) >= 2:
        return True, f"Same unresolved tradeoffs repeated: {repeated}"

    return True, f"Converged: {len(high)} high, {current_accepted} accepted defects"


def run_review(
    draft: str,
    document_path: str = "",
    max_rounds: int = 3,
    output_dir: Path | None = None,
) -> OracleSession:
    """Run the full multi-oracle review loop."""
    session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    session = OracleSession(
        session_id=session_id,
        document_path=document_path,
        original_draft=draft,
        canonical_draft=draft,
    )

    if output_dir is None:
        output_dir = Path("oracle_reviews") / session_id
    output_dir.mkdir(parents=True, exist_ok=True)

    for round_num in range(1, max_rounds + 1):
        LOGGER.info(f"\n{'='*60}\nRound {round_num}\n{'='*60}")

        review_round = ReviewRound(round_number=round_num)
        changed_sections = None
        if round_num > 1 and session.rounds:
            changed_sections = session.rounds[-1].coordinator_decisions.get("revised_sections", [])

        # --- Round N: Blind review (Fran, Codex, Grok in parallel) ---
        review_msg = _build_review_message(session.canonical_draft, round_num, changed_sections)

        # Run reviewers sequentially (parallel via threads would be better but
        # keeps the script simple — swap in concurrent.futures if needed)
        for reviewer_key in ("fran", "codex", "grok"):
            config = ORACLE_ROSTER[reviewer_key]
            try:
                result = call_oracle(config, review_msg)
                review_round.reviewer_outputs[config.name] = result
            except Exception as e:
                LOGGER.error(f"[{config.name}] Failed: {e}")
                review_round.reviewer_outputs[config.name] = {
                    "oracle_name": config.name,
                    "error": str(e),
                    "findings": [],
                }

        # Save reviewer outputs
        for name, output in review_round.reviewer_outputs.items():
            path = output_dir / f"round{round_num}_{name.lower()}.json"
            path.write_text(json.dumps(output, indent=2))

        # --- Round N.5: Sonnet normalizes ---
        referee_msg = _build_referee_message(session.canonical_draft, review_round.reviewer_outputs)
        try:
            normalized = call_oracle(ORACLE_ROSTER["sonnet"], referee_msg)
        except Exception as e:
            LOGGER.error(f"[Sonnet] Failed: {e}")
            normalized = {"oracle_name": "Sonnet", "error": str(e), "normalized_issues": []}

        review_round.normalized_issues = normalized
        (output_dir / f"round{round_num}_sonnet_normalized.json").write_text(
            json.dumps(normalized, indent=2)
        )

        # --- Round N+1: Beth classifies and revises ---
        prior_decisions = session.rounds[-1].coordinator_decisions if session.rounds else None
        coord_msg = _build_coordinator_message(
            session.canonical_draft, normalized, round_num,
            prior_decisions=[prior_decisions] if prior_decisions else None,
        )
        try:
            beth_response = call_oracle(ORACLE_ROSTER["beth"], coord_msg)
        except Exception as e:
            LOGGER.error(f"[Beth] Failed: {e}")
            beth_response = {"oracle_name": "Beth", "error": str(e), "revision_decisions": []}

        review_round.coordinator_decisions = beth_response

        # Extract revised draft if Beth included one
        # Beth outputs JSON + "---REVISED DRAFT---" + text
        # The JSON is already parsed; check raw for revised draft
        if "raw" in beth_response:
            raw = beth_response["raw"]
            if "---REVISED DRAFT---" in raw:
                _, revised = raw.split("---REVISED DRAFT---", 1)
                session.canonical_draft = revised.strip()
                review_round.revised_draft = session.canonical_draft

        (output_dir / f"round{round_num}_beth_decisions.json").write_text(
            json.dumps(beth_response, indent=2)
        )
        if review_round.revised_draft:
            (output_dir / f"round{round_num}_revised_draft.md").write_text(
                review_round.revised_draft
            )

        session.rounds.append(review_round)

        # --- Convergence check ---
        converged, reason = _check_convergence(session)
        if converged:
            session.converged = True
            session.convergence_reason = reason
            LOGGER.info(f"\nConverged after round {round_num}: {reason}")
            break
        else:
            LOGGER.info(f"\nNot converged: {reason}")

    # --- Save final state ---
    (output_dir / "final_draft.md").write_text(session.canonical_draft)
    summary = {
        "session_id": session.session_id,
        "document_path": session.document_path,
        "total_rounds": len(session.rounds),
        "converged": session.converged,
        "convergence_reason": session.convergence_reason,
        "total_findings_by_round": [
            {
                "round": r.round_number,
                "reviewer_findings": {
                    name: len(out.get("findings", []))
                    for name, out in r.reviewer_outputs.items()
                },
                "normalized_issues": len(
                    r.normalized_issues.get("normalized_issues", [])
                ),
                "accepted_defects": sum(
                    1 for d in r.coordinator_decisions.get("revision_decisions", [])
                    if d.get("decision") == "accepted_defect"
                ),
            }
            for r in session.rounds
        ],
    }
    (output_dir / "session_summary.json").write_text(json.dumps(summary, indent=2))
    LOGGER.info(f"\nResults saved to {output_dir}/")

    return session


# ---------------------------------------------------------------------------
# Scoring / QC metrics
# ---------------------------------------------------------------------------

def compute_metrics(session: OracleSession) -> dict:
    """Compute the QC scoring rubric for a completed review."""
    all_decisions = []
    for r in session.rounds:
        all_decisions.extend(r.coordinator_decisions.get("revision_decisions", []))

    accepted = [d for d in all_decisions if d.get("decision") == "accepted_defect"]
    rejected = [d for d in all_decisions if d.get("decision") == "rejected_claim"]
    preference = [d for d in all_decisions if d.get("decision") == "preference_only"]

    all_issues = []
    for r in session.rounds:
        all_issues.extend(r.normalized_issues.get("normalized_issues", []))

    dropped = []
    for r in session.rounds:
        dropped.extend(r.normalized_issues.get("dropped_findings", []))

    critical_accepted = sum(
        1 for i in all_issues
        if i.get("severity") == "critical"
        and any(
            d.get("finding_title", "").lower() in i.get("title", "").lower()
            for d in accepted
        )
    )
    high_accepted = sum(
        1 for i in all_issues
        if i.get("severity") == "high"
        and any(
            d.get("finding_title", "").lower() in i.get("title", "").lower()
            for d in accepted
        )
    )

    total_findings = sum(
        len(out.get("findings", []))
        for r in session.rounds
        for out in r.reviewer_outputs.values()
    )
    duplicate_count = sum(1 for d in dropped if d.get("reason") == "duplicate")
    unsupported_count = sum(1 for d in dropped if d.get("reason") == "unsupported")

    return {
        "accepted_critical_count": critical_accepted,
        "accepted_high_count": high_accepted,
        "total_accepted_defects": len(accepted),
        "total_rejected_claims": len(rejected),
        "total_preference_only": len(preference),
        "novel_issue_count": len(all_issues),
        "duplicate_rate": duplicate_count / max(total_findings, 1),
        "unsupported_claim_rate": unsupported_count / max(total_findings, 1),
        "rounds_to_stability": len(session.rounds),
        "converged": session.converged,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Oracle2: Multi-oracle review system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Environment variables:
  ANTHROPIC_API_KEY   — Required for Beth (Opus) and Sonnet
  OPENAI_API_KEY      — Required for Fran and Codex (GPT-5.4)
  XAI_API_KEY         — Required for Grok

  ORACLE_BETH_MODEL   — Override Beth model  (default: claude-opus-4-6)
  ORACLE_FRAN_MODEL   — Override Fran model  (default: gpt-5.4)
  ORACLE_CODEX_MODEL  — Override Codex model (default: gpt-5.4)
  ORACLE_GROK_MODEL   — Override Grok model  (default: grok-4)
  ORACLE_SONNET_MODEL — Override Sonnet model (default: claude-sonnet-4-6)

Examples:
  python oracle2.py docs/PHASE3_SCALING_PLAN.md
  python oracle2.py docs/PHASE3_SCALING_PLAN.md --max-rounds 5
  python oracle2.py docs/PHASE3_SCALING_PLAN.md --output-dir reviews/scaling-v2
""",
    )
    parser.add_argument("document", help="Path to the document to review")
    parser.add_argument("--max-rounds", type=int, default=3, help="Maximum review rounds (default: 3)")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory (default: oracle_reviews/<timestamp>)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    doc_path = Path(args.document)
    if not doc_path.exists():
        LOGGER.error(f"Document not found: {doc_path}")
        sys.exit(1)

    draft = doc_path.read_text(encoding="utf-8")
    LOGGER.info(f"Loaded {doc_path} ({len(draft)} chars)")

    # Validate API keys
    missing = []
    if not os.environ.get("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")
    if not os.environ.get("OPENAI_API_KEY"):
        missing.append("OPENAI_API_KEY")
    if not os.environ.get("XAI_API_KEY"):
        missing.append("XAI_API_KEY")
    if missing:
        LOGGER.error(f"Missing API keys: {', '.join(missing)}")
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else None
    session = run_review(
        draft=draft,
        document_path=str(doc_path),
        max_rounds=args.max_rounds,
        output_dir=output_dir,
    )

    metrics = compute_metrics(session)
    LOGGER.info(f"\n{'='*60}\nMetrics\n{'='*60}")
    for k, v in metrics.items():
        LOGGER.info(f"  {k}: {v}")

    if output_dir is None:
        output_dir = Path("oracle_reviews") / session.session_id
    (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))

    print(f"\nDone. Results in {output_dir}/")
    print(f"  final_draft.md          — Canonical revised document")
    print(f"  session_summary.json    — Round-by-round stats")
    print(f"  metrics.json            — QC scoring rubric")
    print(f"  roundN_*.json           — Per-round oracle outputs")


if __name__ == "__main__":
    main()
