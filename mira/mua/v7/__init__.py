"""MUA v7 data model and pipeline package.

Material Usage Agreement generation pipeline models and services,
conforming to the MUA v7 Final Specification.

Exports
-------
Models (from ``models.py``):
    All Pydantic models, enums, and data structures for the MUA pipeline.

Session management (from ``session.py``):
    ``SessionManager``  -- CRUD + lifecycle management for MUA sessions.
    ``MuaSessionState``  -- Pydantic model of full session state.

Investigation (from ``investigator.py``):
    ``MUAInvestigator``  -- Step 2 orchestrator: evidence gathering.

Material resolution (from ``material_resolver.py``):
    ``resolve_material``  -- Free-text to MAPTIS code resolution.

Evidence strength (from ``confidence.py``):
    ``calculate_evidence_strength``  -- Composite evidence scoring.

Conflict detection (from ``conflict_detector.py``):
    ``detect_conflicts``  -- Cross-source conflict identification.

Category routing (from ``category_router.py``):
    ``CategoryRouter``  -- MUA Category I/II/III routing.

Draft rendering (from ``draft_renderer.py``):
    ``DraftRenderer``  -- Step 4 MUA document generation.

Fact checking (from ``fact_checker.py``):
    ``FactChecker``  -- Claim-level verification against evidence.

Qualification planning (from ``qualification_plan.py``):
    ``QualificationPlanGenerator``  -- Novel-material test plan generation.

Process sensitivity (from ``process_sensitivity.py``):
    ``ProcessSensitivityHandler``  -- Step 1b process parameter handling.

Relationship explanation (from ``relationship_explainer.py``):
    ``generate_relationship_explanations``  -- Precedent relationship narratives.
"""

from .models import *  # noqa: F401, F403
from .session import MuaSessionState, SessionManager  # noqa: F401
from .qualification_plan import QualificationPlanGenerator  # noqa: F401

from .investigator import MUAInvestigator  # noqa: F401
from .material_resolver import resolve_material  # noqa: F401
from .confidence import calculate_evidence_strength  # noqa: F401
from .conflict_detector import detect_conflicts  # noqa: F401
from .category_router import CategoryRouter, AuthorityPack, evaluate_appendix_b  # noqa: F401
from .pg_precedent_search import search_precedents_pg, pg_results_to_v7_matches  # noqa: F401
from .draft_renderer import DraftRenderer  # noqa: F401
from .fact_checker import FactChecker  # noqa: F401
from .process_sensitivity import ProcessSensitivityHandler  # noqa: F401
from .relationship_explainer import generate_relationship_explanations  # noqa: F401
