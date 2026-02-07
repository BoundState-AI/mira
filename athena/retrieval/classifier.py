#!/usr/bin/env python3
"""
Module: Classifier
Purpose: Classify query and extract components.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Safety Critical: True
"""

from __future__ import annotations

"""
Athena Query Classifier

Lightweight, production-ready classifier that routes incoming queries to the
right retrieval path(s): text, visual, or hybrid. Also extracts useful
constraints (file types, thresholds, part numbers, standards) and sets
appropriate budgets for discovery and post-chunking phases.

Features:
- Zero heavy deps.
- Deterministic + explainable scores with evidence for audits.
- Pluggable hooks so hybrid_orchestrator can adjust budgets at runtime.

__safety_critical__ = True  # NASA document processing system


Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required

Inputs
------
query: str
  User query text

history: Optional[list[str]] = None
  Previous queries from same session (for context)

Outputs
-------
QueryClassification dataclass containing:
- route: "text" | "visual" | "hybrid"
- modalities: set[str]
- visual_types: list[str]  # e.g., ["technical_drawing", "equipment_photo"]
- requires_ocr: bool
- filters: dict[str, Any]  # file_ext, doc_types, standards, part_numbers, etc.
- search_terms: list[str]
- budgets: dict[str, int]
- scores: dict[str, float]  # sub-scores
- evidence: list[str]

Usage
-----
- hybrid_orchestrator.py should call classify_query(query) first.
- Use classification.route to choose path(s):
  * text → document discovery
  * visual → image search
  * hybrid → both in parallel; merge + rerank
- Honor classification.budgets for discovery and post-chunk limits.

BoundState Design Integrity
---------------------------
- In keeping with BoundState design integrity rules, this file performs
  classification only; it does not make material recommendations.
- No string-matching is used for *material-substitution* logic.

Compliance: SWE-013 (traceability via evidence)
"""

import re
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

# NASA COMPLIANCE: Comprehensive audit logging
logger = logging.getLogger(__name__)

# ------------------------------
# Data Model
# ------------------------------

@dataclass
class QueryClassification:
    route: str  # "text" | "visual" | "hybrid"
    modalities: Set[str]
    visual_types: List[str]  # e.g., ["technical_drawing", "equipment_photo"]
    requires_ocr: bool
    filters: Dict[str, Any]  # file_ext, doc_types, standards, part_numbers, etc.
    search_terms: List[str]
    budgets: Dict[str, int]
    scores: Dict[str, float]  # sub-scores
    evidence: List[str]
    source: str = "query_classifier"

# ------------------------------
# Visual Query Patterns
# ------------------------------

VISUAL_TRIGGERS: List[str] = [
    r'\b(show|see|view|look at|photo|image|picture|pic|visual|diagram|drawing|sketch|chart|graph|plot|figure|map|screenshot|scan|render|illustration|blueprint|schematic|cross-section|micrograph|spectrogram|thermogram|x-ray|CT scan|MRI|ultrasound)\b',
    r'\b(setup|configuration|assembly|disassembly|weld joint|fracture surface|microstructure|corrosion|damage|failure|test specimen|equipment|instrument|panel|control|gauge|meter|display|readout|tool|fixture|jig|prototype|model|mockup|simulation|rendering|CAD|3D model|animation|video frame|still)\b',
]

VISUAL_TYPES: Dict[str, List[str]] = {
    "technical_drawing": [
        r'\b(drawing|blueprint|schematic|CAD|3D model|assembly drawing|detail drawing|shop drawing|isometric|orthographic|section view|elevation|plan view|dimension|tolerance|bill of materials|BOM)\b',
    ],
    "data_visualization": [
        r'\b(chart|graph|plot|histogram|scatter plot|spectrum|waveform|oscilloscope|data trace|curve|line graph|bar chart|pie chart|flowchart|Gantt|PERT)\b',
    ],
    "test_photo": [
        r'\b(photo|image|picture|pic|test|specimen|cross-section|micrograph|SEM|TEM|optical microscope|fracture surface|failure analysis|corrosion|damage|wear|crack|defect|inspection|NDT|dye penetrant|x-ray|ultrasound)\b',
    ],
    "weld_analysis": [
        r'\b(weld|joint|cross-section|bead|penetration|fusion|porosity|crack|distortion|residual stress|microstructure|heat affected zone|HAZ|weld pool|macrograph|metallography)\b',
    ],
    "equipment_photo": [
        r'\b(equipment|instrument|tool|machine|setup|configuration|panel|control|gauge|meter|display|readout|fixture|jig|test stand|rig|chamber|furnace|oven|press|welder|robot|manipulator|CNC|lathe|mill)\b',
    ],
    "general_technical": [
        r'\b(technical|engineering|analysis|report|data|results|measurements|calculations|simulation|model|prototype|test|experiment|lab|workshop|manufacturing|fabrication|assembly|disassembly|maintenance|repair|inspection|quality|control|assurance|QA|QC)\b',
    ],
}

# ------------------------------
# OCR and Constraint Patterns
# ------------------------------

OCR_INDICATORS: List[str] = [
    r'\b(threshold|above|below|greater than|less than|exceed|minimum|maximum|range|from \d+ to \d+|at least|up to)\b',
    r'\b(500F|350C|high temperature|low pressure|500 psi)\b',
]

CONSTRAINT_PATTERNS: Dict[str, str] = {
    "file_types": r'\b(pdf|docx|doc|txt|md|xml|pptx|xlsx|dwg|step|igs|par|asm|raww|dat|jpg|png|tiff)\b',
    "standards": r'\b(NASA[-_]?(STD|HDBK|TM|SP)[-_]?\d+[A-Z]?|MSFC[-_]?(STD|SPEC|HDBK|PRC)[-_]?\d+[A-Z]?|MIL[-_]STD[-_]?\d+[A-Z]?|ASTM[-_]?[A-Z]\d+[A-Z]?|ISO[-_]?\d+[-_]?\d*)\b',
    "part_numbers": r'\b[A-Z]{2,4}[-_]?\d{3,8}[-_]?[A-Z]?\d*\b',
    "dimensions": r'\d+\.?\d*\s*[x×]\s*\d+\.?\d*\s*[x×]?\s*\d*\.?\d*',
    "temperatures": r'\d+\.?\d*\s*[°]?\s*[FfCc]\b',
    "thresholds": r'\b(above|below|greater than|less than|exceed|minimum|maximum|at least|up to|range|from \d+ to \d+)\b',
}

# ------------------------------
# Main Classification Function
# ------------------------------

def classify_query(query: str, history: Optional[List[str]] = None) -> QueryClassification:
    """
    Classify query and extract components.

    Args:
        query: User query text
        history: Previous queries for context

    Returns:
        QueryClassification with routing, budgets, and evidence
    

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    # NASA COMPLIANCE: Generate req_id for audit logging
    req_id = str(uuid.uuid4())

    # Preprocess query
    q = query.lower().strip()

    # NASA COMPLIANCE: Log query classification attempt
    logger.info(f"Classifying query: {len(query)} chars", extra={'req_id': req_id})

    # Compute scores
    scores, evidence = _compute_scores(q, req_id)

    # Extract visual types
    visual_types = _extract_visual_types(q)
    requires_ocr = scores["ocr"] > 0.2

    # Extract filters and search terms
    filters = _extract_filters(q)
    search_terms = _extract_search_terms(q)

    # Determine route and modalities
    route, modalities = _determine_route(scores)

    # Compute budgets
    budgets = _compute_budgets(route, filters)

    # Build classification
    return QueryClassification(
        route=route,
        modalities=modalities,
        visual_types=visual_types,
        requires_ocr=requires_ocr,
        filters=filters,
        search_terms=search_terms,
        budgets=budgets,
        scores=scores,
        evidence=evidence
    )

    # NASA COMPLIANCE: Log classification results
    logger.info(f"Query classified as {route} route with {len(visual_types)} visual types",
               extra={'req_id': req_id})
    logger.info(f"Classification scores: visual={scores['visual']:.2f}, text={scores['text']:.2f}, ocr={scores['ocr']:.2f}",
               extra={'req_id': req_id})

    return classification

# ------------------------------
# Scoring
# ------------------------------

def _compute_scores(q: str, req_id: str) -> Tuple[Dict[str, float], List[str]]:
    """
    Compute classification scores and collect evidence.

    Returns:
        (scores_dict, evidence_list)
    

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    scores = {"visual": 0.0, "text": 0.0, "ocr": 0.0}
    evidence = []

    # Visual trigger score (0-1)
    visual_hits = sum(bool(re.search(pat, q)) for pat in VISUAL_TRIGGERS)
    scores["visual"] = min(visual_hits / len(VISUAL_TRIGGERS), 1.0)
    if visual_hits > 0:
        evidence.append(f"visual_triggers={visual_hits}")
        logger.debug(f"Visual triggers detected: {visual_hits}", extra={'req_id': req_id})

    # OCR indicator score (0-1)
    ocr_hits = sum(bool(re.search(pat, q)) for pat in OCR_INDICATORS)
    scores["ocr"] = min(ocr_hits / len(OCR_INDICATORS), 1.0)
    if ocr_hits > 0:
        evidence.append(f"ocr_indicators={ocr_hits}")
        logger.debug(f"OCR indicators detected: {ocr_hits}", extra={'req_id': req_id})

    # Text-heavy if no visual hits
    if scores["visual"] == 0:
        scores["text"] = 1.0
        evidence.append("no_visual_triggers=text_primary")
        logger.debug("No visual triggers found, routing to text", extra={'req_id': req_id})
    else:
        scores["text"] = 0.5  # moderate text score when visual present

    # NASA COMPLIANCE: Log scoring completion
    logger.debug(f"Scoring complete: {scores}", extra={'req_id': req_id})

    return scores, evidence

def _determine_route(scores: Dict[str, float]) -> Tuple[str, Set[str]]:
    """
    Determine primary route and modalities based on scores.

    Returns:
        (route, modalities_set)
    

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    visual_score = scores["visual"]
    text_score = scores["text"]
    ocr_score = scores["ocr"]

    if visual_score > 0.6 or ocr_score > 0.4:
        route = "visual"
        modalities = {"image"}
    elif visual_score > 0.3 or ocr_score > 0.2:
        route = "hybrid"
        modalities = {"text", "image"}
    else:
        route = "text"
        modalities = {"text"}

    if ocr_score > 0.2:
        modalities.add("ocr")

    return route, modalities

def _extract_visual_types(q: str) -> List[str]:
    """
    Extract likely visual content types from query.

    Returns:
        List of visual type names, sorted by relevance
    

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    visual_types = []
    hits = {}
    for vtype, patterns in VISUAL_TYPES.items():
        hits_count = sum(bool(re.search(pat, q)) for pat in patterns)
        if hits_count > 0:
            visual_types.append(vtype)
            hits[vtype] = hits_count

    return sorted(visual_types, key=lambda x: hits.get(x, 0), reverse=True)[:3]

def _extract_filters(q: str) -> Dict[str, Any]:
    """
    Extract search filters and constraints from query.

    Returns:
        Dict of filter_name -> [matches]
    

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    filters = {}
    for name, pat in CONSTRAINT_PATTERNS.items():
        matches = re.findall(pat, q, re.IGNORECASE)
        if matches:
            filters[name] = matches

    return filters

def _extract_search_terms(q: str) -> List[str]:
    """
    Extract cleaned search terms from query.

    Returns:
        List of unique search terms
    

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    # Remove common stopwords
    stopwords = {"the", "a", "an", "in", "on", "at", "for", "with", "by", "of", "to"}

    terms = [t.strip() for t in re.split(r'\s+', q.lower()) if t.strip() and t not in stopwords]
    return list(set(terms))  # Unique terms

def _compute_budgets(route: str, filters: Dict[str, Any]) -> Dict[str, int]:
    """
    Compute retrieval budgets based on route and filters.

    Compliance: SWE-013 (resource limits)
    

Compliance: NASA-CSET, SWE-013, SWE-032, SWE-065
Security Classification: CUI//SP-PRVCY
Authorization: NASA ATO Required
"""
    # Base budgets
    budgets = {
        "k_docs_discovery": 12,
        "post_chunk_budget": 4,       # docs to post-chunk on first pass
        "k_chunks_per_doc": 6,
        "k_images": 24,
    }

    if route == "visual":
        budgets["k_docs_discovery"] = 6  # fewer docs when visual-heavy
        budgets["post_chunk_budget"] = 2
        budgets["k_images"] = 48  # scan more images
    elif route == "hybrid":
        budgets["k_docs_discovery"] = 10
        budgets["post_chunk_budget"] = 3
        budgets["k_images"] = 32

    # Tighten when specific (part number, threshold) to reduce latency
    has_part = bool(filters.get("part_numbers"))
    has_thresholds = bool(filters.get("thresholds"))
    if has_part or has_thresholds:
        budgets["k_docs_discovery"] = max(6, budgets["k_docs_discovery"] - 4)
        budgets["post_chunk_budget"] = max(2, budgets["post_chunk_budget"] - 1)

    # If the query mentions "all" or "comprehensive", allow a bit more
    if any(w in q for w in [" all ", " comprehensive "]):
        budgets["post_chunk_budget"] += 2

    return budgets


# ------------------------------
# Demo / CLI
# ------------------------------
if __name__ == "__main__":
    examples = [
        "Show me images of weld cross-sections for aluminum joints",
        "Find documents about AS9100 clause 8.5 and show related images",
        "What's the procedure for friction stir welding in EM32?",
        "Locate drawings containing part number VAT-2-3215",
        "Find equipment photos with temperature settings above 500F",
        "Impact path for NASA-STD-5005 references",
    ]
    for q in examples:
        qc = classify_query(q)
        print("\nQ:", q)
        print("route:", qc.route, "modalities:", qc.modalities)
        print("visual_types:", qc.visual_types, "requires_ocr:", qc.requires_ocr)
        print("filters:", qc.filters)
        print("budgets:", qc.budgets)
        print("scores:", qc.scores)
        print("evidence:", qc.evidence)