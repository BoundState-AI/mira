from __future__ import annotations

from unified.pipeline.bouncer import UnifiedBouncer


def test_unified_bouncer_rejects_approval_and_allowable_queries() -> None:
    bouncer = UnifiedBouncer()
    decision = bouncer.evaluate("Can you approve this allowable and sign off the design value?")

    assert decision.accepted is False
    assert decision.verdict == "rejected"
    assert "SHALL NOT infer new engineering allowables" in decision.reason

