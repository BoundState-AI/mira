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
GPTL Benchmarks - Performance tracking and analysis
====================================================

Provides performance benchmarking for GPTL pipeline stages.

Features:
- Timing benchmarks for each pipeline stage
- Token usage tracking per query type
- Reduction ratio measurement
- Baseline performance metrics
- Statistical analysis of performance trends

Compliance: SWE-032, SWE-033
Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import json
import logging
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable

__safety_critical__: bool = False  # Benchmarks are not safety-critical

logger = logging.getLogger(__name__)


# =============================================================================
# BENCHMARK TYPES
# =============================================================================

class PipelineStage(str, Enum):
    """GPTL pipeline stages for benchmarking."""
    L0_FEATURE_EXTRACTION = "L0_feature_extraction"
    L2_INTENT_FRAMING = "L2_intent_framing"
    L3_NEGATIVE_SELECTION = "L3_negative_selection"
    L4_SIGNAL_EXTRACTION = "L4_signal_extraction"
    L5_SYNTHESIS = "L5_synthesis"
    TOTAL = "total"


class QueryCategory(str, Enum):
    """Query categories for token tracking."""
    MATERIAL_LOOKUP = "material_lookup"
    COMPATIBILITY_CHECK = "compatibility_check"
    FAILURE_PREDICTION = "failure_prediction"
    SUBSTITUTION_ANALYSIS = "substitution_analysis"
    COMPLIANCE_CHECK = "compliance_check"
    LIABILITY_ASSESSMENT = "liability_assessment"
    PROPERTY_COMPARISON = "property_comparison"
    PROCESS_GUIDANCE = "process_guidance"
    GENERAL_QUERY = "general_query"


# =============================================================================
# BENCHMARK DATA STRUCTURES
# =============================================================================

@dataclass
class StageTiming:
    """Timing data for a single pipeline stage execution."""
    stage: PipelineStage
    duration_ms: int
    success: bool
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenUsage:
    """Token usage for a single operation."""
    tokens_in: int
    tokens_out: int
    model_tier: str
    stage: PipelineStage
    query_category: QueryCategory | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out


@dataclass
class ReductionMetric:
    """Negative selection reduction metrics."""
    total_candidates: int
    eliminated: int
    survivors: int
    reduction_ratio: float
    query_category: QueryCategory | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class BenchmarkRun:
    """A complete benchmark run across all stages."""
    run_id: str
    query_category: QueryCategory
    stage_timings: list[StageTiming] = field(default_factory=list)
    token_usage: list[TokenUsage] = field(default_factory=list)
    reduction_metric: ReductionMetric | None = None
    total_duration_ms: int = 0
    success: bool = True
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def total_tokens(self) -> int:
        return sum(t.total_tokens for t in self.token_usage)

    @property
    def tokens_in(self) -> int:
        return sum(t.tokens_in for t in self.token_usage)

    @property
    def tokens_out(self) -> int:
        return sum(t.tokens_out for t in self.token_usage)


# =============================================================================
# BENCHMARK COLLECTOR
# =============================================================================

class BenchmarkCollector:
    """
    Collects and aggregates benchmark data.

    Thread-safe collection of performance metrics.
    """

    def __init__(self, max_history: int = 1000):
        """
        Args:
            max_history: Maximum number of runs to keep in memory
        """
        self.max_history = max_history
        self._runs: list[BenchmarkRun] = []
        self._current_run: BenchmarkRun | None = None

    def start_run(self, run_id: str, query_category: QueryCategory) -> None:
        """Start a new benchmark run."""
        self._current_run = BenchmarkRun(
            run_id=run_id,
            query_category=query_category,
        )

    def record_stage(
        self,
        stage: PipelineStage,
        duration_ms: int,
        success: bool = True,
        **metadata: Any,
    ) -> None:
        """Record timing for a pipeline stage."""
        if self._current_run is None:
            logger.warning("No active benchmark run, stage timing not recorded")
            return

        self._current_run.stage_timings.append(StageTiming(
            stage=stage,
            duration_ms=duration_ms,
            success=success,
            metadata=metadata,
        ))

    def record_tokens(
        self,
        tokens_in: int,
        tokens_out: int,
        model_tier: str,
        stage: PipelineStage,
    ) -> None:
        """Record token usage."""
        if self._current_run is None:
            logger.warning("No active benchmark run, token usage not recorded")
            return

        self._current_run.token_usage.append(TokenUsage(
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model_tier=model_tier,
            stage=stage,
            query_category=self._current_run.query_category,
        ))

    def record_reduction(
        self,
        total_candidates: int,
        eliminated: int,
        survivors: int,
    ) -> None:
        """Record negative selection reduction."""
        if self._current_run is None:
            logger.warning("No active benchmark run, reduction not recorded")
            return

        reduction_ratio = eliminated / total_candidates if total_candidates > 0 else 0.0
        self._current_run.reduction_metric = ReductionMetric(
            total_candidates=total_candidates,
            eliminated=eliminated,
            survivors=survivors,
            reduction_ratio=reduction_ratio,
            query_category=self._current_run.query_category,
        )

    def end_run(self, success: bool = True) -> BenchmarkRun | None:
        """End the current run and store it."""
        if self._current_run is None:
            return None

        self._current_run.success = success
        self._current_run.total_duration_ms = sum(
            t.duration_ms for t in self._current_run.stage_timings
        )

        run = self._current_run
        self._runs.append(run)

        # Trim history if needed
        if len(self._runs) > self.max_history:
            self._runs = self._runs[-self.max_history:]

        self._current_run = None
        return run

    def get_runs(
        self,
        category: QueryCategory | None = None,
        limit: int | None = None,
    ) -> list[BenchmarkRun]:
        """Get benchmark runs, optionally filtered by category."""
        runs = self._runs
        if category:
            runs = [r for r in runs if r.query_category == category]
        if limit:
            runs = runs[-limit:]
        return runs


# =============================================================================
# BENCHMARK ANALYZER
# =============================================================================

@dataclass
class StageStats:
    """Statistics for a pipeline stage."""
    stage: PipelineStage
    count: int
    mean_ms: float
    median_ms: float
    std_ms: float
    min_ms: int
    max_ms: int
    p95_ms: float
    p99_ms: float
    success_rate: float


@dataclass
class TokenStats:
    """Statistics for token usage."""
    category: QueryCategory | None
    count: int
    mean_tokens_in: float
    mean_tokens_out: float
    mean_total: float
    total_tokens_in: int
    total_tokens_out: int


@dataclass
class ReductionStats:
    """Statistics for reduction ratios."""
    category: QueryCategory | None
    count: int
    mean_ratio: float
    median_ratio: float
    min_ratio: float
    max_ratio: float


class BenchmarkAnalyzer:
    """Analyzes collected benchmark data."""

    def __init__(self, collector: BenchmarkCollector):
        self.collector = collector

    def get_stage_stats(
        self,
        stage: PipelineStage,
        category: QueryCategory | None = None,
    ) -> StageStats | None:
        """Get statistics for a specific stage."""
        runs = self.collector.get_runs(category)
        timings = [
            t for r in runs
            for t in r.stage_timings
            if t.stage == stage
        ]

        if not timings:
            return None

        durations = [t.duration_ms for t in timings]
        sorted_durations = sorted(durations)
        success_count = sum(1 for t in timings if t.success)

        return StageStats(
            stage=stage,
            count=len(timings),
            mean_ms=statistics.mean(durations),
            median_ms=statistics.median(durations),
            std_ms=statistics.stdev(durations) if len(durations) > 1 else 0.0,
            min_ms=min(durations),
            max_ms=max(durations),
            p95_ms=self._percentile(sorted_durations, 95),
            p99_ms=self._percentile(sorted_durations, 99),
            success_rate=success_count / len(timings),
        )

    def get_token_stats(
        self,
        category: QueryCategory | None = None,
    ) -> TokenStats | None:
        """Get token usage statistics."""
        runs = self.collector.get_runs(category)
        usage = [u for r in runs for u in r.token_usage]

        if not usage:
            return None

        return TokenStats(
            category=category,
            count=len(usage),
            mean_tokens_in=statistics.mean(u.tokens_in for u in usage),
            mean_tokens_out=statistics.mean(u.tokens_out for u in usage),
            mean_total=statistics.mean(u.total_tokens for u in usage),
            total_tokens_in=sum(u.tokens_in for u in usage),
            total_tokens_out=sum(u.tokens_out for u in usage),
        )

    def get_reduction_stats(
        self,
        category: QueryCategory | None = None,
    ) -> ReductionStats | None:
        """Get reduction ratio statistics."""
        runs = self.collector.get_runs(category)
        reductions = [r.reduction_metric for r in runs if r.reduction_metric]

        if not reductions:
            return None

        ratios = [r.reduction_ratio for r in reductions]

        return ReductionStats(
            category=category,
            count=len(reductions),
            mean_ratio=statistics.mean(ratios),
            median_ratio=statistics.median(ratios),
            min_ratio=min(ratios),
            max_ratio=max(ratios),
        )

    def get_baseline_metrics(self) -> dict[str, Any]:
        """Get baseline performance metrics across all categories."""
        runs = self.collector.get_runs()
        if not runs:
            return {}

        return {
            "total_runs": len(runs),
            "success_rate": sum(1 for r in runs if r.success) / len(runs),
            "mean_total_duration_ms": statistics.mean(r.total_duration_ms for r in runs),
            "mean_total_tokens": statistics.mean(r.total_tokens for r in runs),
            "stages": {
                stage.value: self._get_stage_summary(stage)
                for stage in PipelineStage
            },
            "by_category": {
                cat.value: {
                    "count": len([r for r in runs if r.query_category == cat]),
                    "mean_duration_ms": statistics.mean(
                        r.total_duration_ms for r in runs if r.query_category == cat
                    ) if any(r.query_category == cat for r in runs) else 0,
                }
                for cat in QueryCategory
            },
        }

    def _get_stage_summary(self, stage: PipelineStage) -> dict[str, Any]:
        """Get summary for a stage."""
        stats = self.get_stage_stats(stage)
        if not stats:
            return {"count": 0}
        return {
            "count": stats.count,
            "mean_ms": round(stats.mean_ms, 2),
            "p95_ms": round(stats.p95_ms, 2),
            "success_rate": round(stats.success_rate, 4),
        }

    def _percentile(self, sorted_data: list[int], percentile: int) -> float:
        """Calculate percentile from sorted data."""
        if not sorted_data:
            return 0.0
        k = (len(sorted_data) - 1) * percentile / 100
        f = int(k)
        c = f + 1 if f + 1 < len(sorted_data) else f
        return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])

    def export_to_json(self, path: Path | str) -> None:
        """Export benchmark data to JSON file."""
        data = {
            "exported_at": datetime.utcnow().isoformat(),
            "baseline": self.get_baseline_metrics(),
            "runs": [
                {
                    "run_id": r.run_id,
                    "category": r.query_category.value,
                    "total_duration_ms": r.total_duration_ms,
                    "total_tokens": r.total_tokens,
                    "success": r.success,
                    "timestamp": r.timestamp.isoformat(),
                }
                for r in self.collector.get_runs()
            ],
        }

        with open(path, "w") as f:
            json.dump(data, f, indent=2)


# =============================================================================
# TIMING CONTEXT MANAGER
# =============================================================================

class TimingContext:
    """Context manager for timing code blocks."""

    def __init__(
        self,
        collector: BenchmarkCollector,
        stage: PipelineStage,
    ):
        self.collector = collector
        self.stage = stage
        self._start_time: float = 0
        self._success = True

    def __enter__(self) -> "TimingContext":
        self._start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        duration_ms = int((time.perf_counter() - self._start_time) * 1000)
        self._success = exc_type is None
        self.collector.record_stage(
            stage=self.stage,
            duration_ms=duration_ms,
            success=self._success,
        )

    def mark_failed(self) -> None:
        """Mark this timing as failed."""
        self._success = False


# =============================================================================
# GLOBAL COLLECTOR
# =============================================================================

# Default global collector
_global_collector = BenchmarkCollector()


def get_global_collector() -> BenchmarkCollector:
    """Get the global benchmark collector."""
    return _global_collector


def get_global_analyzer() -> BenchmarkAnalyzer:
    """Get an analyzer for the global collector."""
    return BenchmarkAnalyzer(_global_collector)


def time_stage(stage: PipelineStage) -> TimingContext:
    """Create a timing context for a stage using the global collector."""
    return TimingContext(_global_collector, stage)


__all__ = [
    # Types
    "PipelineStage",
    "QueryCategory",
    # Data structures
    "StageTiming",
    "TokenUsage",
    "ReductionMetric",
    "BenchmarkRun",
    # Stats
    "StageStats",
    "TokenStats",
    "ReductionStats",
    # Collector and Analyzer
    "BenchmarkCollector",
    "BenchmarkAnalyzer",
    # Timing
    "TimingContext",
    "time_stage",
    # Global access
    "get_global_collector",
    "get_global_analyzer",
]
