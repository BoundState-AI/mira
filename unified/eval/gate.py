from __future__ import annotations

from pydantic import BaseModel, Field

from unified.eval.metrics import ICMetricsSnapshot


class EvaluationGate(BaseModel):
    minimums: dict[str, float] = Field(
        default_factory=lambda: {
            "regression_pass_rate": 0.85,
            "citation_precision": 0.95,
        }
    )
    maximums: dict[str, float] = Field(
        default_factory=lambda: {
            "unsupported_claim_rate": 0.05,
            "latency_p95_ms": 10000.0,
        }
    )

    def evaluate(self, metrics: ICMetricsSnapshot) -> dict[str, object]:
        failures: list[str] = []
        for key, minimum in self.minimums.items():
            if getattr(metrics, key) < minimum:
                failures.append(f"{key}<{minimum}")
        for key, maximum in self.maximums.items():
            if getattr(metrics, key) > maximum:
                failures.append(f"{key}>{maximum}")
        return {"passed": not failures, "failures": failures}

    def enforce(self, metrics: ICMetricsSnapshot) -> None:
        result = self.evaluate(metrics)
        if not result["passed"]:
            raise ValueError(f"IC evaluation gate failed: {', '.join(result['failures'])}")

