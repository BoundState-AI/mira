#!/usr/bin/env python3
"""
Module: Schema Validation Automation
Purpose: Detects schema drift between expected and live Granta schemas for MIRA v4.

BoundState AI 2026
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, NASA-STD-8739.8B
Safety Critical: True

Implements BuildSpec REV1 Item 7: Schema Validation Automation (P1).

SchemaValidator:
    Compares the expected Schema Dictionary against live Granta metadata
    to detect field additions, removals, type changes, and probable
    renames. Classifies each change as FAIL or WARN severity and
    determines whether a FAISS rebuild or 50-query regression is required.

RegressionRunner:
    Stub for the 50-query golden regression suite. Loads golden queries
    from a JSON file and provides the interface for running regression
    against a pipeline function.

Spec Reference: BS-MIRA-V4-BUILDSPEC-001-REV1, Section 8
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from .models import (
    SchemaChange,
    SchemaChangeType,
    SchemaValidationResult,
)

logger = logging.getLogger(__name__)


# =============================================================================
# SchemaValidator
# =============================================================================


class SchemaValidator:
    """Compares expected vs. live schemas to detect drift per BuildSpec Section 8.2.

    Detection rules:
        - Fields in expected but not live: REMOVED_FIELD (FAIL)
        - Fields in live but not expected: NEW_FIELD (WARN)
        - Fields in both but type differs: TYPE_CHANGE (FAIL)
        - If a REMOVED_FIELD name is >80% similar to a NEW_FIELD name:
          reclassify as NAME_CHANGE (WARN) instead

    Result flags:
        - passed: True if no FAIL-severity changes
        - requires_faiss_rebuild: True if any REMOVED_FIELD or TYPE_CHANGE
        - requires_regression: True if any change at all (triggers 50-query regression)

    Compliance: SWE-032, NASA-STD-8739.8B
    """

    NAME_CHANGE_SIMILARITY_THRESHOLD: float = 0.80
    """Minimum character-level similarity to classify as NAME_CHANGE."""

    def compare_schemas(
        self,
        expected_schema: Dict[str, str],
        live_schema: Dict[str, str],
        schema_version: str = "unknown",
    ) -> SchemaValidationResult:
        """Compare expected Schema Dictionary against live Granta metadata.

        Args:
            expected_schema: {field_name: field_type} from Schema Dictionary.
            live_schema: {field_name: field_type} from live Granta metadata.
            schema_version: Version string for the schema being validated.

        Returns:
            SchemaValidationResult with all detected changes and flags.
        """
        logger.info(
            f"Comparing schemas: expected={len(expected_schema)} fields, "
            f"live={len(live_schema)} fields, version={schema_version}"
        )

        changes: List[SchemaChange] = []

        expected_fields = set(expected_schema.keys())
        live_fields = set(live_schema.keys())

        # Fields in expected but not live -> initially REMOVED_FIELD
        removed_fields = sorted(expected_fields - live_fields)
        # Fields in live but not expected -> initially NEW_FIELD
        added_fields = sorted(live_fields - expected_fields)
        # Fields in both -> check type
        common_fields = sorted(expected_fields & live_fields)

        # Detect type changes for common fields
        for field in common_fields:
            expected_type = expected_schema[field]
            live_type = live_schema[field]
            if expected_type != live_type:
                change = SchemaChange(
                    field_name=field,
                    change_type=SchemaChangeType.TYPE_CHANGE,
                    old_value=expected_type,
                    new_value=live_type,
                    severity=self._classify_severity(SchemaChangeType.TYPE_CHANGE),
                )
                changes.append(change)
                logger.warning(
                    f"TYPE_CHANGE: '{field}' type changed from "
                    f"'{expected_type}' to '{live_type}'"
                )

        # Detect name changes: check if removed fields match added fields
        name_change_pairs = self._detect_name_changes(
            removed_fields, added_fields
        )

        # Track which fields were reclassified as name changes
        renamed_old = {old for old, new in name_change_pairs}
        renamed_new = {new for old, new in name_change_pairs}

        # Add NAME_CHANGE entries for detected renames
        for old_name, new_name in name_change_pairs:
            change = SchemaChange(
                field_name=old_name,
                change_type=SchemaChangeType.NAME_CHANGE,
                old_value=old_name,
                new_value=new_name,
                severity=self._classify_severity(SchemaChangeType.NAME_CHANGE),
            )
            changes.append(change)
            logger.info(
                f"NAME_CHANGE: '{old_name}' -> '{new_name}' "
                f"(similarity > {self.NAME_CHANGE_SIMILARITY_THRESHOLD:.0%})"
            )

        # Remaining removed fields (not reclassified as name changes)
        for field in removed_fields:
            if field not in renamed_old:
                change = SchemaChange(
                    field_name=field,
                    change_type=SchemaChangeType.REMOVED_FIELD,
                    old_value=expected_schema[field],
                    new_value=None,
                    severity=self._classify_severity(SchemaChangeType.REMOVED_FIELD),
                )
                changes.append(change)
                logger.warning(
                    f"REMOVED_FIELD: '{field}' (type={expected_schema[field]}) "
                    f"exists in expected but not in live schema"
                )

        # Remaining added fields (not reclassified as name changes)
        for field in added_fields:
            if field not in renamed_new:
                change = SchemaChange(
                    field_name=field,
                    change_type=SchemaChangeType.NEW_FIELD,
                    old_value=None,
                    new_value=live_schema[field],
                    severity=self._classify_severity(SchemaChangeType.NEW_FIELD),
                )
                changes.append(change)
                logger.info(
                    f"NEW_FIELD: '{field}' (type={live_schema[field]}) "
                    f"exists in live but not in expected schema"
                )

        # Determine result flags
        has_fail = any(c.severity == "FAIL" for c in changes)
        has_removed = any(
            c.change_type == SchemaChangeType.REMOVED_FIELD for c in changes
        )
        has_type_change = any(
            c.change_type == SchemaChangeType.TYPE_CHANGE for c in changes
        )
        has_any_change = len(changes) > 0

        passed = not has_fail
        requires_faiss_rebuild = has_removed or has_type_change
        requires_regression = has_any_change

        result = SchemaValidationResult(
            passed=passed,
            schema_version=schema_version,
            changes=changes,
            requires_faiss_rebuild=requires_faiss_rebuild,
            requires_regression=requires_regression,
        )

        logger.info(
            f"Schema validation complete: passed={passed}, "
            f"changes={len(changes)}, "
            f"requires_faiss_rebuild={requires_faiss_rebuild}, "
            f"requires_regression={requires_regression}"
        )

        return result

    def _classify_severity(self, change_type: SchemaChangeType) -> str:
        """Map a schema change type to its severity level.

        Args:
            change_type: The type of schema change.

        Returns:
            "FAIL" for REMOVED_FIELD and TYPE_CHANGE.
            "WARN" for NEW_FIELD and NAME_CHANGE.
        """
        severity_map = {
            SchemaChangeType.REMOVED_FIELD: "FAIL",
            SchemaChangeType.TYPE_CHANGE: "FAIL",
            SchemaChangeType.NEW_FIELD: "WARN",
            SchemaChangeType.NAME_CHANGE: "WARN",
        }
        return severity_map[change_type]

    def _detect_name_changes(
        self,
        removed: List[str],
        added: List[str],
    ) -> List[Tuple[str, str]]:
        """Detect probable field renames using character-level similarity.

        For each removed field, checks similarity against all added fields.
        If similarity exceeds NAME_CHANGE_SIMILARITY_THRESHOLD (0.80),
        the pair is classified as a NAME_CHANGE rather than separate
        REMOVED_FIELD + NEW_FIELD.

        Uses a greedy matching strategy: each field can only be part of
        one name-change pair. The best match (highest similarity) is
        chosen first.

        Args:
            removed: List of field names in expected but not live.
            added: List of field names in live but not expected.

        Returns:
            List of (old_name, new_name) pairs classified as renames.
        """
        if not removed or not added:
            return []

        # Compute all pairwise similarities
        candidates: List[Tuple[float, str, str]] = []
        for old_name in removed:
            for new_name in added:
                sim = self._field_similarity(old_name, new_name)
                if sim > self.NAME_CHANGE_SIMILARITY_THRESHOLD:
                    candidates.append((sim, old_name, new_name))

        # Sort by similarity descending (greedy best-match)
        candidates.sort(key=lambda x: x[0], reverse=True)

        # Greedy assignment: each field used at most once
        used_old: set = set()
        used_new: set = set()
        pairs: List[Tuple[str, str]] = []

        for sim, old_name, new_name in candidates:
            if old_name not in used_old and new_name not in used_new:
                pairs.append((old_name, new_name))
                used_old.add(old_name)
                used_new.add(new_name)
                logger.debug(
                    f"Name change candidate: '{old_name}' -> '{new_name}' "
                    f"(similarity={sim:.3f})"
                )

        return pairs

    def _field_similarity(self, a: str, b: str) -> float:
        """Compute character-level similarity between two field names.

        Uses the Jaccard-like metric: len(intersection) / len(union)
        of the character multisets, case-insensitive.

        Args:
            a: First field name.
            b: Second field name.

        Returns:
            Similarity score in [0.0, 1.0]. Returns 0.0 if both are empty.
        """
        a_lower = a.lower()
        b_lower = b.lower()

        if not a_lower and not b_lower:
            return 0.0

        set_a = set(a_lower)
        set_b = set(b_lower)

        intersection = set_a & set_b
        union = set_a | set_b

        if not union:
            return 0.0

        similarity = len(intersection) / len(union)

        logger.debug(
            f"Field similarity '{a}' vs '{b}': {similarity:.3f} "
            f"(intersection={len(intersection)}, union={len(union)})"
        )

        return similarity


# =============================================================================
# RegressionRunner
# =============================================================================


class RegressionRunner:
    """Runs 50-query golden regression suite per BuildSpec Section 8.4.

    When a schema change is detected (requires_regression=True), this
    runner executes the golden query suite against the pipeline to
    verify that results remain consistent.

    Golden queries are loaded from a JSON file. Each query specifies:
        - query: The raw query string
        - expected_gate: Expected GateAction (PASS, CLARIFY, REFUSE)
        - expected_safety_critical: Whether query is safety-critical

    Compliance: SWE-032, NASA-STD-8739.8B
    """

    def __init__(self, golden_queries_path: Optional[str] = None) -> None:
        """Initialize RegressionRunner.

        Args:
            golden_queries_path: Path to JSON file containing golden
                queries. If None, starts with an empty query list.
        """
        self._golden_queries: List[Dict[str, Any]] = []
        self._golden_queries_path = golden_queries_path

        if golden_queries_path is not None:
            self._golden_queries = self._load_golden_queries(
                golden_queries_path
            )
            logger.info(
                f"Loaded {len(self._golden_queries)} golden queries "
                f"from '{golden_queries_path}'"
            )
        else:
            logger.info(
                "RegressionRunner initialized with no golden queries path"
            )

    @property
    def golden_queries(self) -> List[Dict[str, Any]]:
        """Return the loaded golden queries (read-only access)."""
        return list(self._golden_queries)

    def run_regression(
        self,
        pipeline_fn: Optional[Callable] = None,
        schema_version: str = "unknown",
    ) -> Dict[str, Any]:
        """Run the golden query regression suite.

        If no pipeline_fn is provided, returns a stub result that
        demonstrates the interface contract without executing queries.

        Args:
            pipeline_fn: Optional callable that accepts a query dict
                and returns a result dict with "gate_action" and
                "safety_critical" keys. If None, returns stub result.
            schema_version: Current schema version string for the result.

        Returns:
            Dict with keys:
                - passed: int -- number of queries that passed
                - failed: int -- number of queries that failed
                - total: int -- total number of golden queries
                - failures: List[Dict] -- details of each failure
                - schema_version: str -- schema version tested
        """
        total = len(self._golden_queries)

        if pipeline_fn is None:
            logger.info(
                "No pipeline_fn provided; returning stub regression result"
            )
            return {
                "passed": 0,
                "failed": 0,
                "total": total,
                "failures": [],
                "schema_version": schema_version,
            }

        logger.info(
            f"Running regression: {total} golden queries, "
            f"schema_version={schema_version}"
        )

        passed = 0
        failed = 0
        failures: List[Dict[str, Any]] = []

        for i, query_spec in enumerate(self._golden_queries):
            query_str = query_spec.get("query", "")
            expected_gate = query_spec.get("expected_gate", "")
            expected_safety = query_spec.get("expected_safety_critical", False)

            try:
                result = pipeline_fn(query_spec)

                actual_gate = result.get("gate_action", "UNKNOWN")
                actual_safety = result.get("safety_critical", None)

                gate_match = actual_gate == expected_gate
                safety_match = actual_safety == expected_safety

                if gate_match and safety_match:
                    passed += 1
                    logger.debug(
                        f"Query {i + 1}/{total} PASSED: '{query_str}'"
                    )
                else:
                    failed += 1
                    failure_detail = {
                        "query_index": i,
                        "query": query_str,
                        "expected_gate": expected_gate,
                        "actual_gate": actual_gate,
                        "expected_safety_critical": expected_safety,
                        "actual_safety_critical": actual_safety,
                        "gate_match": gate_match,
                        "safety_match": safety_match,
                    }
                    failures.append(failure_detail)
                    logger.warning(
                        f"Query {i + 1}/{total} FAILED: '{query_str}' "
                        f"expected_gate={expected_gate} actual_gate={actual_gate} "
                        f"expected_safety={expected_safety} actual_safety={actual_safety}"
                    )

            except Exception as exc:
                failed += 1
                failure_detail = {
                    "query_index": i,
                    "query": query_str,
                    "expected_gate": expected_gate,
                    "expected_safety_critical": expected_safety,
                    "error": str(exc),
                }
                failures.append(failure_detail)
                logger.error(
                    f"Query {i + 1}/{total} ERROR: '{query_str}' -> {exc}"
                )

        logger.info(
            f"Regression complete: {passed}/{total} passed, "
            f"{failed}/{total} failed"
        )

        return {
            "passed": passed,
            "failed": failed,
            "total": total,
            "failures": failures,
            "schema_version": schema_version,
        }

    def _load_golden_queries(self, path: str) -> List[Dict[str, Any]]:
        """Load golden queries from a JSON file.

        Each query in the file should have the following structure:
            {
                "query": str,
                "expected_gate": str,       # "PASS", "CLARIFY", or "REFUSE"
                "expected_safety_critical": bool
            }

        Args:
            path: Path to the JSON file.

        Returns:
            List of golden query dictionaries.

        Raises:
            FileNotFoundError: If the file does not exist.
            json.JSONDecodeError: If the file is not valid JSON.
            ValueError: If the file does not contain a list.
        """
        logger.debug(f"Loading golden queries from '{path}'")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError(
                f"Golden queries file must contain a JSON array, "
                f"got {type(data).__name__}"
            )

        # Validate each query has required fields
        for i, query in enumerate(data):
            if not isinstance(query, dict):
                raise ValueError(
                    f"Golden query at index {i} must be a dict, "
                    f"got {type(query).__name__}"
                )
            required = {"query", "expected_gate", "expected_safety_critical"}
            missing = required - set(query.keys())
            if missing:
                raise ValueError(
                    f"Golden query at index {i} missing required fields: "
                    f"{missing}"
                )

        logger.info(f"Loaded {len(data)} golden queries from '{path}'")
        return data
