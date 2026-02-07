#!/usr/bin/env python3
"""
Module: Cell
Purpose: TableCell Model.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
Safety Critical: True
"""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from athena.core.bbox import BBox
    from athena.semantic.ontology import SemanticTag

__all__ = ["TableCell"]
__safety_critical__ = True


class TableCell(BaseModel):
    """Single cell in extracted table grid."""
    model_config = {"extra": "forbid"}

    r: int                              # Row index (0-based)
    c: int                              # Column index (0-based)
    text: Optional[str] = None          # Cell content (None if empty)
    rowspan: int = 1
    colspan: int = 1

    # Semantic tag (assigned by SemanticMapper)
    semantic_tag: Optional[Any] = None  # SemanticTag enum value

    # Pixel-level provenance (optional, debug mode)
    cell_bbox: Optional["BBox"] = None

    def __repr__(self) -> str:
        text_preview = self.text[:20] + "..." if self.text and len(self.text) > 20 else self.text
        return f"TableCell(r={self.r}, c={self.c}, text={text_preview!r})"
