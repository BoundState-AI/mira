#!/usr/bin/env python3
"""
Module: Pipeline Stage
Purpose: Abstract base class for all MIRA V3 pipeline stages.

Every stage implements execute() and optionally should_skip().
Every stage reads from and writes to a shared QueryContext.
No stage reaches into another stage's internals. Rule 4.2.

BoundState AI 2026
Version: 3.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

from __future__ import annotations

import abc
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import QueryContext

logger = logging.getLogger(__name__)


class PipelineStage(abc.ABC):
    """
    Abstract base class for a single pipeline stage.

    Subclasses MUST implement:
        name: str property
        execute(ctx) -> QueryContext

    Subclasses MAY override:
        should_skip(ctx) -> bool  (default: False)
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable stage identifier (e.g., 'parse', 'mua_retrieval')."""
        ...

    @abc.abstractmethod
    def execute(self, ctx: QueryContext) -> QueryContext:
        """
        Perform this stage's work.

        Read what you need from ctx. Write your results to ctx.
        Return ctx (may be the same object, mutated in place).

        Raises:
            Exception: Any stage failure. The pipeline will catch it,
            log it, record it in ctx.errors, and continue.
        """
        ...

    def should_skip(self, ctx: QueryContext) -> bool:
        """
        Return True to skip this stage entirely.

        Common reasons:
        - Boundary check short-circuited (no further stages needed)
        - Wrong pipeline (materials_search doesn't need MUA retrieval)

        Default: never skip.
        """
        return False
