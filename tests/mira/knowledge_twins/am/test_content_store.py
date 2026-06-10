"""
Tests: AM content store freeze gate, deny-by-default access, placeholder
inertness, and the real frozen 6030/6033 corpus (PR-0).

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mira.core.models import SafetyCriticalError
from mira.knowledge_twins.am.am_models import AccessContext, DataClassification
from mira.knowledge_twins.am.content_store import (
    AccessDeniedError,
    AMContentStore,
    PlaceholderInertError,
    UnknownStandardError,
    default_store_dir,
)
from mira.knowledge_twins.am.freeze import (
    DEMO_PLACEHOLDER_CATALOG,
    freeze_gpcm_pack,
    seed_placeholders,
)
from mira.knowledge_twins.am.rule_pack_models import (
    PlaceholderStandard,
    VerificationStatus,
)

_STD = "TEST-STD-0001"


def _demo_access(**overrides: object) -> AccessContext:
    base: dict = {
        "tenant_id": "boundstate-demo",
        "program_ids": ["demo"],
        "permitted_source_classes": ["public"],
        "deployment_boundary": "demo-public-box",
        "max_data_classification": DataClassification.PUBLIC,
    }
    base.update(overrides)
    return AccessContext(**base)


def _gpcm_payload() -> dict:
    return {
        "schema_version": "gpcm_rulepack/v1",
        "rule_pack_id": f"gpcm-rulepack-{_STD.lower()}",
        "standard_id": _STD,
        "version": "1.0.0",
        "generated_at": "2026-06-09T00:00:00+00:00",
        "source_document": "test_std.pdf",
        "source_extract": "test_std_shall_statements.json",
        "total_requirements": 2,
        "requirements": [
            {
                "id": "amr-1",
                "source_tag": "AMR 1",
                "section": "4.1",
                "shall_text": "The CEO shall do the first thing.",
                "subject": "The CEO",
                "requirement": "do the first thing",
                "page": 10,
                "keywords": ["materials"],
                "applies_to": ["all_programs"],
            },
            {
                "id": "req-2",
                "source_tag": "",
                "section": "4.2",
                "shall_text": "The CEO shall do the second thing.",
                "subject": "The CEO",
                "requirement": "do the second thing",
                "page": 11,
            },
        ],
    }


@pytest.fixture()
def store(tmp_path: Path) -> AMContentStore:
    gpcm_path = tmp_path / "gpcm.json"
    gpcm_path.write_text(json.dumps(_gpcm_payload()), encoding="utf-8")
    source_pdf = tmp_path / "test_std.pdf"
    source_pdf.write_bytes(b"%PDF-1.4 synthetic source bytes")
    store_dir = tmp_path / "store"
    seed_placeholders(store_dir)
    freeze_gpcm_pack(gpcm_path, source_pdf, store_dir, standard_title="Test Standard")
    return AMContentStore(store_dir)


# ------------------------------------------------------------- access policy


def test_no_access_context_denies_everything(store: AMContentStore) -> None:
    with pytest.raises(AccessDeniedError):
        store.load_pack(_STD, None)
    with pytest.raises(AccessDeniedError):
        store.available_standards(None)
    with pytest.raises(AccessDeniedError):
        store.get_placeholders(None)


def test_source_class_not_permitted_is_denied(store: AMContentStore) -> None:
    ctx = _demo_access(permitted_source_classes=["customer"])
    with pytest.raises(AccessDeniedError):
        store.load_pack(_STD, ctx)
    assert store.available_standards(ctx) == []


def test_permitted_access_loads_pack(store: AMContentStore) -> None:
    pack = store.load_pack(_STD, _demo_access())
    assert pack.standard_id == _STD
    assert pack.total_requirements == 2
    assert pack.verification_status is VerificationStatus.UNVERIFIED
    assert pack.source_document_hash and pack.source_pack_hash
    ids = [r.requirement_id for r in pack.requirements]
    assert ids == [f"REQ:{_STD}:AMR-1", f"REQ:{_STD}:REQ-2"]


def test_unknown_standard_raises(store: AMContentStore) -> None:
    with pytest.raises(UnknownStandardError):
        store.load_pack("NOT-A-STANDARD", _demo_access())


def test_classification_above_boundary_is_rejected_not_downgraded(
    store: AMContentStore,
) -> None:
    """Rev 5 §4.5: above-boundary content is rejected with an explicit
    boundary error, never silently served. Exercised by marking the manifest
    entry CUI against a PUBLIC-boundary caller."""
    manifest_path = store.store_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in payload["packs"]:
        entry["data_classification"] = "CUI"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AccessDeniedError, match="exceeds boundary"):
        store.load_pack(_STD, _demo_access())
    assert store.available_standards(_demo_access()) == []


def test_default_store_dir_resolves_to_repo_data_dir() -> None:
    """Guards the parents[N] depth in default_store_dir against file moves."""
    resolved = default_store_dir()
    assert resolved.name == "am_content_store"
    assert resolved.parent.name == "data"
    assert (resolved.parents[1] / "mira" / "knowledge_twins" / "am").is_dir()


# ------------------------------------------------------------ integrity gate


def test_tampered_pack_is_a_safety_critical_error(store: AMContentStore) -> None:
    pack_file = next(store.store_dir.glob("am_rulepack_*.json"))
    payload = json.loads(pack_file.read_text(encoding="utf-8"))
    payload["requirements"][0]["shall_text"] = "The CEO shall do whatever."
    pack_file.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SafetyCriticalError, match="integrity"):
        store.load_pack(_STD, _demo_access())


def test_missing_manifest_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        AMContentStore(tmp_path / "empty").load_manifest()


# ----------------------------------------------------------- freeze gate


def test_freeze_rejects_inconsistent_total(tmp_path: Path) -> None:
    payload = _gpcm_payload()
    payload["total_requirements"] = 7
    gpcm = tmp_path / "bad.json"
    gpcm.write_text(json.dumps(payload), encoding="utf-8")
    pdf = tmp_path / "test_std.pdf"
    pdf.write_bytes(b"x")
    with pytest.raises(ValueError, match="inconsistent"):
        freeze_gpcm_pack(gpcm, pdf, tmp_path / "s")


def test_freeze_rejects_empty_shall_text(tmp_path: Path) -> None:
    payload = _gpcm_payload()
    payload["requirements"][1]["shall_text"] = "  "
    gpcm = tmp_path / "bad.json"
    gpcm.write_text(json.dumps(payload), encoding="utf-8")
    pdf = tmp_path / "test_std.pdf"
    pdf.write_bytes(b"x")
    with pytest.raises(ValueError, match="uncitable"):
        freeze_gpcm_pack(gpcm, pdf, tmp_path / "s")


def test_freeze_rejects_mismatched_source_document(tmp_path: Path) -> None:
    gpcm = tmp_path / "gpcm.json"
    gpcm.write_text(json.dumps(_gpcm_payload()), encoding="utf-8")
    wrong_pdf = tmp_path / "some_other_doc.pdf"
    wrong_pdf.write_bytes(b"x")
    with pytest.raises(ValueError, match="pins the exact source"):
        freeze_gpcm_pack(gpcm, wrong_pdf, tmp_path / "s")


# ------------------------------------------------------- placeholder inertness


def test_placeholders_are_listed_but_never_loadable(store: AMContentStore) -> None:
    ctx = _demo_access()
    placeholders = store.get_placeholders(ctx)
    assert len(placeholders) == len(DEMO_PLACEHOLDER_CATALOG)
    assert all(p.loaded is False for p in placeholders)
    with pytest.raises(PlaceholderInertError):
        store.load_pack(placeholders[0].standard_id, ctx)


def test_placeholder_model_cannot_carry_content() -> None:
    """Inert by construction: content-bearing fields are unrepresentable."""
    with pytest.raises(ValidationError):
        PlaceholderStandard(
            standard_id="SAE-AMS7003A",
            title="x",
            clause_text="2.4.1 The process shall...",  # type: ignore[call-arg]
        )
    with pytest.raises(ValidationError):
        PlaceholderStandard(standard_id="SAE-AMS7003A", title="x", loaded=True)  # type: ignore[arg-type]


def test_no_rule_packs_ship_inside_the_code_package() -> None:
    """Rev 5 §4.4: corpus lives in the external store, not the code tree."""
    package_dir = Path(__file__).resolve().parents[4] / "mira" / "knowledge_twins" / "am"
    assert package_dir.is_dir()
    assert list(package_dir.glob("**/*.json")) == []


# ------------------------------------------------------ real frozen corpus


_REAL_STORE = default_store_dir()


@pytest.mark.skipif(
    not (_REAL_STORE / "manifest.json").is_file(),
    reason="real AM content store not populated on this machine",
)
def test_real_6030_and_6033_packs_load_and_cite() -> None:
    store = AMContentStore(_REAL_STORE)
    ctx = _demo_access()
    assert set(store.available_standards(ctx)) == {"NASA-STD-6030", "NASA-STD-6033"}

    pack_6030 = store.load_pack("NASA-STD-6030", ctx)
    assert pack_6030.total_requirements == 115
    by_id = {r.requirement_id: r for r in pack_6030.requirements}
    amr5 = by_id["REQ:NASA-STD-6030:AMR-5"]
    assert "primary classification" in amr5.shall_text.lower()
    assert amr5.page == 34
    # Source PDF is pinned by hash and the pack is honest about verification.
    assert len(pack_6030.source_document_hash) == 64
    assert pack_6030.verification_status is VerificationStatus.UNVERIFIED

    pack_6033 = store.load_pack("NASA-STD-6033", ctx)
    assert pack_6033.total_requirements == 33
    assert all(r.shall_text.strip() for r in pack_6033.requirements)
