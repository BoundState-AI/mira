#!/usr/bin/env python3
"""
Module: Pipeline Config
Purpose: pipeline_config

BoundState AI 2025
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, NASA-STD-8739.8B
Safety Critical: True
"""

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from athena.models.enums import DeploymentMode


class AthenaConfig(BaseSettings):
    """Full ATHENA configuration.

    Environment Variables:
        DEPLOYMENT_MODE: cloud|govcloud|on_prem (default: govcloud)
        AWS_REGION: AWS region (default: us-gov-west-1)
        POSTGRES_URL: PostgreSQL connection string
        REDIS_URL: Redis connection string
        S3_BUCKET: S3 bucket for file storage
        QDRANT_URL: Qdrant vector database URL
        JWT_SECRET: Secret for JWT tokens

    V2 Environment Variables:
        ABBYY_SERVER_URL: ABBYY FineReader Server URL
        SEPARATOR_BARCODE_PREFIX: Prefix for separator sheet barcodes
        USE_TEXT_ONLY_MODE: Enable text-only extraction (cheaper)
        DISCOVERY_SAMPLE_PAGES: Pages to sample for discovery phase
    """

    # Deployment
    deployment_mode: DeploymentMode = DeploymentMode.GOVCLOUD
    pipeline_version: str = "4.0.0"  # V2 pipeline

    # AWS/Bedrock
    aws_region: str = "us-gov-west-1"

    # Storage
    postgres_url: str = Field(default="")
    redis_url: str = Field(default="")
    s3_bucket: str = Field(default="")
    qdrant_url: str = Field(default="")
    qdrant_collection: str = "athena_docs"

    # Models
    embedding_model: str = "all-MiniLM-L12-v2"

    # Processing
    max_concurrent_jobs: int = 10
    pages_per_triage: int = 3
    pages_per_extraction: int = 3
    default_dpi: int = 200
    max_dpi: int = 400

    # Thresholds
    quality_threshold: float = 0.5
    confidence_threshold: float = 0.7
    boundary_threshold: float = 0.7

    # Cost
    default_budget_usd: float = 1000.0
    per_document_cap_usd: float = 5.0
    cache_ttl_days: int = 30

    # Security
    jwt_secret: str = Field(default="")
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24

    # Audit
    audit_log_enabled: bool = True
    audit_log_retention_days: int = 2555  # ~7 years

    # ==========================================================================
    # V2: ABBYY OCR Settings
    # ==========================================================================
    abbyy_server_url: str = Field(default="")
    abbyy_output_dir: str = Field(default="./ocr_output")
    ocr_confidence_threshold: float = 0.7  # Below this triggers vision review
    max_text_length_per_page: int = 12000  # Truncate text for LLM context

    # ==========================================================================
    # V2: Separator Sheet Settings
    # ==========================================================================
    use_separators: bool = True  # Enable barcode-based boundary detection
    separator_barcode_prefix: str = "SEP"  # Prefix for separator barcodes
    separator_dpi: int = 300  # DPI for barcode scanning
    hybrid_boundary_mode: bool = True  # Separator + heuristic fallback

    # ==========================================================================
    # V2: Discovery Phase Settings
    # ==========================================================================
    discovery_enabled: bool = True  # Run discovery before triage
    discovery_sample_pages: int = 50  # Pages to sample per batch
    discovery_output_dir: str = Field(default="./discovery_output")

    # ==========================================================================
    # V2: Text-Only Mode Settings (3.8x cheaper than vision)
    # ==========================================================================
    use_text_only_mode: bool = True  # Use text-only extraction when possible
    vision_trigger_threshold: float = 0.15  # % of pages that need vision (~15%)
    max_vision_pages_per_batch: int = 100  # Cap on vision pages per batch

    # ==========================================================================
    # V2: Incremental Save Settings (THE WASTED RUN OF 2025-12-22)
    # ==========================================================================
    incremental_save_enabled: bool = True
    save_state_dir: str = Field(default="./pipeline_state")

    # ==========================================================================
    # V2: Cost Model Settings
    # ==========================================================================
    # Per-page costs (approximate)
    cost_per_page_ocr: float = 0.002  # ABBYY OCR
    cost_per_page_text_triage: float = 0.0005  # Haiku text-only
    cost_per_page_text_extract: float = 0.003  # Haiku text-only
    cost_per_page_vision_extract: float = 0.01  # Sonnet vision
    # Blended cost target: ~$0.018/page (vs V1 ~$0.035/page)

    model_config = {
        "env_prefix": "",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @classmethod
    def from_env(cls) -> "AthenaConfig":
        """Create configuration from environment variables."""
        return cls(
            deployment_mode=DeploymentMode(os.environ.get("DEPLOYMENT_MODE", "govcloud")),
            aws_region=os.environ.get("AWS_REGION", "us-gov-west-1"),
            postgres_url=os.environ.get("POSTGRES_URL", ""),
            redis_url=os.environ.get("REDIS_URL", ""),
            s3_bucket=os.environ.get("S3_BUCKET", ""),
            qdrant_url=os.environ.get("QDRANT_URL", ""),
            jwt_secret=os.environ.get("JWT_SECRET", ""),
            # V2 settings
            abbyy_server_url=os.environ.get("ABBYY_SERVER_URL", ""),
            separator_barcode_prefix=os.environ.get("SEPARATOR_BARCODE_PREFIX", "SEP"),
            use_text_only_mode=os.environ.get("USE_TEXT_ONLY_MODE", "true").lower() == "true",
            discovery_sample_pages=int(os.environ.get("DISCOVERY_SAMPLE_PAGES", "50")),
            incremental_save_enabled=os.environ.get("INCREMENTAL_SAVE_ENABLED", "true").lower() == "true",
        )

    def get_model_id(self, model_key: str) -> str:
        """Get model ID based on deployment mode and model key.

        Args:
            model_key: "triage" or "extract"

        Returns:
            Full model ID for the deployment mode
        """
        if self.deployment_mode == DeploymentMode.GOVCLOUD:
            models = {
                "triage": "us-gov.anthropic.claude-3-5-haiku-20241022-v1:0",
                "extract": "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0",
            }
        elif self.deployment_mode == DeploymentMode.CLOUD:
            models = {
                "triage": "claude-3-5-haiku-20241022",
                "extract": "claude-sonnet-4-5-20250929",
            }
        else:  # ON_PREM
            models = {
                "triage": "local-haiku",
                "extract": "local-sonnet",
            }
        return models.get(model_key, models["extract"])


class DPIStrategy:
    """Adaptive DPI calculation based on document quality and routing."""

    # DPI recommendations based on quality issues
    QUALITY_DPI_ADJUSTMENTS: dict[str, int] = {
        "faded": 50,
        "low_contrast": 50,
        "handwritten": 100,
        "blurry": -50,  # Higher DPI won't help blurry originals
    }

    @classmethod
    def calculate(
        cls,
        routing: str,
        quality_issues: list[Any],
        source_dpi: int | None = None,
        max_dpi: int = 400,
        default_dpi: int = 200,
    ) -> int:
        """Calculate recommended DPI based on document characteristics.

        Args:
            routing: Routing decision (extract_full, extract_light, etc.)
            quality_issues: List of quality issues detected
            source_dpi: Original document DPI if known
            max_dpi: Maximum allowed DPI
            default_dpi: Default DPI to use

        Returns:
            Recommended DPI for extraction
        """
        # Start with base DPI based on routing
        if routing == "extract_full":
            base_dpi = 300
        elif routing == "extract_light":
            base_dpi = 200
        else:
            base_dpi = default_dpi

        # Adjust for quality issues
        adjustment = 0
        for issue in quality_issues:
            issue_str = issue.value if hasattr(issue, "value") else str(issue)
            adjustment += cls.QUALITY_DPI_ADJUSTMENTS.get(issue_str, 0)

        # Apply adjustment
        recommended = base_dpi + adjustment

        # Clamp to valid range
        recommended = max(100, min(max_dpi, recommended))

        # Don't exceed source DPI if known (upscaling doesn't help)
        if source_dpi and recommended > source_dpi:
            recommended = source_dpi

        return recommended
