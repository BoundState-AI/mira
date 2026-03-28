from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from unified.eval.regression import ICRegressionCorpus, RegressionReport


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95))))
    return ordered[index]


class ICMetricsSnapshot(BaseModel):
    regression_pass_rate: float = 0.0
    citation_precision: float = 0.0
    unsupported_claim_rate: float = 1.0
    latency_p95_ms: float = 0.0
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_report(cls, report: RegressionReport) -> "ICMetricsSnapshot":
        total = max(1, report.total_cases)
        citation_passes = sum(1 for result in report.results if "insufficient_citations" not in result.issues)
        unsupported_failures = sum(1 for result in report.results if "insufficient_citations" in result.issues)
        latencies = [result.latency_ms for result in report.results]
        return cls(
            regression_pass_rate=report.passed_cases / total,
            citation_precision=citation_passes / total,
            unsupported_claim_rate=unsupported_failures / total,
            latency_p95_ms=_p95(latencies),
            raw={"total_cases": report.total_cases, "passed_cases": report.passed_cases},
        )


class ICEvaluator:
    def __init__(self, corpus: ICRegressionCorpus) -> None:
        self._corpus = corpus
        self._last_report = RegressionReport()
        self._current_metrics = ICMetricsSnapshot()

    def evaluate_pipeline(self, pipeline) -> ICMetricsSnapshot:
        self._last_report = self._corpus.run(pipeline)
        self._current_metrics = ICMetricsSnapshot.from_report(self._last_report)
        return self._current_metrics

    def current_metrics(self) -> dict[str, Any]:
        return self._current_metrics.model_dump(mode="json")

    def last_report(self) -> dict[str, Any]:
        return self._last_report.model_dump(mode="json")

