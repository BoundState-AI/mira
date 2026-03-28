from __future__ import annotations

from typing import Protocol

from unified.schema import ICEvidenceItem


class UnifiedEvidenceProvider(Protocol):
    def get_evidence(
        self,
        query: str,
        limit: int = 20,
        intent: str | None = None,
    ) -> list[ICEvidenceItem]:
        ...

