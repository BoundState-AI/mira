#!/usr/bin/env python3
"""
Module: Discovery
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, Field


@dataclass
class CorpusProfile:
    """Aggregated profile of document corpus from discovery phase.

    Used to inform triage with corpus-specific vocabulary and patterns.
    """
    document_types: dict[str, int] = field(default_factory=dict)
    entity_patterns: dict[str, list[str]] = field(default_factory=dict)
    vocabulary: dict[str, int] = field(default_factory=dict)
    form_numbers: dict[str, int] = field(default_factory=dict)
    date_range: tuple[str | None, str | None] = (None, None)
    condition_breakdown: dict[str, int] = field(default_factory=dict)
    total_pages: int = 0


class DiscoveryResult(BaseModel):
    """Single page discovery observation.

    Raw observations without normalization - capture exactly what's seen.
    """
    page: int
    document_type: str
    era_estimate: str | None = None              # e.g., "1980s", "unknown"
    entities_found: dict[str, list[str]] = Field(default_factory=dict)
    vocabulary_notes: list[str] = Field(default_factory=list)
    form_number: str | None = None
    condition_notes: list[str] = Field(default_factory=list)
    content_summary: str | None = None


class DiscoveryAggregator:
    """Aggregate discovery results into corpus profile.

    Implements the discovery workflow:
    1. OBSERVE: Haiku reads each page - "What do you see?"
    2. AGGREGATE: Collect patterns, count frequencies
    3. BUILD: Create corpus-specific config for triage/extraction
    """

    # Common English stop words to filter from vocabulary
    STOP_WORDS = {
        "the", "and", "or", "is", "was", "were", "are", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "must", "shall", "can", "need", "dare",
        "ought", "used", "to", "of", "in", "for", "on", "with", "at", "by",
        "from", "as", "into", "through", "during", "before", "after", "above",
        "below", "between", "under", "again", "further", "then", "once", "here",
        "there", "when", "where", "why", "how", "all", "each", "few", "more",
        "most", "other", "some", "such", "no", "nor", "not", "only", "own",
        "same", "so", "than", "too", "very", "just", "also", "now", "this",
        "that", "these", "those", "what", "which", "who", "whom", "whose",
        "page", "date", "name", "number", "see", "per", "item", "total",
    }

    def __init__(self):
        self.document_types: Counter = Counter()
        self.entities: dict[str, list[str]] = defaultdict(list)
        self.vocabulary: Counter = Counter()
        self.form_numbers: Counter = Counter()
        self.dates: list[str] = []
        self.conditions: Counter = Counter()
        self.total_pages: int = 0

    def add_discovery_result(self, result: dict | DiscoveryResult) -> None:
        """Add single page discovery result to aggregation.

        CRITICAL: Supports incremental processing - call after each page.

        Args:
            result: Discovery result (dict from LLM or DiscoveryResult model)
        """
        if isinstance(result, DiscoveryResult):
            result = result.model_dump()

        self.total_pages += 1

        # Document type
        doc_type = result.get("document_type", "unknown")
        self.document_types[doc_type] += 1

        # Entities
        entities = result.get("entities_found", {})
        for entity_type, values in entities.items():
            if isinstance(values, list):
                self.entities[entity_type].extend(values)

        # Vocabulary
        vocab_notes = result.get("vocabulary_notes", [])
        for term in vocab_notes:
            if isinstance(term, str):
                normalized = term.lower().strip()
                if normalized and normalized not in self.STOP_WORDS:
                    self.vocabulary[normalized] += 1

        # Form numbers
        form_num = result.get("form_number")
        if form_num:
            self.form_numbers[form_num] += 1

        # Dates
        dates = entities.get("dates", [])
        if isinstance(dates, list):
            self.dates.extend(dates)

        # Conditions
        conditions = result.get("condition_notes", [])
        for cond in conditions:
            if isinstance(cond, str):
                self.conditions[cond.lower()] += 1

    def build_profile(self) -> CorpusProfile:
        """Build final corpus profile from aggregated data.

        Returns:
            CorpusProfile with document types, entity patterns, vocabulary
        """
        # Extract patterns from entities
        entity_patterns = {}
        for entity_type, values in self.entities.items():
            # Get unique values, sorted by frequency
            counter = Counter(values)
            entity_patterns[entity_type] = [v for v, _ in counter.most_common(100)]

        return CorpusProfile(
            document_types=dict(self.document_types.most_common()),
            entity_patterns=entity_patterns,
            vocabulary=dict(self.vocabulary.most_common(500)),
            form_numbers=dict(self.form_numbers.most_common()),
            date_range=self._extract_date_range(),
            condition_breakdown=dict(self.conditions.most_common()),
            total_pages=self.total_pages,
        )

    def _extract_date_range(self) -> tuple[str | None, str | None]:
        """Extract earliest and latest dates from collected dates.

        Returns:
            Tuple of (earliest_date, latest_date) or (None, None)
        """
        if not self.dates:
            return (None, None)
        # Basic min/max - could be enhanced with proper date parsing
        return (min(self.dates), max(self.dates))


class BatchDiscoveryState(BaseModel):
    """State for incremental batch discovery processing.

    CRITICAL: Enables saving progress after each page.
    The Wasted Run of 2025-12-22: Lost all progress on interrupt.
    Always save incrementally in long-running processes.
    """
    batch_id: str
    total_pages: int = 0
    pages_discovered: int = 0
    results: list[DiscoveryResult] = Field(default_factory=list)
    profile: CorpusProfile | None = None
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    processing_complete: bool = False

    def add_result(self, result: DiscoveryResult) -> None:
        """Add discovery result and increment counter.

        CRITICAL: Call save after this to preserve progress.
        """
        self.results.append(result)
        self.pages_discovered = len(self.results)
