from __future__ import annotations

from unified.canonical_store import CanonicalStore
from unified.evidence.doc_provider import DocumentEvidenceProvider
from unified.eval.gate import EvaluationGate
from unified.eval.metrics import ICEvaluator, ICMetricsSnapshot
from unified.eval.regression import ICRegressionCorpus, RegressionCase
from unified.pipeline.pipeline import UnifiedPipeline
from unified.schema import ICChunk, ICDocument, QueryRequest, QuerySource


def test_regression_corpus_runs_pipeline_and_computes_metrics() -> None:
    store = CanonicalStore()
    store.insert_document(
        ICDocument(
            doc_id="doc-1",
            doc_hash="hash-1",
            source_path="/tmp/doc-1.pdf",
            source_type="pdf",
        )
    )
    store.insert_chunk(
        ICChunk(
            chunk_id="chunk-1",
            doc_id="doc-1",
            content_text="Titanium shall have strength of 42 MPa.",
            content_type="text",
            extraction_method="manual",
            extraction_confidence=1.0,
        )
    )
    pipeline = UnifiedPipeline(doc_provider=DocumentEvidenceProvider(store=store))
    evaluator = ICEvaluator(
        ICRegressionCorpus(
            cases=[
                RegressionCase(
                    case_id="R-001",
                    request=QueryRequest(query="Titanium strength", source=QuerySource.DOCS),
                    required_substrings=["strongest support"],
                    min_citations=1,
                )
            ]
        )
    )

    metrics = evaluator.evaluate_pipeline(pipeline)

    assert metrics.regression_pass_rate == 1.0
    assert metrics.citation_precision == 1.0


def test_evaluation_gate_blocks_failing_metrics() -> None:
    gate = EvaluationGate()
    failing = ICMetricsSnapshot(
        regression_pass_rate=0.2,
        citation_precision=0.5,
        unsupported_claim_rate=0.2,
        latency_p95_ms=15000.0,
    )

    result = gate.evaluate(failing)
    assert result["passed"] is False

