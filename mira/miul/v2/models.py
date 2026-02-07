#!/usr/bin/env python3
"""
Module: Models
Purpose: MIUL Builder v2.2 - Data Models

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from pathlib import Path


# =============================================================================
# Enumerations
# =============================================================================

class Zone(Enum):
    """
    Page zones for occurrence scoring.

    Zone weights per spec v2.2:
    - TITLEBLOCK: 70 (strongest signal)
    - BORDER: 50
    - BODY: 30
    - NOTES: 10 (weak - notes don't bind)
    - UNKNOWN: 20
    """
    TITLEBLOCK = "titleblock"
    BORDER = "border"
    BODY = "body"
    NOTES = "notes"
    UNKNOWN = "unknown"


class BindingMethod(Enum):
    """How a page was bound to a drawing."""
    TITLE_BLOCK = "title_block"      # Exact match in title block
    SCORED_ZONE = "scored_zone"      # Zone-weighted scoring
    INFERRED = "inferred"            # Inferred from context


class BindingConfidence(Enum):
    """
    Confidence level for page-to-drawing binding.

    Thresholds per spec v2.2:
    - HIGH: score >= 80
    - MEDIUM: 50 <= score < 80
    - LOW: score < 50
    """
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ExplosionPolicy(Enum):
    """Per-edge explosion policy for Drawing Tree traversal."""
    EXPLODE = "explode"        # Recurse into children
    BLACK_BOX = "black_box"    # Count as 1 unit, don't recurse
    PHANTOM = "phantom"        # Skip this node, recurse into children


class NodeType(Enum):
    """Drawing node type classification."""
    ASSEMBLY = "assembly"
    SUBASSEMBLY = "subassembly"
    PIECE_PART = "piece_part"
    HARDWARE = "hardware"
    PURCHASED = "purchased"
    STANDARD = "standard"


class IssueSeverity(Enum):
    """
    Issue severity levels.

    BLOCKER: Pipeline halts, requires human resolution
    WARNING: Pipeline continues, flagged in output
    """
    BLOCKER = "blocker"
    WARNING = "warning"


class IssueType(Enum):
    """
    Issue types per spec v2.2.

    See Issue Severity Matrix in spec for mapping.
    """
    MISSING_CHILD = "missing_child"            # WARNING: Continue, mark as BLACK_BOX
    AMBIGUOUS_BINDING = "ambiguous_binding"    # BLOCKER: Stop, require disambiguation
    LOW_CONFIDENCE = "low_confidence"          # WARNING: Continue, flag in output
    QTY_CONFLICT = "qty_conflict"              # WARNING: Use higher-confidence, flag
    REV_CONFLICT = "rev_conflict"              # BLOCKER (if strict_revision)
    PARSE_FAILURE = "parse_failure"            # WARNING: Skip page, flag
    GRAPH_MISMATCH = "graph_mismatch"          # WARNING: DT wins, flag discrepancy
    CYCLE_DETECTED = "cycle_detected"          # BLOCKER: Stop graph build
    ORPHAN_PAGE = "orphan_page"                # WARNING: List in orphan_page_ids
    SUSPICIOUS_PART_NUMBER = "suspicious_part_number"  # WARNING: Part number may be misread


# =============================================================================
# Zone Scoring Constants
# =============================================================================

ZONE_WEIGHTS: dict[Zone, int] = {
    Zone.TITLEBLOCK: 70,
    Zone.BORDER: 50,
    Zone.BODY: 30,
    Zone.NOTES: 10,
    Zone.UNKNOWN: 20,
}

# Binding thresholds per spec v2.2
THRESHOLD_PRIMARY = 80       # Strong binding → pages_primary
THRESHOLD_SUPPORTING = 50    # Weak binding → pages_supporting
THRESHOLD_AMBIGUOUS = 10     # Score difference that triggers BLOCKER


# =============================================================================
# Phase 1: Ingest Models
# =============================================================================

@dataclass
class RenderParams:
    """PDF rendering parameters for reproducibility."""
    requested_dpi: int = 150
    effective_scale: float = 1.0
    rotation: int = 0


@dataclass
class PageMetadata:
    """Metadata extracted from a single PDF page."""
    page_id: str           # sha256(image_bytes)[:16]
    pdf_path: Path
    page_number: int       # 0-indexed
    render_params: RenderParams = field(default_factory=RenderParams)
    width_px: int = 0
    height_px: int = 0


# =============================================================================
# Phase 2: Extract Models
# =============================================================================

@dataclass
class BBox:
    """Bounding box coordinates (normalized 0-1 or pixel values)."""
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class Occurrence:
    """
    A drawing number occurrence on a page.

    Zone and confidence are used for binding score calculation.
    """
    drawing_number: str
    zone: Zone
    confidence: float = 1.0
    bbox: Optional[BBox] = None
    source: str = ""       # "text" or "vision"

    @property
    def weighted_score(self) -> float:
        """Zone-weighted score with confidence multiplier."""
        return ZONE_WEIGHTS.get(self.zone, 0) * self.confidence


@dataclass
class LayoutFlags:
    """Page layout signals for binding confidence."""
    has_title_block: bool = False
    has_revision_block: bool = False
    has_views: bool = False
    has_balloons: bool = False
    has_parts_list: bool = False


@dataclass
class TitleBlock:
    """Extracted title block fields."""
    drawing_number: Optional[str] = None
    sheet: Optional[str] = None          # e.g., "3 of 5"
    revision: Optional[str] = None
    title: Optional[str] = None
    cage_code: Optional[str] = None
    nha_part_number: Optional[str] = None  # Next Higher Assembly
    # Material fields from title block (v1-proven)
    material_designation: Optional[str] = None  # e.g., "6061-T6 ALUMINUM"
    material_spec: Optional[str] = None         # e.g., "SAE AMS 4124"
    uns_number: Optional[str] = None            # e.g., "UNS A96061"
    process_spec: Optional[str] = None          # e.g., "passivation per SAE-AMS-QQ-P-35"


@dataclass
class BOMRow:
    """A single row from a parts list / BOM (EPL)."""
    find_no: Optional[str] = None
    part_number: str = ""
    description: str = ""
    quantity: int = 1
    quantity_note: str = ""        # AR, REF, TBD if non-numeric
    material_callout: str = ""     # EPL MATERIAL column ONLY for this row
    spec_callout: str = ""         # ONLY if EPL row has its own spec
    uns_callout: str = ""          # ONLY if EPL row shows UNS
    form_callout: str = ""         # material form: SHEET, BAR, FORGING
    finish_callout: str = ""       # finish/process from EPL
    notes: str = ""


@dataclass
class HardwareCallout:
    """Hardware callout from notes section."""
    raw_text: str = ""
    standard: str = ""       # NAS, MS, AN, etc.
    size: str = ""
    quantity: int = 1
    material: str = ""


@dataclass
class PageExtract:
    """
    Phase 2 output: Everything extracted from a single page.

    Contains both raw text (PyMuPDF) and structured vision results.
    No identity decisions are made here - that's Phase 3.

    Per v2.3: page_id = "filename:page_index" (no image hashing)
    """
    page_id: str                 # Format: "filename:page_index"
    page_index: int              # 0-indexed within source file
    source_file: str             # Original PDF filename

    # Vision extraction (structure + zones) - NO text extraction in v2.3
    title_block: TitleBlock = field(default_factory=TitleBlock)
    drawing_number_occurrences: list[Occurrence] = field(default_factory=list)
    layout_flags: LayoutFlags = field(default_factory=LayoutFlags)
    parts_list: list[BOMRow] = field(default_factory=list)
    hardware_callouts: list[HardwareCallout] = field(default_factory=list)

    # Revision info
    revision: str = ""

    @property
    def key_candidates(self) -> set[str]:
        """All drawing numbers found on this page (for binding candidate list)."""
        candidates = set()
        for occ in self.drawing_number_occurrences:
            candidates.add(occ.drawing_number)
        if self.title_block.drawing_number:
            candidates.add(self.title_block.drawing_number)
        return candidates


# =============================================================================
# Phase 3: Assemble Models
# =============================================================================

@dataclass(frozen=True)
class DrawingKey:
    """
    Unique drawing identity (frozen for use as dict key).

    Revision is optional for grouping purposes but tracked for conflict detection.
    """
    drawing_number: str
    revision: Optional[str] = None

    def __hash__(self):
        return hash((self.drawing_number, self.revision))


@dataclass
class PageBinding:
    """Record of how a page was bound to a drawing."""
    page_id: str
    binding_score: float
    binding_method: BindingMethod
    binding_confidence: BindingConfidence


@dataclass
class DrawingEntity:
    """
    Phase 3 output: A complete drawing assembled from one or more pages.

    Pages are split into primary (score >= 80) and supporting (50-79).
    """
    key: DrawingKey
    title: str = ""

    # Page bindings
    pages_primary: list[PageBinding] = field(default_factory=list)
    pages_supporting: list[PageBinding] = field(default_factory=list)

    # Merged data from all pages
    parts_list: list[BOMRow] = field(default_factory=list)
    hardware: list[HardwareCallout] = field(default_factory=list)
    notes: str = ""

    # Material from title block (for detail drawings)
    # These are populated from the drawing's own title block/notes, not from parent EPL
    material_designation: str = ""  # e.g., "INCONEL 625", "A286 CRES"
    material_spec: str = ""         # e.g., "SAE AMS 5666", "SAE AMS 5737"
    uns_number: str = ""            # e.g., "UNS N06625", "UNS S66286"
    process_spec: str = ""          # e.g., "passivation per SAE-AMS-QQ-P-35"

    # Hierarchy info (filled in Phase 4)
    parent: Optional[str] = None
    children: list[str] = field(default_factory=list)
    node_type: NodeType = NodeType.ASSEMBLY

    @property
    def drawing_number(self) -> str:
        return self.key.drawing_number

    @property
    def revision(self) -> Optional[str]:
        return self.key.revision

    @property
    def all_page_ids(self) -> list[str]:
        """All page IDs bound to this drawing."""
        return [p.page_id for p in self.pages_primary] + [p.page_id for p in self.pages_supporting]


# =============================================================================
# Phase 4: Graph Models
# =============================================================================

@dataclass
class GraphEdgeEvidence:
    """Traceability for graph edges."""
    source_drawing: str
    page_id: str
    row_index: Optional[int] = None
    bbox: Optional[BBox] = None


@dataclass
class GraphEdge:
    """
    A parent-child relationship in the Drawing Tree.

    Per-edge explosion policy allows different treatment of the same
    child in different contexts.
    """
    parent: DrawingKey
    child: DrawingKey
    find_no: Optional[str] = None
    qty_per_parent: int = 1
    explosion_policy: ExplosionPolicy = ExplosionPolicy.EXPLODE
    evidence: list[GraphEdgeEvidence] = field(default_factory=list)


@dataclass
class DrawingGraph:
    """
    Phase 4 output: The complete drawing hierarchy.

    When a Drawing Tree PDF exists, it is the hierarchy authority.
    BOM data fills in quantities and validates structure.
    """
    root: Optional[DrawingKey] = None
    nodes: dict[DrawingKey, DrawingEntity] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)

    # DT reconciliation
    dt_source: Optional[str] = None  # Path to DT PDF if used

    def get_children(self, key: DrawingKey) -> list[GraphEdge]:
        """Get all child edges for a drawing."""
        return [e for e in self.edges if e.parent == key]

    def get_parent(self, key: DrawingKey) -> Optional[GraphEdge]:
        """Get parent edge for a drawing."""
        for e in self.edges:
            if e.child == key:
                return e
        return None

    def detect_cycles(self) -> list[list[DrawingKey]]:
        """Detect cycles in the graph using DFS."""
        visited: set[DrawingKey] = set()
        cycles: list[list[DrawingKey]] = []

        def dfs(node: DrawingKey, path: list[DrawingKey], path_set: set[DrawingKey]) -> None:
            """DFS that finds ALL cycles, not just first."""
            if node in visited:
                return

            visited.add(node)
            path.append(node)
            path_set.add(node)

            for edge in self.get_children(node):
                child = edge.child
                if child in path_set:
                    # Found cycle - child is already in current path
                    try:
                        cycle_start = path.index(child)
                        cycles.append(path[cycle_start:] + [child])
                    except ValueError:
                        # Child in path_set but not path - shouldn't happen but handle gracefully
                        cycles.append([child, child])  # Report as self-cycle
                elif child not in visited:
                    dfs(child, path, path_set)

            path.pop()
            path_set.discard(node)

        for node in self.nodes:
            if node not in visited:
                dfs(node, [], set())

        return cycles


# =============================================================================
# Phase 5: MIUL Models
# =============================================================================

@dataclass
class MIULEntry:
    """
    Phase 5 output: A single row in the MIUL spreadsheet.

    Includes evidence chain for traceability.
    """
    index: int
    find_no: str = ""
    part_number: str = ""
    description: str = ""
    qty_per_top: int = 1

    # Material data
    material: str = ""
    spec: str = ""
    finish: str = ""

    # Traceability
    source_drawing: str = ""
    evidence_chain: list[str] = field(default_factory=list)  # [drawing -> page -> row]
    parent: str = ""
    detail_drawing: str = ""
    next_assembly: str = ""

    # Additional MAPTIS fields
    change_letter: str = ""
    drawing_source: str = ""
    material_form: str = ""
    material_manufacturer: str = ""
    designation: str = ""
    material_specification: str = ""
    process_specification: str = ""
    environment: str = ""
    material_code: str = ""
    standard_part_number: str = ""

    # Node type for categorization
    node_type: NodeType = NodeType.PIECE_PART


# =============================================================================
# Issue Tracking
# =============================================================================

@dataclass
class Issue:
    """
    A problem requiring attention.

    BLOCKER issues halt the pipeline and require human resolution.
    WARNING issues are flagged but pipeline continues.
    """
    severity: IssueSeverity
    issue_type: IssueType
    affected: str                           # Drawing number or page ID
    message: str
    evidence_page_ids: list[str] = field(default_factory=list)

    @property
    def is_blocker(self) -> bool:
        return self.severity == IssueSeverity.BLOCKER


# =============================================================================
# Package-Level Container
# =============================================================================

@dataclass
class PackageExtract:
    """
    Complete extraction result for a package of drawings.

    Contains all artifacts from all phases plus issue tracking.
    """
    package_id: str                                      # Unique ID for this extraction run
    prompt_version: str = ""                             # For cache keying
    model_version: str = ""                              # For cache keying

    # Phase outputs
    pages: list[PageExtract] = field(default_factory=list)
    drawings: dict[DrawingKey, DrawingEntity] = field(default_factory=dict)
    graph: Optional[DrawingGraph] = None
    miul: list[MIULEntry] = field(default_factory=list)

    # Issue tracking
    issues: list[Issue] = field(default_factory=list)
    orphan_page_ids: list[str] = field(default_factory=list)

    @property
    def has_blockers(self) -> bool:
        """True if any BLOCKER issues exist."""
        return any(issue.is_blocker for issue in self.issues)

    @property
    def blocker_count(self) -> int:
        """Count of BLOCKER issues."""
        return sum(1 for issue in self.issues if issue.is_blocker)

    @property
    def warning_count(self) -> int:
        """Count of WARNING issues."""
        return sum(1 for issue in self.issues if not issue.is_blocker)

    def add_issue(self, issue: Issue) -> None:
        """Add an issue to the package."""
        self.issues.append(issue)

    def get_issues_by_type(self, issue_type: IssueType) -> list[Issue]:
        """Get all issues of a specific type."""
        return [i for i in self.issues if i.issue_type == issue_type]


# =============================================================================
# Legacy Compatibility Aliases
# =============================================================================

# For backwards compatibility with existing v2 code
PartItem = BOMRow
ZoneOccurrence = Occurrence
Edge = GraphEdge
DrawingTree = DrawingGraph
MIULRow = MIULEntry
