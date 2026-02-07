#!/usr/bin/env python3
"""
Module: Template Renderer
Purpose: Logic-free Jinja2 template rendering

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Fran Fix #9: Templates are deliberately dumb.
Allowed: {{ value }}, {% for %}, {% if section.content %}
Forbidden: {% if value > threshold %} (logic belongs in SectionBuilder)

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .section_builder import SectionContent

LOGGER = logging.getLogger(__name__)

__version__ = "2.0.0"
__safety_critical__ = False

# Default template directory
DEFAULT_TEMPLATE_DIR = Path(__file__).parent / "templates"


class TemplateRenderer:
    """
    Logic-free template renderer.

    Fran Fix #9: Templates only do:
    - Value insertion: {{ section.text_content }}
    - Iteration: {% for row in section.table_content %}
    - Presence check: {% if section.content %}

    All business logic is pre-computed in SectionBuilder.
    """

    def __init__(
        self,
        template_dir: Optional[Path] = None,
    ):
        """
        Initialize renderer.

        Args:
            template_dir: Template directory. Defaults to built-in templates.
        """
        self._template_dir = template_dir or DEFAULT_TEMPLATE_DIR

        # Ensure template directory exists
        self._template_dir.mkdir(parents=True, exist_ok=True)

        # Initialize Jinja2 environment
        self._env = Environment(
            loader=FileSystemLoader(str(self._template_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render_section(
        self,
        section: SectionContent,
        template_name: Optional[str] = None,
    ) -> str:
        """
        Render a section using its template.

        Args:
            section: Pre-computed section content.
            template_name: Optional template name override.

        Returns:
            Rendered content string.
        """
        # Determine template name
        if template_name is None:
            template_name = f"{section.section_id}.html"

        # Check if template exists, otherwise use default
        template_path = self._template_dir / template_name
        if not template_path.exists():
            template_name = "default_section.html"
            template_path = self._template_dir / template_name

        # If no templates exist at all, return plain text
        if not template_path.exists():
            return self._render_plain_text(section)

        try:
            template = self._env.get_template(template_name)
            return template.render(section=section)
        except Exception as e:
            LOGGER.warning(f"Template render failed: {e}, using plain text")
            return self._render_plain_text(section)

    def _render_plain_text(self, section: SectionContent) -> str:
        """Render section as plain text (fallback)."""
        lines = []

        # Title
        if section.section_number:
            lines.append(f"{section.section_number} {section.section_title}")
        else:
            lines.append(section.section_title)
        lines.append("=" * len(lines[-1]))
        lines.append("")

        # Text content
        if section.text_content:
            lines.append(section.text_content)
            lines.append("")

        # Bullet points
        if section.bullet_points:
            for point in section.bullet_points:
                lines.append(f"  • {point}")
            lines.append("")

        # Table (simple text format)
        if section.table_content:
            # Get column headers from first row
            if section.table_content:
                headers = list(section.table_content[0].keys())
                lines.append(" | ".join(headers))
                lines.append("-" * (len(headers) * 15))
                for row in section.table_content:
                    values = [str(row.get(h, "")) for h in headers]
                    lines.append(" | ".join(values))
            lines.append("")

        # Subsections
        for subsection in section.subsections:
            lines.append(self._render_plain_text(subsection))

        return "\n".join(lines)

    def render_document(
        self,
        sections: list[SectionContent],
        document_template: str = "document.html",
    ) -> str:
        """
        Render complete document with all sections.

        Args:
            sections: List of pre-computed sections.
            document_template: Document template name.

        Returns:
            Rendered document string.
        """
        template_path = self._template_dir / document_template
        if not template_path.exists():
            # Concatenate sections as fallback
            return "\n\n".join(
                self.render_section(section) for section in sections
            )

        try:
            template = self._env.get_template(document_template)
            return template.render(sections=sections)
        except Exception as e:
            LOGGER.warning(f"Document render failed: {e}")
            return "\n\n".join(
                self.render_section(section) for section in sections
            )


def render_section(
    section: SectionContent,
    template_dir: Optional[Path] = None,
) -> str:
    """
    Render a single section.

    Args:
        section: Pre-computed section content.
        template_dir: Optional template directory.

    Returns:
        Rendered content string.
    """
    renderer = TemplateRenderer(template_dir)
    return renderer.render_section(section)
