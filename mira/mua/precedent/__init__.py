"""MUA Precedent Database — BS-SPEC-MUA-DB-001.

Historic MUA precedent lookup for enriching V10 classifier output.
Optional module — V10 runs identically without it.

BoundState AI 2026
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from .lookup import lookup_precedent, lookup_precedent_with_ring, normalize_media_category
from .models import PrecedentSummary, PrecedentExemplar

__all__ = [
    "PrecedentSummary",
    "PrecedentExemplar",
    "lookup_precedent",
    "lookup_precedent_with_ring",
    "normalize_media_category",
]
