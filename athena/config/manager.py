#!/usr/bin/env python3
"""
Module: Manager
Purpose: EM32 Enterprise Config Manager - Production-ready configuration with Pydantic validation

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: Features:
Safety Critical: True
"""

import os
import yaml
import re
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Set
import logging
from datetime import datetime

try:
    from pydantic import BaseModel, Field, validator, root_validator
    from pydantic.types import PositiveInt, PositiveFloat, confloat, conint
    PYDANTIC_AVAILABLE = True
except ImportError:
    # Fallback for environments without Pydantic
    PYDANTIC_AVAILABLE = False
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        def dict(self): return self.__dict__
        def json(self): return json.dumps(self.__dict__)
    def Field(**kwargs): return kwargs.get('default')
    def validator(*args, **kwargs): return lambda f: f
    def root_validator(*args, **kwargs): return lambda f: f
    PositiveInt = int
    PositiveFloat = float
    confloat = float
    conint = int

logger = logging.getLogger(__name__)

class RetrievalConfig(BaseModel):
    """Pydantic-validated retrieval configuration for EM32"""
    use_post_chunking: bool = Field(default=True, description="Enable post-chunking for better context")
    k_docs_discovery: conint(ge=1, le=100) = Field(default=10, description="Documents for initial discovery")
    k_chunks_final: conint(ge=1, le=50) = Field(default=12, description="Final chunks to return")
    max_postchunk_docs_per_query: conint(ge=1, le=20) = Field(default=3, description="Max documents for post-chunking")
    early_exit_chunk_score: confloat(ge=0.0, le=1.0) = Field(default=0.82, description="Score threshold for early exit")
    postchunk_chunk_len_tokens: conint(ge=100, le=2048) = Field(default=420, description="Post-chunk token length")
    postchunk_overlap_tokens: conint(ge=0, le=200) = Field(default=60, description="Overlap tokens between chunks")
    cache_ttl_days: PositiveInt = Field(default=10, description="Cache TTL in days")

    # Manufacturing-specific retrieval settings
    manufacturing_boost: confloat(ge=1.0, le=3.0) = Field(default=1.5, description="Boost for manufacturing keywords")
    nasa_standard_boost: confloat(ge=1.0, le=3.0) = Field(default=2.0, description="Boost for NASA standards")
    em32_context_boost: confloat(ge=1.0, le=3.0) = Field(default=1.8, description="Boost for EM32 context")

    promotion_threshold: Dict[str, Any] = Field(
        default_factory=lambda: {
            'hits': 3,
            'window_hours': 48,
            'distinct_users': 2
        },
        description="Thresholds for content promotion"
    )

    @validator('promotion_threshold')
    def validate_promotion_threshold(cls, v):
        required_keys = {'hits', 'window_hours', 'distinct_users'}
        if not all(key in v for key in required_keys):
            raise ValueError(f"promotion_threshold must contain keys: {required_keys}")
        if v['hits'] < 1 or v['window_hours'] < 1 or v['distinct_users'] < 1:
            raise ValueError("All promotion threshold values must be positive")
        return v

    class Config:
        validate_assignment = True
        extra = "forbid"

class IndexingConfig(BaseModel):
    """Pydantic-validated indexing configuration for EM32"""
    doc_level_embed: Dict[str, Any] = Field(
        default_factory=lambda: {
            'enabled': True,
            'text_budget_tokens': 5000
        },
        description="Document-level embedding settings"
    )

    # Enhanced for EM32 manufacturing documents
    prechunk_allowlist_regex: List[str] = Field(
        default_factory=lambda: [
            r'^(NASA-(STD|HDBK|TM|SP)-\d+)',
            r'^(NPR|NPD)-\d+(\.\d+)*',
            r'^(MSFC-(STD|SPEC|HDBK|PRC)-\d+(-|\.)?\w*)',
            r'^(SSP|SLS|JSC|KSC|GSFC)-(STD|HDBK|SPEC)-\w+',
            r'^(MIL-STD|ASTM|ISO)\b.*',
            r'MAPTIS.*(SUMMARY|CLASS|OVERVIEW)',
            r'^(EM32|TUI|FSW).*',  # EM32-specific patterns
            r'.*(?:friction.*stir.*welding|manufacturing|calibration).*'
        ],
        description="Regex patterns for pre-chunk allowlist"
    )

    # EM32 manufacturing-specific indexing settings
    enable_cad_indexing: bool = Field(default=True, description="Enable CAD file indexing")
    enable_ocr_indexing: bool = Field(default=True, description="Enable OCR for technical drawings")
    enable_manufacturing_tags: bool = Field(default=True, description="Enable manufacturing-specific tagging")

    @validator('prechunk_allowlist_regex')
    def validate_regex_patterns(cls, v):
        for pattern in v:
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(f"Invalid regex pattern '{pattern}': {e}")
        return v

    @validator('doc_level_embed')
    def validate_doc_level_embed(cls, v):
        required_keys = {'enabled', 'text_budget_tokens'}
        if not all(key in v for key in required_keys):
            raise ValueError(f"doc_level_embed must contain keys: {required_keys}")
        if not isinstance(v['enabled'], bool):
            raise ValueError("doc_level_embed.enabled must be boolean")
        if v['text_budget_tokens'] < 100 or v['text_budget_tokens'] > 50000:
            raise ValueError("text_budget_tokens must be between 100 and 50000")
        return v

    class Config:
        validate_assignment = True
        extra = "forbid"

class LimitsConfig(BaseModel):
    """Pydantic-validated processing limits for EM32"""
    skip_if_mb_gt: conint(ge=1, le=1000) = Field(default=10, description="Skip files larger than MB")
    max_file_size_mb: conint(ge=1, le=10000) = Field(default=100, description="Maximum file size in MB")
    skip_binary_files: bool = Field(default=True, description="Skip binary files without parsers")
    max_depth: conint(ge=1, le=100) = Field(default=20, description="Maximum directory traversal depth")

    # EM32-specific limits
    max_cad_files_per_batch: conint(ge=1, le=1000) = Field(default=50, description="Max CAD files per processing batch")
    max_image_resolution: conint(ge=100, le=50000) = Field(default=4096, description="Max image resolution for OCR")

    @root_validator(skip_on_failure=True)
    def validate_limits(cls, values):
        if values.get('skip_if_mb_gt', 0) > values.get('max_file_size_mb', 0):
            raise ValueError("skip_if_mb_gt cannot be larger than max_file_size_mb")
        return values

    class Config:
        validate_assignment = True
        extra = "forbid"

class FileTypesConfig(BaseModel):
    """Pydantic-validated file type configuration for EM32"""
    full_index: List[str] = Field(
        default_factory=lambda: ['.pdf', '.docx', '.doc', '.txt', '.md', '.json'],
        description="File types for full indexing"
    )
    metadata_only: List[str] = Field(
        default_factory=lambda: ['.pptx', '.xlsx', '.xls', '.msg', '.mpp'],
        description="File types for metadata-only indexing"
    )
    skip: List[str] = Field(
        default_factory=lambda: ['.db', '.tmp', '.log', '.cache', '.bak'],
        description="File types to skip entirely"
    )

    # EM32 manufacturing file types
    cad_files: List[str] = Field(
        default_factory=lambda: ['.par', '.asm', '.igs', '.iges', '.dwg', '.step', '.stp', '.x_t'],
        description="CAD file extensions for EM32"
    )
    technical_images: List[str] = Field(
        default_factory=lambda: ['.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp', '.svg'],
        description="Technical image formats for OCR processing"
    )
    manufacturing_data: List[str] = Field(
        default_factory=lambda: ['.nc', '.cnc', '.gcode', '.tap', '.csv'],
        description="Manufacturing data file formats"
    )

    @validator('full_index', 'metadata_only', 'skip', 'cad_files', 'technical_images', 'manufacturing_data')
    def validate_extensions(cls, v):
        for ext in v:
            if not ext.startswith('.'):
                raise ValueError(f"File extension must start with '.': {ext}")
            if len(ext) < 2:
                raise ValueError(f"File extension too short: {ext}")
        return v

    class Config:
        validate_assignment = True
        extra = "forbid"

class PerformanceConfig(BaseModel):
    """Pydantic-validated performance configuration for EM32"""
    doc_level_batch_size: conint(ge=1, le=1000) = Field(default=100, description="Documents per batch")
    chunk_batch_size: conint(ge=1, le=100) = Field(default=16, description="Chunks per batch")
    embedding_device: str = Field(default='cuda', description="Device for embeddings (cuda/cpu)")
    max_concurrent_postchunk: conint(ge=1, le=50) = Field(default=2, description="Max concurrent post-chunk operations")
    cache_size_mb: conint(ge=100, le=50000) = Field(default=1000, description="Cache size in MB")

    # EM32 manufacturing-specific performance settings
    max_cad_processing_threads: conint(ge=1, le=16) = Field(default=4, description="Max threads for CAD processing")
    ocr_timeout_seconds: conint(ge=5, le=300) = Field(default=60, description="OCR timeout per image")
    indexing_checkpoint_interval: conint(ge=10, le=10000) = Field(default=500, description="Files between checkpoints")

    @validator('embedding_device')
    def validate_device(cls, v):
        allowed_devices = {'cuda', 'cpu', 'mps'}  # Include Apple Silicon support
        if v not in allowed_devices:
            raise ValueError(f"embedding_device must be one of: {allowed_devices}")
        return v

    class Config:
        validate_assignment = True
        extra = "forbid"

class TelemetryConfig(BaseModel):
    """Pydantic-validated telemetry configuration for EM32"""
    enabled: bool = Field(default=True, description="Enable telemetry collection")
    log_level: str = Field(default='INFO', description="Logging level")
    track_promotion_stats: bool = Field(default=True, description="Track content promotion statistics")
    track_cache_performance: bool = Field(default=True, description="Track cache hit/miss rates")
    track_query_patterns: bool = Field(default=True, description="Track query pattern analysis")

    # EM32 manufacturing-specific telemetry
    track_manufacturing_metrics: bool = Field(default=True, description="Track manufacturing-specific metrics")
    track_cad_processing: bool = Field(default=True, description="Track CAD processing performance")
    track_ocr_accuracy: bool = Field(default=True, description="Track OCR accuracy metrics")

    telemetry_retention_days: conint(ge=1, le=365) = Field(default=90, description="Days to retain telemetry data")

    @validator('log_level')
    def validate_log_level(cls, v):
        allowed_levels = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}
        if v.upper() not in allowed_levels:
            raise ValueError(f"log_level must be one of: {allowed_levels}")
        return v.upper()

    class Config:
        validate_assignment = True
        extra = "forbid"

class SecurityConfig(BaseModel):
    """Pydantic-validated security configuration for EM32"""
    enable_api_authentication: bool = Field(default=True, description="Enable API authentication")
    api_key_min_length: conint(ge=8, le=128) = Field(default=32, description="Minimum API key length")
    rate_limit_requests_per_minute: conint(ge=1, le=10000) = Field(default=100, description="API rate limit per minute")
    enable_audit_logging: bool = Field(default=True, description="Enable audit logging")
    allowed_file_upload_extensions: Set[str] = Field(
        default_factory=lambda: {'.pdf', '.docx', '.txt', '.png', '.jpg', '.step', '.iges'},
        description="Allowed file upload extensions"
    )

    class Config:
        validate_assignment = True
        extra = "forbid"

class EM32Config(BaseModel):
    """Complete EM32 enterprise configuration with Pydantic validation"""
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig, description="Retrieval system configuration")
    indexing: IndexingConfig = Field(default_factory=IndexingConfig, description="Indexing system configuration")
    limits: LimitsConfig = Field(default_factory=LimitsConfig, description="Processing limits configuration")
    file_types: FileTypesConfig = Field(default_factory=FileTypesConfig, description="File type handling configuration")
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig, description="Performance settings")
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig, description="Telemetry and monitoring")
    security: SecurityConfig = Field(default_factory=SecurityConfig, description="Security configuration")

    # EM32 enterprise metadata
    deployment_environment: str = Field(default="development", description="Deployment environment")
    config_version: str = Field(default="2.0.0", description="Configuration schema version")
    last_updated: datetime = Field(default_factory=datetime.now, description="Last configuration update")

    # NASA compliance metadata
    nasa_compliance_level: str = Field(default="SWE-032", description="NASA software compliance level")
    safety_critical: bool = Field(default=False, description="Safety-critical system designation")

    @validator('deployment_environment')
    def validate_environment(cls, v):
        allowed_envs = {'development', 'testing', 'staging', 'production'}
        if v not in allowed_envs:
            raise ValueError(f"deployment_environment must be one of: {allowed_envs}")
        return v

    @validator('nasa_compliance_level')
    def validate_compliance(cls, v):
        allowed_levels = {'SWE-032', 'SWE-033', 'SWE-013', 'SWE-047'}
        if v not in allowed_levels:
            raise ValueError(f"nasa_compliance_level must be one of: {allowed_levels}")
        return v

    class Config:
        validate_assignment = True
        extra = "forbid"
        json_encoders = {
            datetime: lambda dt: dt.isoformat()
        }

    def __post_init__(self):
        """Post-initialization for compiled patterns and environment overrides"""
        # Compile regex patterns for efficiency
        self._compiled_allowlist = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self.indexing.prechunk_allowlist_regex
        ]

        # Apply environment variable overrides
        self._apply_env_overrides()

    def _apply_env_overrides(self):
        """Apply environment variable overrides to configuration"""
        env_mappings = {
            'EM32_MAX_FILE_SIZE_MB': ('limits', 'max_file_size_mb', int),
            'EM32_EMBEDDING_DEVICE': ('performance', 'embedding_device', str),
            'EM32_ENABLE_CAD': ('indexing', 'enable_cad_indexing', lambda x: x.lower() == 'true'),
            'EM32_ENABLE_OCR': ('indexing', 'enable_ocr_indexing', lambda x: x.lower() == 'true'),
            'EM32_LOG_LEVEL': ('telemetry', 'log_level', str),
            'EM32_DEPLOYMENT_ENV': ('deployment_environment', None, str),
        }

        for env_var, (section, key, converter) in env_mappings.items():
            env_value = os.getenv(env_var)
            if env_value is not None:
                try:
                    converted_value = converter(env_value)
                    if key is None:
                        # Direct attribute
                        setattr(self, section, converted_value)
                    else:
                        # Nested attribute
                        section_obj = getattr(self, section)
                        setattr(section_obj, key, converted_value)
                    logger.info(f"Applied environment override: {env_var}={env_value}")
                except Exception as e:
                    logger.warning(f"Failed to apply environment override {env_var}: {e}")

    def matches_allowlist(self, filename: str) -> bool:
        """Check if filename matches pre-chunk allowlist."""
        for pattern in self._compiled_allowlist:
            if pattern.search(filename):
                return True
        return False

    def should_skip_file(self, filename: str, file_size_mb: float) -> bool:
        """Determine if file should be skipped entirely."""
        ext = Path(filename).suffix.lower()

        if ext in self.file_types.skip:
            return True

        if file_size_mb > self.limits.max_file_size_mb:
            return True

        if self.limits.skip_binary_files and ext not in (self.file_types.full_index + self.file_types.metadata_only):
            return True

        return False

    def get_processing_mode(self, filename: str, file_size_mb: float) -> str:
        """Determine processing mode for file."""
        if self.should_skip_file(filename, file_size_mb):
            return 'skip'

        ext = Path(filename).suffix.lower()

        # Check if matches allowlist for pre-chunking
        if self.matches_allowlist(filename) and ext in self.file_types.full_index:
            if file_size_mb <= self.limits.skip_if_mb_gt:
                return 'pre_chunk'
            else:
                return 'doc_level'  # Too large for pre-chunking

        # Full indexing eligible files
        if ext in self.file_types.full_index:
            return 'doc_level'

        # Metadata only files
        if ext in self.file_types.metadata_only:
            return 'metadata_only'

        return 'skip'

class ConfigManager:
    """Manages Athena configuration with hot-reloading."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self._find_config_file()
        self.config: Optional[AthenaConfig] = None
        self._last_modified = 0
        self.load_config()

    def _find_config_file(self) -> str:
        """Find athena config file in standard locations."""
        search_paths = [
            'athena_config.yaml',
            'athena.yaml',
            os.path.join(os.path.dirname(__file__), 'athena_config.yaml'),
            os.path.expanduser('~/.athena/config.yaml'),
            '/etc/athena/config.yaml'
        ]

        for path in search_paths:
            if os.path.exists(path):
                return path

        # Return default path if none found
        return 'athena_config.yaml'

    def load_config(self) -> AthenaConfig:
        """Load configuration from YAML file."""
        try:
            if not os.path.exists(self.config_path):
                logger.warning(f"Config file not found: {self.config_path}, using defaults")
                self.config = AthenaConfig()
                return self.config

            current_modified = os.path.getmtime(self.config_path)

            # Only reload if file has changed
            if current_modified <= self._last_modified and self.config is not None:
                return self.config

            with open(self.config_path, 'r') as f:
                config_data = yaml.safe_load(f)

            if not config_data:
                logger.warning("Empty config file, using defaults")
                self.config = AthenaConfig()
                return self.config

            # Parse configuration sections
            retrieval_data = config_data.get('retrieval', {})
            indexing_data = config_data.get('indexing', {})
            limits_data = config_data.get('limits', {})
            file_types_data = config_data.get('file_types', {})
            performance_data = config_data.get('performance', {})
            telemetry_data = config_data.get('telemetry', {})

            self.config = AthenaConfig(
                retrieval=RetrievalConfig(**retrieval_data),
                indexing=IndexingConfig(**indexing_data),
                limits=LimitsConfig(**limits_data),
                file_types=FileTypesConfig(**file_types_data),
                performance=PerformanceConfig(**performance_data),
                telemetry=TelemetryConfig(**telemetry_data)
            )

            self._last_modified = current_modified
            logger.info(f"Configuration loaded from {self.config_path}")

        except Exception as e:
            logger.error(f"Error loading config: {e}, using defaults")
            self.config = AthenaConfig()

        return self.config

    def get_config(self) -> AthenaConfig:
        """Get current configuration (with hot-reload check)."""
        return self.load_config()

    def save_config(self, config: AthenaConfig = None) -> bool:
        """Save current configuration to file."""
        try:
            config_to_save = config or self.config
            if not config_to_save:
                return False

            config_dict = {
                'retrieval': {
                    'use_post_chunking': config_to_save.retrieval.use_post_chunking,
                    'k_docs_discovery': config_to_save.retrieval.k_docs_discovery,
                    'k_chunks_final': config_to_save.retrieval.k_chunks_final,
                    'max_postchunk_docs_per_query': config_to_save.retrieval.max_postchunk_docs_per_query,
                    'early_exit_chunk_score': config_to_save.retrieval.early_exit_chunk_score,
                    'postchunk_chunk_len_tokens': config_to_save.retrieval.postchunk_chunk_len_tokens,
                    'postchunk_overlap_tokens': config_to_save.retrieval.postchunk_overlap_tokens,
                    'cache_ttl_days': config_to_save.retrieval.cache_ttl_days,
                    'promotion_threshold': config_to_save.retrieval.promotion_threshold
                },
                'indexing': {
                    'doc_level_embed': config_to_save.indexing.doc_level_embed,
                    'prechunk_allowlist_regex': config_to_save.indexing.prechunk_allowlist_regex
                },
                'limits': {
                    'skip_if_mb_gt': config_to_save.limits.skip_if_mb_gt,
                    'max_file_size_mb': config_to_save.limits.max_file_size_mb,
                    'skip_binary_files': config_to_save.limits.skip_binary_files,
                    'max_depth': config_to_save.limits.max_depth
                },
                'file_types': {
                    'full_index': config_to_save.file_types.full_index,
                    'metadata_only': config_to_save.file_types.metadata_only,
                    'skip': config_to_save.file_types.skip
                },
                'performance': {
                    'doc_level_batch_size': config_to_save.performance.doc_level_batch_size,
                    'chunk_batch_size': config_to_save.performance.chunk_batch_size,
                    'embedding_device': config_to_save.performance.embedding_device,
                    'max_concurrent_postchunk': config_to_save.performance.max_concurrent_postchunk,
                    'cache_size_mb': config_to_save.performance.cache_size_mb
                },
                'telemetry': {
                    'enabled': config_to_save.telemetry.enabled,
                    'log_level': config_to_save.telemetry.log_level,
                    'track_promotion_stats': config_to_save.telemetry.track_promotion_stats,
                    'track_cache_performance': config_to_save.telemetry.track_cache_performance,
                    'track_query_patterns': config_to_save.telemetry.track_query_patterns
                }
            }

            with open(self.config_path, 'w') as f:
                yaml.safe_dump(config_dict, f, default_flow_style=False, indent=2)

            logger.info(f"Configuration saved to {self.config_path}")
            return True

        except Exception as e:
            logger.error(f"Error saving config: {e}")
            return False

# Global config manager instance
_config_manager = None

def get_config() -> AthenaConfig:
    """Get global Athena configuration."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager.get_config()

def set_config_path(path: str):
    """Set custom configuration file path."""
    global _config_manager
    _config_manager = ConfigManager(path)

if __name__ == "__main__":
    # Test configuration loading
    config = get_config()
    print(f"Loaded config with {len(config.indexing.prechunk_allowlist_regex)} allowlist patterns")
    print(f"Post-chunking enabled: {config.retrieval.use_post_chunking}")
    print(f"Document discovery limit: {config.retrieval.k_docs_discovery}")

    # Test allowlist matching
    test_files = [
        "NASA-STD-6001B_Flammability_Requirements.pdf",
        "NPR-8715.3C_Safety_Risk_Management.pdf",
        "MSFC-STD-3029_Welding_Requirements.pdf",
        "MIL-STD-1472H_Human_Engineering.pdf",
        "MAPTIS_SUMMARY_Outgassing_Data.pdf",
        "regular_document.docx"
    ]

    for filename in test_files:
        matches = config.matches_allowlist(filename)
        mode = config.get_processing_mode(filename, 5.0)  # 5MB file
        print(f"{filename}: allowlist={matches}, mode={mode}")