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
GPTL Shadow Mode - Parallel execution for validation
=====================================================

Shadow mode runs GPTL filtering alongside normal retrieval without
affecting results. This allows validation of:
- False elimination rate
- False positive rate
- Reduction ratio
- Latency impact

Mode Types:
- strict: GPTL filters are enforced (production mode)
- shadow: GPTL runs in parallel, logs differences, uses bypass results
- bypass: GPTL is completely disabled

Shadow mode is required for Phase Gate 3->4 validation.

Compliance: SWE-032 (Data Validation), SWE-033 (Requirements Traceability)
Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from gptl.negative_selection import Candidate, ViolationReport
from gptl.schema import DocFeatures, IntentFrame

__safety_critical__: bool = True

logger = logging.getLogger(__name__)


# =============================================================================
# SHADOW COMPARISON RESULT
# =============================================================================

class DifferenceType(str, Enum):
    """Types of differences detected in shadow mode."""
    FALSE_ELIMINATION = "false_elimination"  # GPTL eliminated a relevant doc
    FALSE_INCLUSION = "false_inclusion"      # GPTL kept an irrelevant doc
    RANK_DIFFERENCE = "rank_difference"      # Different ranking order
    SCORE_DIFFERENCE = "score_difference"    # Significant score difference


@dataclass
class ShadowDifference:
    """A single difference detected between shadow and bypass."""
    diff_type: DifferenceType
    doc_id: str
    description: str
    gptl_score: float | None = None
    bypass_score: float | None = None
    gptl_rank: int | None = None
    bypass_rank: int | None = None
    severity: Literal["low", "medium", "high"] = "low"


@dataclass
class ShadowComparisonResult:
    """Result of comparing shadow vs bypass execution."""
    query_id: str
    query: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    config_hash: str = ""
    domain_id: str = ""
    intent_frame_id: str | None = None

    # Bypass results (ground truth for shadow mode)
    bypass_count: int = 0
    bypass_doc_ids: list[str] = field(default_factory=list)

    # GPTL results
    gptl_count: int = 0
    gptl_doc_ids: list[str] = field(default_factory=list)
    gptl_eliminated_ids: list[str] = field(default_factory=list)

    # Comparison metrics
    overlap_count: int = 0
    false_eliminations: int = 0
    false_inclusions: int = 0
    rank_correlation: float = 0.0

    # Violation report from GPTL
    violation_report: ViolationReport | None = None

    # Detailed differences
    differences: list[ShadowDifference] = field(default_factory=list)

    # Timing
    bypass_latency_ms: int = 0
    gptl_latency_ms: int = 0

    @property
    def reduction_ratio(self) -> float:
        """How much GPTL reduced the result set."""
        if self.bypass_count == 0:
            return 0.0
        return (self.bypass_count - self.gptl_count) / self.bypass_count

    @property
    def false_elimination_rate(self) -> float:
        """Rate of false eliminations (relevant docs eliminated)."""
        if self.bypass_count == 0:
            return 0.0
        return self.false_eliminations / self.bypass_count

    @property
    def has_critical_differences(self) -> bool:
        """Check if any high-severity differences exist."""
        return any(d.severity == "high" for d in self.differences)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "query_id": self.query_id,
            "query": self.query,
            "timestamp": self.timestamp.isoformat(),
            "config_hash": self.config_hash,
            "domain_id": self.domain_id,
            "intent_frame_id": self.intent_frame_id,
            "bypass_count": self.bypass_count,
            "gptl_count": self.gptl_count,
            "overlap_count": self.overlap_count,
            "reduction_ratio": self.reduction_ratio,
            "false_eliminations": self.false_eliminations,
            "false_elimination_rate": self.false_elimination_rate,
            "false_inclusions": self.false_inclusions,
            "rank_correlation": self.rank_correlation,
            "bypass_latency_ms": self.bypass_latency_ms,
            "gptl_latency_ms": self.gptl_latency_ms,
            "has_critical_differences": self.has_critical_differences,
            "differences": [
                {
                    "type": d.diff_type.value,
                    "doc_id": d.doc_id,
                    "description": d.description,
                    "severity": d.severity,
                }
                for d in self.differences
            ],
        }


# =============================================================================
# SHADOW COMPARATOR
# =============================================================================

class ShadowComparator:
    """
    Compares GPTL (shadow) results against bypass (ground truth) results.

    Used to validate GPTL before enabling strict mode.
    """

    def __init__(
        self,
        relevance_threshold: float = 0.5,
        rank_difference_threshold: int = 5,
        score_difference_threshold: float = 0.2,
    ):
        """
        Initialize comparator.

        Args:
            relevance_threshold: Bypass score threshold to consider "relevant"
            rank_difference_threshold: Rank diff to flag as significant
            score_difference_threshold: Score diff to flag as significant
        """
        self.relevance_threshold = relevance_threshold
        self.rank_difference_threshold = rank_difference_threshold
        self.score_difference_threshold = score_difference_threshold

    def compare(
        self,
        query_id: str,
        query: str,
        bypass_results: list[tuple[str, float]],  # (doc_id, score)
        gptl_survivors: list[Candidate],
        gptl_eliminated: list[Candidate],
        violation_report: ViolationReport,
        config_hash: str = "",
        domain_id: str = "",
        intent_frame: IntentFrame | None = None,
        bypass_latency_ms: int = 0,
        gptl_latency_ms: int = 0,
    ) -> ShadowComparisonResult:
        """
        Compare bypass results against GPTL results.

        Args:
            query_id: Query identifier
            query: Query text
            bypass_results: Bypass results as (doc_id, score) tuples
            gptl_survivors: GPTL survivor candidates
            gptl_eliminated: GPTL eliminated candidates
            violation_report: GPTL violation report
            config_hash: Config hash for traceability
            domain_id: Domain identifier
            intent_frame: Intent frame if available
            bypass_latency_ms: Bypass execution time
            gptl_latency_ms: GPTL execution time

        Returns:
            ShadowComparisonResult with detailed comparison
        """
        # Build lookup maps
        bypass_scores = {doc_id: score for doc_id, score in bypass_results}
        bypass_ranks = {doc_id: i for i, (doc_id, _) in enumerate(bypass_results)}

        gptl_survivor_ids = set(c.doc_id for c in gptl_survivors)
        gptl_eliminated_ids = set(c.doc_id for c in gptl_eliminated)
        gptl_scores = {c.doc_id: c.current_score for c in gptl_survivors}
        gptl_ranks = {c.doc_id: i for i, c in enumerate(gptl_survivors)}

        # Initialize result
        result = ShadowComparisonResult(
            query_id=query_id,
            query=query,
            config_hash=config_hash,
            domain_id=domain_id,
            intent_frame_id=intent_frame.frame_id if intent_frame else None,
            bypass_count=len(bypass_results),
            bypass_doc_ids=[doc_id for doc_id, _ in bypass_results],
            gptl_count=len(gptl_survivors),
            gptl_doc_ids=[c.doc_id for c in gptl_survivors],
            gptl_eliminated_ids=list(gptl_eliminated_ids),
            violation_report=violation_report,
            bypass_latency_ms=bypass_latency_ms,
            gptl_latency_ms=gptl_latency_ms,
        )

        # Calculate overlap
        result.overlap_count = len(gptl_survivor_ids & set(bypass_scores.keys()))

        # Detect false eliminations
        # (docs in bypass results that GPTL eliminated)
        for doc_id, score in bypass_results:
            if doc_id in gptl_eliminated_ids:
                # This is a potential false elimination
                # Check if it was "relevant" (high bypass score)
                if score >= self.relevance_threshold:
                    result.false_eliminations += 1
                    severity = "high" if score >= 0.8 else "medium"
                    result.differences.append(ShadowDifference(
                        diff_type=DifferenceType.FALSE_ELIMINATION,
                        doc_id=doc_id,
                        description=f"Eliminated doc with bypass score {score:.3f}",
                        bypass_score=score,
                        bypass_rank=bypass_ranks.get(doc_id),
                        severity=severity,
                    ))

        # Detect false inclusions (less critical)
        # (docs in GPTL survivors not in bypass results)
        for candidate in gptl_survivors:
            if candidate.doc_id not in bypass_scores:
                result.false_inclusions += 1
                result.differences.append(ShadowDifference(
                    diff_type=DifferenceType.FALSE_INCLUSION,
                    doc_id=candidate.doc_id,
                    description="GPTL included doc not in bypass results",
                    gptl_score=candidate.current_score,
                    gptl_rank=gptl_ranks.get(candidate.doc_id),
                    severity="low",
                ))

        # Detect significant rank differences
        for doc_id in gptl_survivor_ids & set(bypass_scores.keys()):
            bypass_rank = bypass_ranks.get(doc_id, -1)
            gptl_rank = gptl_ranks.get(doc_id, -1)

            if bypass_rank >= 0 and gptl_rank >= 0:
                rank_diff = abs(bypass_rank - gptl_rank)
                if rank_diff >= self.rank_difference_threshold:
                    result.differences.append(ShadowDifference(
                        diff_type=DifferenceType.RANK_DIFFERENCE,
                        doc_id=doc_id,
                        description=f"Rank changed from {bypass_rank} to {gptl_rank}",
                        bypass_rank=bypass_rank,
                        gptl_rank=gptl_rank,
                        severity="low" if rank_diff < 10 else "medium",
                    ))

        # Calculate rank correlation (Spearman-like)
        result.rank_correlation = self._calculate_rank_correlation(
            bypass_ranks, gptl_ranks, gptl_survivor_ids
        )

        return result

    def _calculate_rank_correlation(
        self,
        bypass_ranks: dict[str, int],
        gptl_ranks: dict[str, int],
        common_ids: set[str],
    ) -> float:
        """Calculate Spearman-like rank correlation for common documents."""
        if len(common_ids) < 2:
            return 1.0 if len(common_ids) == 1 else 0.0

        common_docs = [doc_id for doc_id in common_ids if doc_id in bypass_ranks]
        if len(common_docs) < 2:
            return 0.0

        # Calculate rank differences
        d_squared_sum = sum(
            (bypass_ranks.get(doc_id, 0) - gptl_ranks.get(doc_id, 0)) ** 2
            for doc_id in common_docs
        )

        n = len(common_docs)
        # Spearman correlation formula
        rho = 1 - (6 * d_squared_sum) / (n * (n * n - 1))
        return max(-1.0, min(1.0, rho))


# =============================================================================
# SHADOW LOGGER
# =============================================================================

class ShadowLogger:
    """
    Logs shadow comparison results for analysis.

    Writes JSONL files for later analysis of false elimination rates.
    """

    def __init__(
        self,
        log_dir: Path | str = "logs/shadow",
        max_file_size_mb: int = 100,
    ):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.max_file_size = max_file_size_mb * 1024 * 1024
        self._current_file: Path | None = None
        self._current_size = 0

    def log(self, result: ShadowComparisonResult):
        """Log a shadow comparison result."""
        # Ensure we have a current file
        if self._current_file is None or self._current_size >= self.max_file_size:
            self._rotate_file()

        # Write JSONL
        line = json.dumps(result.to_dict()) + "\n"
        with open(self._current_file, "a", encoding="utf-8") as f:
            f.write(line)

        self._current_size += len(line.encode())

        # Log summary
        if result.false_eliminations > 0:
            logger.warning(
                f"Shadow mode: {result.false_eliminations} false eliminations "
                f"(rate: {result.false_elimination_rate:.1%}) for query {result.query_id}"
            )
        else:
            logger.info(
                f"Shadow mode: reduction={result.reduction_ratio:.1%}, "
                f"correlation={result.rank_correlation:.2f} for query {result.query_id}"
            )

    def _rotate_file(self):
        """Rotate to a new log file."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        self._current_file = self.log_dir / f"shadow_{timestamp}.jsonl"
        self._current_size = 0
        logger.info(f"Shadow log rotated to {self._current_file}")


# =============================================================================
# SHADOW MODE CONTROLLER
# =============================================================================

class ShadowModeController:
    """
    Controls shadow mode execution.

    Coordinates running GPTL in parallel with bypass and comparing results.
    """

    def __init__(
        self,
        comparator: ShadowComparator | None = None,
        shadow_logger: ShadowLogger | None = None,
    ):
        self.comparator = comparator or ShadowComparator()
        self.logger = shadow_logger or ShadowLogger()

        # Aggregate metrics
        self._total_queries = 0
        self._total_false_eliminations = 0
        self._false_elimination_rates: list[float] = []

    def record_shadow_run(
        self,
        query_id: str,
        query: str,
        bypass_results: list[tuple[str, float]],
        gptl_survivors: list[Candidate],
        gptl_eliminated: list[Candidate],
        violation_report: ViolationReport,
        **kwargs,
    ) -> ShadowComparisonResult:
        """
        Record a shadow mode run.

        Args:
            query_id: Query identifier
            query: Query text
            bypass_results: Bypass results
            gptl_survivors: GPTL survivors
            gptl_eliminated: GPTL eliminated
            violation_report: GPTL violation report
            **kwargs: Additional comparison args

        Returns:
            Comparison result
        """
        result = self.comparator.compare(
            query_id=query_id,
            query=query,
            bypass_results=bypass_results,
            gptl_survivors=gptl_survivors,
            gptl_eliminated=gptl_eliminated,
            violation_report=violation_report,
            **kwargs,
        )

        # Log result
        self.logger.log(result)

        # Update aggregate metrics
        self._total_queries += 1
        self._total_false_eliminations += result.false_eliminations
        self._false_elimination_rates.append(result.false_elimination_rate)

        return result

    def get_aggregate_metrics(self) -> dict[str, Any]:
        """Get aggregate shadow mode metrics."""
        if self._total_queries == 0:
            return {"total_queries": 0}

        avg_false_elim_rate = (
            sum(self._false_elimination_rates) / len(self._false_elimination_rates)
            if self._false_elimination_rates else 0.0
        )

        return {
            "total_queries": self._total_queries,
            "total_false_eliminations": self._total_false_eliminations,
            "avg_false_elimination_rate": avg_false_elim_rate,
            "max_false_elimination_rate": max(self._false_elimination_rates) if self._false_elimination_rates else 0.0,
            "queries_with_false_eliminations": sum(1 for r in self._false_elimination_rates if r > 0),
        }

    def is_ready_for_strict_mode(self, threshold: float = 0.02) -> tuple[bool, str]:
        """
        Check if shadow mode results indicate readiness for strict mode.

        Gate requirement: false elimination rate < 2%

        Args:
            threshold: Maximum acceptable false elimination rate

        Returns:
            Tuple of (ready, reason)
        """
        metrics = self.get_aggregate_metrics()

        if metrics["total_queries"] < 100:
            return False, f"Insufficient queries: {metrics['total_queries']} < 100"

        if metrics["avg_false_elimination_rate"] > threshold:
            return False, (
                f"False elimination rate too high: "
                f"{metrics['avg_false_elimination_rate']:.1%} > {threshold:.1%}"
            )

        return True, "Shadow mode validation passed"


# =============================================================================
# FACTORY
# =============================================================================

def create_shadow_controller(
    log_dir: str | Path = "logs/shadow",
) -> ShadowModeController:
    """Create a configured ShadowModeController."""
    return ShadowModeController(
        comparator=ShadowComparator(),
        shadow_logger=ShadowLogger(log_dir=log_dir),
    )


__all__ = [
    # Types
    "DifferenceType",
    "ShadowDifference",
    "ShadowComparisonResult",

    # Comparator
    "ShadowComparator",

    # Logger
    "ShadowLogger",

    # Controller
    "ShadowModeController",

    # Factory
    "create_shadow_controller",
]
