#!/usr/bin/env python3
"""
Module: Config
Purpose: MIUL Builder v2.3 - Configuration

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

import re
from dataclasses import dataclass, field


# =============================================================================
# Binding Configuration
# =============================================================================

@dataclass
class BindingConfig:
    """Configuration for Phase 2 page binding."""

    # Zone weights per spec v2.3 (THE KEY FIX)
    zone_weights: dict[str, int] = field(default_factory=lambda: {
        "titleblock": 70,
        "border": 50,
        "body": 30,
        "notes": 10,    # Notes don't bind!
        "unknown": 20,
    })

    # Binding thresholds
    threshold_primary: int = 80      # Strong binding -> pages_primary
    threshold_supporting: int = 50   # Weak binding -> pages_supporting
    threshold_ambiguous: int = 10    # Score difference that triggers BLOCKER
    threshold_orphan: int = 30       # Below this, page is orphan

    # Title block bonus
    title_block_match_bonus: int = 100

    # Layout evidence bonuses
    layout_title_block_bonus: int = 20
    layout_views_bonus: int = 10
    layout_balloons_bonus: int = 10
    layout_parts_list_bonus: int = 20

    # Revision handling
    strict_revision: bool = True     # If True, revision conflicts are BLOCKERs


# =============================================================================
# Extraction Configuration
# =============================================================================

@dataclass
class ExtractionConfig:
    """Configuration for Phase 1 extraction."""

    # Vision model configuration
    vision_model: str = "claude-sonnet-4-20250514"
    prompt_version: str = "v2.3"

    # Standard hardware prefixes (for part number detection)
    standard_hardware_prefixes: tuple[str, ...] = (
        "NAS",   # National Aerospace Standard
        "MS",    # Military Standard
        "AN",    # Air Force-Navy Aeronautical Standard
        "AS",    # Aerospace Standard (SAE)
        "NASM",  # NAS Metric
        "BAC",   # Boeing Aerospace Company
        "HCC",   # Hardware Component Code
    )

    @property
    def standard_hardware_regex(self) -> re.Pattern:
        pattern = r'^(' + '|'.join(self.standard_hardware_prefixes) + r')-?\d'
        return re.compile(pattern, re.IGNORECASE)


# =============================================================================
# Graph Configuration
# =============================================================================

@dataclass
class GraphConfig:
    """Configuration for Phase 3 graph building."""

    # Drawing Tree PDF detection patterns
    dt_pdf_patterns: tuple[str, ...] = (
        r'.*drawing.*tree.*\.pdf$',
        r'.*-DT.*\.pdf$',
        r'.*_DT_.*\.pdf$',
        r'.*_DT\.pdf$',
    )

    # Standard hardware prefixes that are always BLACK_BOX
    always_black_box_prefixes: tuple[str, ...] = (
        "NAS",
        "MS",
        "AN",
        "AS",
        "NASM",
        "BAC",
        "HCC",
    )

    # Additional black-box part numbers (manually configured)
    black_box_part_numbers: list[str] = field(default_factory=list)

    # Explosion policy overrides (part_number -> policy)
    explosion_policy_overrides: dict[str, str] = field(default_factory=dict)


# =============================================================================
# MIUL Configuration
# =============================================================================

@dataclass
class MIULConfig:
    """Configuration for Phase 4 MIUL generation."""

    # Deduplication
    deduplicate_by_part_number: bool = True

    # Missing data handling
    missing_material_placeholder: str = "MATERIAL TBD"


# =============================================================================
# Pipeline Configuration
# =============================================================================

@dataclass
class PipelineConfig:
    """Complete pipeline configuration."""

    binding: BindingConfig = field(default_factory=BindingConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    graph: GraphConfig = field(default_factory=GraphConfig)
    miul: MIULConfig = field(default_factory=MIULConfig)

    # Global settings
    cache_enabled: bool = True
    verbose: bool = False
    skip_vision: bool = False
    max_workers: int = 5  # Concurrent Vision API calls (parallel extraction)

    @classmethod
    def default(cls) -> 'PipelineConfig':
        """Create default configuration."""
        return cls()

    @classmethod
    def from_dict(cls, data: dict) -> 'PipelineConfig':
        """Create configuration from dictionary."""
        config = cls()

        if 'binding' in data:
            for key, value in data['binding'].items():
                if hasattr(config.binding, key):
                    setattr(config.binding, key, value)

        if 'extraction' in data:
            for key, value in data['extraction'].items():
                if hasattr(config.extraction, key):
                    setattr(config.extraction, key, value)

        if 'graph' in data:
            for key, value in data['graph'].items():
                if hasattr(config.graph, key):
                    setattr(config.graph, key, value)

        if 'miul' in data:
            for key, value in data['miul'].items():
                if hasattr(config.miul, key):
                    setattr(config.miul, key, value)

        # Global settings
        if 'cache_enabled' in data:
            config.cache_enabled = data['cache_enabled']
        if 'verbose' in data:
            config.verbose = data['verbose']
        if 'skip_vision' in data:
            config.skip_vision = data['skip_vision']
        if 'max_workers' in data:
            config.max_workers = data['max_workers']

        return config

    def to_dict(self) -> dict:
        """Convert configuration to dictionary."""
        return {
            'binding': {
                'zone_weights': self.binding.zone_weights,
                'threshold_primary': self.binding.threshold_primary,
                'threshold_supporting': self.binding.threshold_supporting,
                'threshold_ambiguous': self.binding.threshold_ambiguous,
                'strict_revision': self.binding.strict_revision,
            },
            'extraction': {
                'vision_model': self.extraction.vision_model,
                'prompt_version': self.extraction.prompt_version,
                'standard_hardware_prefixes': list(self.extraction.standard_hardware_prefixes),
            },
            'graph': {
                'always_black_box_prefixes': list(self.graph.always_black_box_prefixes),
                'black_box_part_numbers': self.graph.black_box_part_numbers,
            },
            'miul': {
                'deduplicate_by_part_number': self.miul.deduplicate_by_part_number,
            },
            'cache_enabled': self.cache_enabled,
            'verbose': self.verbose,
            'skip_vision': self.skip_vision,
            'max_workers': self.max_workers,
        }
