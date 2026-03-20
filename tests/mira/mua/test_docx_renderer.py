"""Tests for MUA Form 551 DOCX rendering."""

from mira.mua.classifier.models import Form551Fields


def test_render_form551_docx_produces_bytes():
    """Ensure renderer returns non-empty bytes."""
    from mira.mua.classifier.docx_renderer import render_form551_docx

    form = Form551Fields(
        mua_number="MUA-FS-A286-10392",
        category="II",
        date="2026-02-28",
        governing_standard="NASA-STD-6016C",
        project="DMLLV",
        system="10-Inch H2 Valve (In-Space Refueling)",
        material_designation="A286 CRES (UNS K66286)",
        maptis_code="10392",
        material_specification="SAE AMS 5731",
        material_class="metal",
        issue="FS",
        rating="U",
        part_numbers=["MER07581-001: SHAFT, PISTON, ACTUATOR"],
        part_count=1,
        media="GH2",
        pressure="6000 psia",
        temperature="-423 to 200 degF",
        location="Non-habitable (in-space)",
        application="Actuator piston shaft for 10-inch H2 valve",
        rationale="A286 CRES (MAPTIS 10392) has a fluid system compatibility rating of U...",
        disposition="Accepted. FS=U reflects absence of screening data...",
    )

    result = render_form551_docx(form)
    assert isinstance(result, bytes)
    assert len(result) > 1000
    assert result[:2] == b"PK"


def test_render_form551_docx_handles_empty_parts():
    """Renderer should handle empty part_numbers gracefully."""
    from mira.mua.classifier.docx_renderer import render_form551_docx

    form = Form551Fields(
        mua_number="MUA-FLAM-INC625-10727",
        category="II",
        issue="FLAM",
        rating="C",
        material_designation="INCONEL 625",
        maptis_code="10727",
        material_class="metal",
        media="GH2",
        rationale="Test rationale.",
        disposition="Accepted.",
    )
    result = render_form551_docx(form)
    assert isinstance(result, bytes)
    assert result[:2] == b"PK"
