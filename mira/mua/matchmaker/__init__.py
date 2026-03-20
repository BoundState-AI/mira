"""MUA Matchmaker v8 core package.

This package contains the data models, rule-pack interpreter, and adapter
boundary that decouples v8 from v7 internals.
"""

from .adapters import (
    get_family_aliases,
    normalize_issue_code,
    resolve_material,
    search_precedents,
)
from .batch import bulk_apply_cat3_code, parse_miul_upload
from .matcher import (
    auto_detect_issues,
    determine_category,
    environment_banners,
    run_precedent_match,
)
from .models import (
    ConflictPair,
    EnvironmentSpec,
    ExportMode,
    ExportValidationResponse,
    IssueCode,
    IssueOutcome,
    IssueStatus,
    MatchmakerEvent,
    MatchmakerSession,
    MaterialResolution,
    MaterialResolutionStatus,
    PrecedentMatch,
    RationalePhrase,
    SessionSummary,
)
from .question_engine import (
    evaluate_answers,
    get_applicable_codes,
    get_next_question,
    load_rule_pack,
    validate_rule_pack,
)
from .session import MatchmakerSessionStore

__all__ = [
    "ConflictPair",
    "EnvironmentSpec",
    "ExportMode",
    "ExportValidationResponse",
    "IssueCode",
    "IssueOutcome",
    "IssueStatus",
    "MatchmakerEvent",
    "MatchmakerSession",
    "MatchmakerSessionStore",
    "MaterialResolution",
    "MaterialResolutionStatus",
    "PrecedentMatch",
    "RationalePhrase",
    "SessionSummary",
    "auto_detect_issues",
    "bulk_apply_cat3_code",
    "determine_category",
    "environment_banners",
    "evaluate_answers",
    "get_applicable_codes",
    "get_next_question",
    "get_family_aliases",
    "load_rule_pack",
    "normalize_issue_code",
    "parse_miul_upload",
    "resolve_material",
    "run_precedent_match",
    "search_precedents",
    "validate_rule_pack",
]
