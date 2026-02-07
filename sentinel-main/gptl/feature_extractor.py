# Copyright 2025 BoundStateAI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
GPTL Feature Extractor - L0 DocFeatures computation with Haiku validation
==========================================================================

Computes DocFeatures at ingestion time. This is the foundation of GPTL's
feature-first constraint system.

CRITICAL REQUIREMENT: DocFeatures MUST be computed BEFORE the document
is searchable. Constraints operate on validated DocFeatures, not raw text.

The extraction pipeline:
1. Parse document structure (from existing content_miner)
2. Extract entities (materials, standards, hazards, systems, processes)
3. Compute evidence markers (flags)
4. Apply derivation rules
5. Validate derivation with Haiku
6. Package as DocFeatures

Compliance: SWE-032 (Data Validation), SWE-033 (Requirements Traceability)
Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import hashlib
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from gptl.claude_client import BaseClaudeClient, ParsedResponse, get_default_client
from gptl.evidence_taxonomy import DerivationEngine, create_derivation_engine
from gptl.prompts import L0_DERIVATION_VALIDATION_V1, L0_NOISE_DETECTION_V1
from gptl.schema import (
    DateSource,
    DerivationRule,
    DerivationValidationResponse,
    DocFeatures,
    DocFlags,
    DocType,
    EntitySet,
    EvidenceTaxonomy,
    EvidenceType,
    ModelTier,
)

__safety_critical__: bool = True

logger = logging.getLogger(__name__)


# =============================================================================
# INPUT TYPES
# =============================================================================

@dataclass
class RawDocument:
    """
    Raw document input for feature extraction.

    This is the minimal input required for feature extraction.
    Can be extended with additional metadata.
    """
    doc_id: str
    content: str  # Full text content
    title: str | None = None
    file_path: str | None = None
    file_type: str | None = None
    metadata: dict[str, Any] | None = None

    def compute_hash(self) -> str:
        """Compute content hash."""
        return hashlib.sha256(self.content.encode()).hexdigest()[:32]

    @property
    def content_sample(self) -> str:
        """Get first 500 chars for LLM validation."""
        return self.content[:500] if self.content else ""


# =============================================================================
# ENTITY EXTRACTOR PROTOCOL (Dependency Inversion)
# =============================================================================

class EntityExtractorProtocol(Protocol):
    """Protocol for entity extraction implementations."""

    def extract_materials(self, text: str) -> list[str]:
        """Extract material names."""
        ...

    def extract_standards(self, text: str) -> list[str]:
        """Extract standard references (NASA-STD, MIL-STD, etc.)."""
        ...

    def extract_hazards(self, text: str) -> list[str]:
        """Extract hazard mentions."""
        ...

    def extract_systems(self, text: str) -> list[str]:
        """Extract system/component names."""
        ...

    def extract_processes(self, text: str) -> list[str]:
        """Extract process names."""
        ...


# =============================================================================
# REGEX-BASED ENTITY EXTRACTOR
# =============================================================================

class RegexEntityExtractor:
    """
    Regex-based entity extractor.

    Uses pattern matching for entity extraction.
    Can be replaced with ML-based extractor for better accuracy.
    """

    # Material patterns
    MATERIAL_PATTERNS = [
        r"\b(aluminum|steel|titanium|inconel|hastelloy|monel|copper|brass)\b",
        r"\b(Al|Ti|Ni|Cu|Fe)-?\d{3,4}\b",
        r"\b[A-Z]{2,4}-?\d{3,5}[A-Z]?\b",  # Alloy designations
        r"\bPTFE\b|\bPEEK\b|\bViton\b|\bKalrez\b|\bNylon\b",
        r"\b(epoxy|silicone|polyurethane|rubber)\b",
    ]

    # Standard patterns
    STANDARD_PATTERNS = [
        r"NASA[- ]?(STD|HDBK|TM|SP|PRC)[- ]?\d+[A-Z]?",
        r"MIL[- ]?(STD|SPEC|HDBK|PRF)[- ]?\d+[A-Z]?",
        r"ASTM\s*[A-Z]?\d+",
        r"ISO\s*\d+",
        r"SAE\s*(AMS|AS|J)\d+",
        r"MSFC[- ]?(STD|SPEC|HDBK|PRC)[- ]?\d+",
    ]

    # Hazard patterns
    HAZARD_PATTERNS = [
        r"\b(flammab|ignit|combust|explos)[a-z]*\b",
        r"\b(toxic|hazard|danger|warning|caution)\b",
        r"\b(corros|oxidiz|react)[a-z]*\b",
        r"\b(LOX|GOX|LH2|GH2|LN2)\s*(compat|incompat|sensitiv)",
        r"\b(failure|crack|fatigue|stress|rupture)\b",
    ]

    # Process patterns
    PROCESS_PATTERNS = [
        r"\b(weld|braze|solder)[a-z]*\b",
        r"\b(machin|mill|turn|drill|grind)[a-z]*\b",
        r"\b(heat\s*treat|anneal|quench|temper)[a-z]*\b",
        r"\b(coat|plate|anodiz|passivat)[a-z]*\b",
        r"\b(inspect|test|verif|valid)[a-z]*\b",
        r"\b(assembl|install|integrat)[a-z]*\b",
    ]

    # System patterns (general)
    SYSTEM_PATTERNS = [
        r"\b(engine|turbine|pump|valve|tank|pipe|duct)\b",
        r"\b(sensor|actuator|controller|circuit)\b",
        r"\b(SLS|RS-25|Orion|ICPS|EUS)\b",
        r"\b(propulsion|avionics|thermal|structural)\s*(system|subsystem)\b",
    ]

    def __init__(self):
        self._compile_patterns()

    def _compile_patterns(self):
        """Compile regex patterns for efficiency."""
        self._material_re = [re.compile(p, re.IGNORECASE) for p in self.MATERIAL_PATTERNS]
        self._standard_re = [re.compile(p, re.IGNORECASE) for p in self.STANDARD_PATTERNS]
        self._hazard_re = [re.compile(p, re.IGNORECASE) for p in self.HAZARD_PATTERNS]
        self._process_re = [re.compile(p, re.IGNORECASE) for p in self.PROCESS_PATTERNS]
        self._system_re = [re.compile(p, re.IGNORECASE) for p in self.SYSTEM_PATTERNS]

    def _extract_with_patterns(self, text: str, patterns: list[re.Pattern]) -> list[str]:
        """Extract unique matches from text using patterns."""
        matches = set()
        for pattern in patterns:
            for match in pattern.findall(text):
                if isinstance(match, tuple):
                    match = match[0]
                matches.add(match.strip())
        return sorted(matches)

    def extract_materials(self, text: str) -> list[str]:
        return self._extract_with_patterns(text, self._material_re)

    def extract_standards(self, text: str) -> list[str]:
        return self._extract_with_patterns(text, self._standard_re)

    def extract_hazards(self, text: str) -> list[str]:
        return self._extract_with_patterns(text, self._hazard_re)

    def extract_systems(self, text: str) -> list[str]:
        return self._extract_with_patterns(text, self._system_re)

    def extract_processes(self, text: str) -> list[str]:
        return self._extract_with_patterns(text, self._process_re)


# =============================================================================
# DOC TYPE CLASSIFIER
# =============================================================================

class DocTypeClassifier:
    """
    Classifies document type based on content patterns.

    Uses heuristics. Can be replaced with ML classifier.
    """

    DOC_TYPE_PATTERNS: dict[DocType, list[str]] = {
        DocType.SPECIFICATION: [
            r"specification|requirement|shall\s+be|must\s+be",
            r"scope|purpose|applicable\s+documents",
        ],
        DocType.PROCEDURE: [
            r"procedure|step\s+\d|instructions?|how\s+to",
            r"perform|execute|conduct|complete\s+the\s+following",
        ],
        DocType.REPORT: [
            r"test\s+report|analysis|results|findings|conclusion",
            r"summary|abstract|introduction|methodology",
        ],
        DocType.DRAWING: [
            r"drawing|schematic|diagram|dwg|rev\s+[A-Z]",
            r"scale:|dimensions:|tolerance:",
        ],
        DocType.MANUAL: [
            r"manual|handbook|guide|operation|maintenance",
            r"chapter\s+\d|section\s+\d|appendix",
        ],
        DocType.MEMO: [
            r"memo(randum)?|from:|to:|subject:|re:",
            r"internal\s+use|distribution:",
        ],
        DocType.EMAIL: [
            r"from:|to:|cc:|sent:|subject:",
            r"@\w+\.\w+|dear\s+\w+|regards,",
        ],
        DocType.MARKETING: [
            r"contact\s+us|learn\s+more|buy\s+now|free\s+trial",
            r"our\s+products?|solutions?|services?",
            r"call\s+today|limited\s+time|special\s+offer",
        ],
    }

    def __init__(self):
        self._compiled = {
            doc_type: [re.compile(p, re.IGNORECASE) for p in patterns]
            for doc_type, patterns in self.DOC_TYPE_PATTERNS.items()
        }

    def classify(self, text: str, file_type: str | None = None) -> DocType:
        """Classify document type."""
        # Check file extension hints
        if file_type:
            ext = file_type.lower()
            if ext in (".dwg", ".dxf", ".step", ".iges"):
                return DocType.DRAWING
            if ext == ".msg":
                return DocType.EMAIL

        # Score each type
        scores: dict[DocType, int] = {}
        text_sample = text[:5000]  # Use first 5000 chars

        for doc_type, patterns in self._compiled.items():
            score = sum(1 for p in patterns if p.search(text_sample))
            if score > 0:
                scores[doc_type] = score

        if not scores:
            return DocType.UNKNOWN

        return max(scores.items(), key=lambda x: x[1])[0]


# =============================================================================
# FLAGS EXTRACTOR
# =============================================================================

class FlagsExtractor:
    """Extracts DocFlags from document content."""

    # Patterns for flag detection
    MEASUREMENT_PATTERNS = [
        r"\d+\.?\d*\s*(mm|cm|m|in|ft|kg|g|lb|psi|ksi|MPa|GPa|°[CF]|K)",
        r"±\s*\d+\.?\d*",
        r"\d+\.?\d*\s*[xX×]\s*\d+",
    ]

    TABLE_PATTERNS = [
        r"\|.*\|.*\|",  # Markdown tables
        r"^\s*\d+\s+\d+\s+\d+",  # Numeric columns
        r"table\s+\d+|table\s+[IVX]+",
    ]

    TEST_CONDITION_PATTERNS = [
        r"test\s+(temperature|pressure|condition|environment)",
        r"(ambient|room|elevated|cryogenic)\s+temperature",
        r"(vacuum|atmosphere|inert\s+gas|nitrogen)",
        r"test\s+duration|exposure\s+time|cycle[sd]?",
    ]

    SPEC_REFERENCE_PATTERNS = [
        r"per\s+(NASA|MIL|ASTM|ISO|SAE)",
        r"in\s+accordance\s+with",
        r"reference[sd]?\s+(document|specification|standard)",
        r"see\s+(section|paragraph|appendix)",
    ]

    FIGURE_PATTERNS = [
        r"figure\s+\d+|fig\.\s*\d+",
        r"image\s+\d+|photo\s+\d+",
        r"schematic|diagram|illustration",
    ]

    EQUATION_PATTERNS = [
        r"equation\s+\d+|eq\.\s*\d+",
        r"[=<>≤≥]\s*\d+\.?\d*\s*[+\-*/^]",
        r"∫|∑|∏|√|∂|∇",
    ]

    NOISE_PATTERNS = [
        r"click\s+here|learn\s+more|subscribe|newsletter",
        r"copyright\s+©|all\s+rights\s+reserved",
        r"privacy\s+policy|terms\s+of\s+service|cookie",
        r"follow\s+us|share\s+on|like\s+us",
    ]

    def __init__(self):
        self._compile_patterns()

    def _compile_patterns(self):
        self._measurement_re = [re.compile(p, re.IGNORECASE) for p in self.MEASUREMENT_PATTERNS]
        self._table_re = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in self.TABLE_PATTERNS]
        self._test_re = [re.compile(p, re.IGNORECASE) for p in self.TEST_CONDITION_PATTERNS]
        self._spec_re = [re.compile(p, re.IGNORECASE) for p in self.SPEC_REFERENCE_PATTERNS]
        self._figure_re = [re.compile(p, re.IGNORECASE) for p in self.FIGURE_PATTERNS]
        self._equation_re = [re.compile(p, re.IGNORECASE) for p in self.EQUATION_PATTERNS]
        self._noise_re = [re.compile(p, re.IGNORECASE) for p in self.NOISE_PATTERNS]

    def _has_pattern(self, text: str, patterns: list[re.Pattern]) -> bool:
        return any(p.search(text) for p in patterns)

    def extract(self, text: str) -> DocFlags:
        """Extract DocFlags from text."""
        return DocFlags(
            has_measurements=self._has_pattern(text, self._measurement_re),
            has_tables=self._has_pattern(text, self._table_re),
            has_test_conditions=self._has_pattern(text, self._test_re),
            has_spec_references=self._has_pattern(text, self._spec_re),
            has_figures=self._has_pattern(text, self._figure_re),
            has_equations=self._has_pattern(text, self._equation_re),
            is_noise_candidate=self._has_pattern(text, self._noise_re),
        )


# =============================================================================
# DATE EXTRACTOR
# =============================================================================

class DateExtractor:
    """Extracts document date from content or metadata."""

    DATE_PATTERNS = [
        # ISO format
        (r"(\d{4})-(\d{2})-(\d{2})", "%Y-%m-%d"),
        # US format
        (r"(\d{1,2})/(\d{1,2})/(\d{4})", "%m/%d/%Y"),
        # Written format
        (r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})", None),
        # Revision date patterns
        (r"(?:date|dated|rev(?:ision)?)\s*[:\-]?\s*(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", "%m/%d/%Y"),
    ]

    MONTH_MAP = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }

    def extract(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[datetime | None, float, DateSource]:
        """
        Extract date from document.

        Returns:
            Tuple of (date, confidence, source)
        """
        # Try metadata first
        if metadata:
            for key in ["date", "created", "modified", "revision_date"]:
                if key in metadata:
                    try:
                        date = self._parse_date_value(metadata[key])
                        if date:
                            return date, 0.9, DateSource.METADATA
                    except (ValueError, TypeError):
                        pass

        # Try content patterns
        for pattern, fmt in self.DATE_PATTERNS:
            match = re.search(pattern, text[:2000], re.IGNORECASE)
            if match:
                try:
                    if fmt:
                        date_str = match.group(0)
                        date = datetime.strptime(date_str, fmt)
                    else:
                        # Written format
                        month_name = match.group(1).lower()
                        day = int(match.group(2))
                        year = int(match.group(3))
                        month = self.MONTH_MAP.get(month_name, 1)
                        date = datetime(year, month, day)

                    return date, 0.7, DateSource.CONTENT
                except (ValueError, IndexError):
                    continue

        return None, 0.0, DateSource.UNKNOWN

    def _parse_date_value(self, value: Any) -> datetime | None:
        """Parse a date from various formats."""
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y"]:
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        return None


# =============================================================================
# HAIKU VALIDATOR
# =============================================================================

class HaikuValidator:
    """
    Validates derivation using Claude Haiku.

    Uses L0_DERIVATION_VALIDATION_V1 prompt.
    """

    def __init__(self, client: BaseClaudeClient | None = None):
        self.client = client

    def validate_derivation(
        self,
        features: DocFeatures,
        derived_types: list[EvidenceType],
        content_sample: str,
    ) -> DerivationValidationResponse:
        """
        Validate evidence type derivation with Haiku.

        Args:
            features: Extracted DocFeatures
            derived_types: Rule-derived evidence types
            content_sample: Sample of document content

        Returns:
            DerivationValidationResponse
        """
        client = self.client or get_default_client()

        prompt = L0_DERIVATION_VALIDATION_V1.format(
            doc_id=features.doc_id,
            doc_type=features.doc_type.value,
            has_measurements=features.flags.has_measurements,
            has_test_conditions=features.flags.has_test_conditions,
            has_spec_references=features.flags.has_spec_references,
            has_tables=features.flags.has_tables,
            has_figures=features.flags.has_figures,
            entities=features.entities.model_dump(),
            content_sample=content_sample[:500],
            derived_types=[t.value for t in derived_types],
        )

        response = client.call_json(prompt, ModelTier.HAIKU)

        if not response.parse_success:
            logger.warning(f"Haiku validation parse failed: {response.parse_error}")
            return DerivationValidationResponse(
                valid=True,  # Default to accepting rule-based derivation
                corrected_types=None,
                confidence=0.5,
                reasoning="LLM validation failed, using rule-based derivation",
            )

        data = response.data

        corrected = None
        if not data.get("valid", True) and "corrected_types" in data:
            try:
                corrected = [EvidenceType(t) for t in data["corrected_types"]]
            except (ValueError, KeyError):
                corrected = None

        return DerivationValidationResponse(
            valid=data.get("valid", True),
            corrected_types=corrected,
            confidence=data.get("confidence", 0.8),
            reasoning=data.get("reasoning", ""),
        )

    def detect_noise(
        self,
        doc_id: str,
        doc_type: DocType,
        content_sample: str,
    ) -> tuple[bool, list[str], float]:
        """
        Detect noise markers using Haiku.

        Returns:
            Tuple of (is_noise_candidate, noise_markers, confidence)
        """
        client = self.client or get_default_client()

        prompt = L0_NOISE_DETECTION_V1.format(
            doc_id=doc_id,
            doc_type=doc_type.value,
            content_sample=content_sample[:500],
        )

        response = client.call_json(prompt, ModelTier.HAIKU)

        if not response.parse_success:
            return False, [], 0.5

        data = response.data
        return (
            data.get("is_noise_candidate", False),
            data.get("noise_markers", []),
            data.get("confidence", 0.8),
        )


# =============================================================================
# FEATURE EXTRACTOR
# =============================================================================

class FeatureExtractor:
    """
    Main feature extraction pipeline.

    Orchestrates entity extraction, flag detection, derivation, and validation.
    """

    def __init__(
        self,
        entity_extractor: EntityExtractorProtocol | None = None,
        doc_type_classifier: DocTypeClassifier | None = None,
        flags_extractor: FlagsExtractor | None = None,
        date_extractor: DateExtractor | None = None,
        derivation_engine: DerivationEngine | None = None,
        haiku_validator: HaikuValidator | None = None,
        domain_scores_func: callable | None = None,
        config_hash: str = "",
    ):
        self.entity_extractor = entity_extractor or RegexEntityExtractor()
        self.doc_type_classifier = doc_type_classifier or DocTypeClassifier()
        self.flags_extractor = flags_extractor or FlagsExtractor()
        self.date_extractor = date_extractor or DateExtractor()
        self.derivation_engine = derivation_engine or create_derivation_engine()
        self.haiku_validator = haiku_validator
        self.domain_scores_func = domain_scores_func
        self.config_hash = config_hash

    def extract(
        self,
        doc: RawDocument,
        validate_with_llm: bool = True,
        detect_noise_with_llm: bool = True,
    ) -> DocFeatures:
        """
        Extract DocFeatures from a raw document.

        Args:
            doc: Raw document input
            validate_with_llm: Whether to validate derivation with Haiku
            detect_noise_with_llm: Whether to detect noise with Haiku

        Returns:
            Fully populated DocFeatures
        """
        logger.info(f"Extracting features for {doc.doc_id}")

        # 1. Classify document type
        doc_type = self.doc_type_classifier.classify(doc.content, doc.file_type)

        # 2. Extract entities
        entities = EntitySet(
            materials=self.entity_extractor.extract_materials(doc.content),
            standards=self.entity_extractor.extract_standards(doc.content),
            hazards=self.entity_extractor.extract_hazards(doc.content),
            systems=self.entity_extractor.extract_systems(doc.content),
            processes=self.entity_extractor.extract_processes(doc.content),
        )

        # 3. Extract flags
        flags = self.flags_extractor.extract(doc.content)

        # 4. Extract date
        date_value, date_confidence, date_source = self.date_extractor.extract(
            doc.content, doc.metadata
        )

        # 5. Compute domain scores (if func provided)
        domain_scores = {}
        if self.domain_scores_func:
            domain_scores = self.domain_scores_func(doc.content, entities, doc_type)

        # 6. Count references
        spec_ref_count = len(entities.standards)
        drawing_ref_count = len(re.findall(r"drawing\s+\d+|dwg[- ]\d+", doc.content, re.IGNORECASE))
        internal_ref_count = len(re.findall(r"see\s+(section|paragraph|appendix)", doc.content, re.IGNORECASE))

        # 7. Build initial features
        features = DocFeatures(
            doc_id=doc.doc_id,
            doc_hash=doc.compute_hash(),
            feature_schema_version="1.0",
            extracted_at=datetime.utcnow(),
            extractor_config_hash=self.config_hash,
            extraction_model="haiku-3.5" if validate_with_llm else "regex",
            derivation_validated=False,
            derivation_confidence=0.0,
            doc_type=doc_type,
            domain_scores=domain_scores,
            tags=[],  # Tags can be added by domain-specific logic
            entities=entities,
            flags=flags,
            derived_evidence_types=[],
            spec_ref_count=spec_ref_count,
            drawing_ref_count=drawing_ref_count,
            internal_ref_count=internal_ref_count,
            date_value=date_value,
            date_confidence=date_confidence,
            date_source=date_source,
            noise_markers=[],
        )

        # 8. Derive evidence types
        llm_validator = None
        if validate_with_llm and self.haiku_validator:
            llm_validator = lambda f, t, c: self.haiku_validator.validate_derivation(f, t, c)

        derived_types, confidence = self.derivation_engine.derive(
            features,
            doc.content_sample,
            validate_with_llm=validate_with_llm and self.haiku_validator is not None,
        )

        features.derived_evidence_types = derived_types
        features.derivation_validated = validate_with_llm and self.haiku_validator is not None
        features.derivation_confidence = confidence

        # 9. Detect noise with LLM if enabled
        if detect_noise_with_llm and self.haiku_validator:
            is_noise, noise_markers, noise_conf = self.haiku_validator.detect_noise(
                doc.doc_id, doc_type, doc.content_sample
            )
            if is_noise:
                features.flags.is_noise_candidate = True
            features.noise_markers = noise_markers

        logger.info(
            f"Extracted features for {doc.doc_id}: "
            f"type={doc_type.value}, evidence={[t.value for t in derived_types]}, "
            f"confidence={confidence:.2f}"
        )

        return features


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_feature_extractor(
    derivation_rules: list[DerivationRule] | None = None,
    taxonomy: EvidenceTaxonomy | None = None,
    claude_client: BaseClaudeClient | None = None,
    config_hash: str = "",
) -> FeatureExtractor:
    """
    Create a configured FeatureExtractor.

    Args:
        derivation_rules: Custom derivation rules (uses defaults if None)
        taxonomy: Evidence taxonomy
        claude_client: Claude client for Haiku validation
        config_hash: Config hash for traceability

    Returns:
        Configured FeatureExtractor
    """
    derivation_engine = create_derivation_engine(
        rules=derivation_rules,
        taxonomy=taxonomy,
    )

    haiku_validator = None
    if claude_client:
        haiku_validator = HaikuValidator(client=claude_client)

    return FeatureExtractor(
        derivation_engine=derivation_engine,
        haiku_validator=haiku_validator,
        config_hash=config_hash,
    )


__all__ = [
    # Input types
    "RawDocument",

    # Extractors
    "EntityExtractorProtocol",
    "RegexEntityExtractor",
    "DocTypeClassifier",
    "FlagsExtractor",
    "DateExtractor",

    # Validation
    "HaikuValidator",

    # Main extractor
    "FeatureExtractor",
    "create_feature_extractor",
]
