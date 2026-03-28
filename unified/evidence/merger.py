from __future__ import annotations

from collections import Counter, defaultdict

from unified.constraints.conflict_rules import DEFAULT_CROSS_SOURCE_RULES, authority_ranking_for_intent
from unified.schema import ICConflict, ICEvidenceItem, MergedEvidence


class EvidenceMerger:
    def __init__(self, rules=None) -> None:
        self._rules = rules or DEFAULT_CROSS_SOURCE_RULES

    def merge(
        self,
        db_items: list[ICEvidenceItem] | None = None,
        doc_items: list[ICEvidenceItem] | None = None,
        intent: str | None = None,
        max_items: int = 20,
    ) -> MergedEvidence:
        items = list(db_items or []) + list(doc_items or [])
        ranked = self._rank(items, intent=intent)
        conflicts = self._detect_conflicts(ranked, intent=intent)
        source_counts = Counter(item.source_type.value for item in ranked)
        return MergedEvidence(
            items=ranked[:max_items],
            conflicts=conflicts,
            source_counts=dict(source_counts),
            human_review_required=any(conflict.requires_human_review for conflict in conflicts),
        )

    def _rank(self, items: list[ICEvidenceItem], intent: str | None) -> list[ICEvidenceItem]:
        ranking = authority_ranking_for_intent(intent, self._rules)
        authority_positions = {authority: index for index, authority in enumerate(ranking)}

        ranked: list[ICEvidenceItem] = []
        for item in items:
            authority_rank = authority_positions.get(item.authority_class, len(authority_positions))
            adjusted = max(0.0, min(1.0, item.score + ((len(authority_positions) - authority_rank) / 100)))
            ranked.append(item.model_copy(update={"score": adjusted}))
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked

    def _detect_conflicts(self, items: list[ICEvidenceItem], intent: str | None) -> list[ICConflict]:
        grouped: dict[str, list[ICEvidenceItem]] = defaultdict(list)
        for item in items:
            key = item.claim_key or item.source_id
            grouped[key].append(item)

        conflicts: list[ICConflict] = []
        for subject, group in grouped.items():
            distinct_values = {str(item.claim_value) for item in group if item.claim_value is not None}
            if len(distinct_values) <= 1:
                continue

            requires_human_review = any(bool(item.metadata.get("safety_critical")) for item in group)
            policy = "flag_conflict" if requires_human_review else "highest_authority"
            conflicts.append(
                ICConflict(
                    conflict_id=f"conflict:{subject}",
                    subject=subject,
                    description=f"Conflicting evidence for {subject}: {sorted(distinct_values)}",
                    policy=policy,
                    evidence_ids=[item.evidence_id for item in group],
                    requires_human_review=requires_human_review,
                    metadata={"intent": intent, "values": sorted(distinct_values)},
                )
            )
        return conflicts

