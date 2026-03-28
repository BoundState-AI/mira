from __future__ import annotations

import time
from datetime import datetime

from pydantic import BaseModel, Field

from unified.schema import QueryRequest


class RegressionCase(BaseModel):
    case_id: str
    request: QueryRequest
    required_substrings: list[str] = Field(default_factory=list)
    min_citations: int = 0
    max_conflicts: int | None = None


class RegressionResult(BaseModel):
    case_id: str
    passed: bool
    latency_ms: float
    issues: list[str] = Field(default_factory=list)
    response: dict = Field(default_factory=dict)


class RegressionReport(BaseModel):
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    total_cases: int = 0
    passed_cases: int = 0
    results: list[RegressionResult] = Field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return (self.passed_cases / self.total_cases) if self.total_cases else 0.0


class ICRegressionCorpus(BaseModel):
    cases: list[RegressionCase] = Field(default_factory=list)

    def run(self, pipeline) -> RegressionReport:
        results: list[RegressionResult] = []
        passed_cases = 0

        for case in self.cases:
            started = time.perf_counter()
            response = pipeline.query(case.request)
            latency_ms = (time.perf_counter() - started) * 1000
            issues: list[str] = []

            for snippet in case.required_substrings:
                if snippet.lower() not in response.answer.lower():
                    issues.append(f"missing_substring:{snippet}")
            if len(response.citations) < case.min_citations:
                issues.append("insufficient_citations")
            if case.max_conflicts is not None and len(response.conflicts) > case.max_conflicts:
                issues.append("too_many_conflicts")

            passed = not issues
            if passed:
                passed_cases += 1

            results.append(
                RegressionResult(
                    case_id=case.case_id,
                    passed=passed,
                    latency_ms=latency_ms,
                    issues=issues,
                    response=response.model_dump(mode="json"),
                )
            )

        return RegressionReport(
            total_cases=len(self.cases),
            passed_cases=passed_cases,
            results=results,
        )

