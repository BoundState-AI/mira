#!/usr/bin/env python3
"""
Module: Config
Purpose: Copyright (c) 2025 BoundState Inc. All Rights Reserved.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: - SWE-013: Configurable requirements
Safety Critical: True
"""

from __future__ import annotations

__version__ = "3.0.0"
__safety_critical__ = True  # Class B/C: Configuration affects safety-critical operations

import os
import json
import logging
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator
from enum import Enum

# Handle pydantic v2's separate pydantic-settings package
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    # Fallback: Create minimal BaseSettings from BaseModel
    class BaseSettings(BaseModel):
        """Fallback BaseSettings when pydantic-settings not installed."""
        pass

    # Fallback: Create no-op SettingsConfigDict
    class SettingsConfigDict(dict):
        """Fallback SettingsConfigDict when pydantic-settings not installed."""
        def __init__(self, **kwargs):
            super().__init__(**kwargs)


logger = logging.getLogger(__name__)


class Environment(str, Enum):
    """Application environment enumeration."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


class LogLevel(str, Enum):
    """Logging level enumeration."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class CacheType(str, Enum):
    """Cache backend type enumeration."""
    MEMORY = "memory"
    REDIS = "redis"
    NONE = "none"


class AppConfig(BaseSettings):
    """
    Centralized application configuration with validation.
    
    Loads configuration from environment variables and .env files,
    with validation for production requirements.
    
    Compliance: SWE-013 (Configurable requirements)
    """
    
    # Application Settings
    app_name: str = Field(default="MAPTIS-NLP", description="Application name")
    app_version: str = Field(default="2.0.1", description="Application version")
    environment: Environment = Field(default=Environment.DEVELOPMENT, description="Deployment environment")
    debug: bool = Field(default=True, description="Debug mode flag")
    log_level: LogLevel = Field(default=LogLevel.INFO, description="Logging level")
    
    # Server Configuration
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    workers: int = Field(default=4, description="Number of worker processes")
    reload: bool = Field(default=True, description="Auto-reload on code changes")
    
    # Database and Storage Paths
    faiss_index_path: str = Field(default="./mira/databases/maptis_faiss_db", description="FAISS index directory")
    faiss_gpu_enabled: bool = Field(default=False, description="Enable GPU acceleration for FAISS")
    data_path: str = Field(default="./data", description="Data directory path")

    # PostgreSQL Configuration — dev defaults; production MUST use env vars
    postgres_user: str = Field(default="postgres", description="PostgreSQL username")
    postgres_password: str = Field(default="postgres", description="PostgreSQL password")
    postgres_db: str = Field(default="mira", description="PostgreSQL database name")
    postgres_host: str = Field(default="localhost", description="PostgreSQL host")
    postgres_port: str = Field(default="5432", description="PostgreSQL port")
    materials_data_path: str = Field(default="./data/materials_data.json", description="Materials data file")
    miuls_data_path: str = Field(default="./data/miuls.json", description="MIULs data file")
    muas_data_path: str = Field(default="./data/muas.json", description="MUAs data file")
    test_data_path: str = Field(default="./data/test_materials.json", description="Test materials data")
    upload_path: str = Field(default="./uploads", description="Upload directory")
    max_upload_size_mb: int = Field(default=100, description="Maximum upload size in MB")
    
    # LLM API Keys
    anthropic_api_key: Optional[str] = Field(default=None, description="Anthropic API key for Claude")

    # Security Configuration
    jwt_secret_key: str = Field(
        default_factory=lambda: os.environ.get("JWT_SECRET_KEY", secrets.token_hex(32)),
        description="JWT secret key — MUST be set via JWT_SECRET_KEY env var in production",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_expiration_hours: int = Field(default=24, description="JWT token expiration in hours")
    api_key_header: str = Field(default="X-API-Key", description="API key header name")
    require_api_key: bool = Field(default=False, description="Require API key for access")
    
    # CORS Settings
    cors_origins: List[str] = Field(
        default=[
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:8000",
            "http://localhost:8080",
            "http://localhost:8081",
        ],
        description="Allowed CORS origins"
    )
    cors_allow_credentials: bool = Field(default=True, description="Allow credentials in CORS")
    cors_allow_methods: List[str] = Field(
        default=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        description="Allowed HTTP methods"
    )
    cors_allow_headers: List[str] = Field(default=["*"], description="Allowed headers")
    
    # SSL/TLS Configuration
    ssl_enabled: bool = Field(default=False, description="Enable SSL/TLS")
    ssl_cert_path: Optional[str] = Field(default=None, description="SSL certificate path")
    ssl_key_path: Optional[str] = Field(default=None, description="SSL key path")
    ssl_ca_path: Optional[str] = Field(default=None, description="SSL CA certificate path")
    
    # Logging Configuration
    log_dir: str = Field(default="./logs", description="Log directory path")
    log_file: str = Field(default="maptis.log", description="Main log file name")
    log_max_bytes: int = Field(default=10485760, description="Max log file size (10MB default)")
    log_backup_count: int = Field(default=5, description="Number of log backups to keep")
    log_format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log message format"
    )
    log_date_format: str = Field(
        default="%Y-%m-%d %H:%M:%S",
        description="Log date format"
    )
    enable_console_logging: bool = Field(default=True, description="Enable console logging")
    enable_file_logging: bool = Field(default=True, description="Enable file logging")
    enable_json_logging: bool = Field(default=False, description="Enable JSON logging")
    
    # NASA Specific Configuration
    nasa_site: str = Field(default="JSC", description="NASA site/center code")
    nasa_program: str = Field(default="MAPTIS", description="NASA program name")
    nasa_mission: str = Field(default="Materials Safety", description="NASA mission")
    nasa_subsystem: str = Field(default="NLP", description="NASA subsystem")
    nasa_component: str = Field(default="API", description="NASA component")
    nasa_software_class: str = Field(default="Class B", description="NASA software classification")
    nasa_criticality: str = Field(default="2", description="NASA criticality level")
    nasa_safety_critical: bool = Field(default=True, description="NASA safety-critical designation")
    
    # NASA Compliance Settings
    audit_log_enabled: bool = Field(default=True, description="Enable audit logging")
    audit_log_path: str = Field(default="./logs/audit.log", description="Audit log file path")
    audit_log_retention_days: int = Field(default=90, description="Audit log retention period")
    safety_critical_mode: bool = Field(default=True, description="Enable safety-critical mode")
    safety_error_notifications: bool = Field(default=True, description="Enable safety error notifications")
    safety_notification_email: Optional[str] = Field(default=None, description="Safety notification email")
    nasa_std_8739_8b_enabled: bool = Field(default=True, description="Enable NASA-STD-8739.8B compliance")
    nasa_std_6016_enabled: bool = Field(default=True, description="Enable NASA-STD-6016 compliance")
    swe_compliance_mode: bool = Field(default=True, description="Enable SWE compliance mode")
    
    # Performance Configuration
    cache_enabled: bool = Field(default=True, description="Enable caching")
    cache_type: CacheType = Field(default=CacheType.REDIS, description="Cache backend type")
    cache_prefix: str = Field(default="maptis", description="Cache key prefix")
    cache_ttl_seconds: int = Field(default=3600, description="Cache TTL in seconds")
    cache_warmup_ttl: int = Field(default=7200, description="Warmup cache TTL in seconds")
    cache_ttl_default: int = Field(default=3600, description="Default cache TTL in seconds")
    cache_ttl_search: int = Field(default=1800, description="Search cache TTL")
    cache_ttl_material: int = Field(default=7200, description="Material cache TTL")
    cache_warmup_enabled: bool = Field(default=True, description="Enable cache warmup on startup")
    cache_warmup_queries: List[str] = Field(
        default=[
            "oxygen compatible materials",
            "aluminum alloys",
            "stainless steel",
            "titanium",
            "PEEK",
            "PTFE"
        ],
        description="Queries to warm up cache with"
    )
    
    # Redis Configuration
    redis_url: Optional[str] = Field(default=None, description="Redis connection URL")
    redis_host: str = Field(default="localhost", description="Redis host")
    redis_port: int = Field(default=6379, description="Redis port")
    redis_password: Optional[str] = Field(default=None, description="Redis password")
    redis_db: int = Field(default=0, description="Redis database number")
    redis_max_connections: int = Field(default=50, description="Redis connection pool size")
    redis_socket_timeout: int = Field(default=5, description="Redis socket timeout in seconds")
    redis_retry_on_timeout: bool = Field(default=True, description="Retry on timeout")
    
    # Rate Limiting
    rate_limit_enabled: bool = Field(default=False, description="Enable rate limiting")
    rate_limit_requests: int = Field(default=100, description="Rate limit requests per window")
    rate_limit_window_seconds: int = Field(default=60, description="Rate limit window in seconds")
    
    # Search Configuration
    default_search_limit: int = Field(default=20, description="Default search result limit")
    max_search_limit: int = Field(default=100, description="Maximum search result limit")
    min_similarity_score: float = Field(default=0.1, description="Minimum similarity score threshold")
    semantic_search_timeout_ms: int = Field(default=5000, description="Semantic search timeout in ms")
    search_timeout_ms: int = Field(default=500, description="Search timeout in milliseconds")
    search_performance_threshold_ms: int = Field(default=200, description="Performance warning threshold")
    
    # Feature Flags
    enable_nlp_parser: bool = Field(default=True, description="Enable NLP parser")
    enable_risk_analyzer: bool = Field(default=True, description="Enable risk analyzer")
    enable_pdf_export: bool = Field(default=True, description="Enable PDF export")
    enable_material_comparison: bool = Field(default=True, description="Enable material comparison")
    enable_miul_checking: bool = Field(default=True, description="Enable MIUL checking")
    enable_mua_checking: bool = Field(default=True, description="Enable MUA checking")
    
    # PFAS Detection Configuration
    pfas_detection_enabled: bool = Field(
        default=False,
        description="Enable PFAS (per- and polyfluoroalkyl substances) detection. Disabled by default pending proper semantic model."
    )
    pfas_detection_mode: str = Field(
        default="conservative",
        description="PFAS detection mode: 'conservative' (high precision) or 'aggressive' (high recall)"
    )
    pfas_keywords: List[str] = Field(
        default=[
            "fluor", "ptfe", "pvdf", "fep", "pfa", "etfe", "pfas",
            "teflon", "viton", "fkm", "fluoroelastomer", "perfluoro",
            "polyfluoro", "fluoropolymer", "fluorocarbon"
        ],
        description="Keywords for PFAS detection"
    )
    pfas_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for PFAS detection (0.0-1.0)"
    )
    pfas_detection_rationale: str = Field(
        default="PFAS detection disabled pending proper semantic model and validation per NASA safety requirements",
        description="Rationale for current PFAS detection configuration"
    )
    
    # Development Settings
    test_mode: bool = Field(default=False, description="Test mode flag")
    use_test_data: bool = Field(default=False, description="Use test data")
    mock_external_services: bool = Field(default=False, description="Mock external services")
    enable_swagger_ui: bool = Field(default=True, description="Enable Swagger UI")
    enable_debug_endpoints: bool = Field(default=True, description="Enable debug endpoints")
    enable_profiling: bool = Field(default=False, description="Enable performance profiling")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
        
    @field_validator("environment", mode="before")
    @classmethod
    def validate_environment(cls, v):
        """Validate and normalize environment value."""
        if isinstance(v, Environment):
            return v.value

        if isinstance(v, str):
            normalized = v.strip().lower()
            aliases = {
                "prod": Environment.PRODUCTION.value,
                "production": Environment.PRODUCTION.value,
                "stage": Environment.STAGING.value,
                "staging": Environment.STAGING.value,
                "stg": Environment.STAGING.value,
                "dev": Environment.DEVELOPMENT.value,
                "development": Environment.DEVELOPMENT.value,
                "test": Environment.TEST.value,
                "testing": Environment.TEST.value,
                "qa": Environment.TEST.value,
            }
            return aliases.get(normalized, normalized)

        return v
        
    @field_validator("port")
    @classmethod
    def validate_port(cls, v):
        """Validate port is in valid range."""
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v
        
    @field_validator("workers")
    @classmethod
    def validate_workers(cls, v):
        """Validate number of workers."""
        if v < 1:
            raise ValueError("Workers must be at least 1")
        return v
        
    @model_validator(mode='after')
    def validate_jwt_secret(self):
        """Validate JWT secret key for production."""
        if self.environment == Environment.PRODUCTION and not os.environ.get("JWT_SECRET_KEY"):
            raise ValueError(
                "JWT_SECRET_KEY environment variable must be set in production. "
                "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
            )
        return self
        
    @model_validator(mode='after')
    def validate_ssl_config(self):
        """Validate SSL configuration for production."""
        if self.environment == Environment.PRODUCTION and not self.ssl_enabled:
            logger.warning("SSL is disabled in production environment")
            
        if self.ssl_enabled:
            if not self.ssl_cert_path:
                raise ValueError("SSL certificate path required when SSL is enabled")
            if not self.ssl_key_path:
                raise ValueError("SSL key path required when SSL is enabled")
                
        return self
        
    @model_validator(mode='after')
    def validate_paths(self):
        """Validate and create required paths."""
        paths_to_check = [
            ("data_path", self.data_path),
            ("upload_path", self.upload_path),
            ("faiss_index_path", self.faiss_index_path),
            ("log_dir", self.log_dir),
        ]
        
        for path_name, path_value in paths_to_check:
            if path_value:
                path = Path(path_value)
                if not path.exists() and not path.is_absolute():
                    # Try to create directory if it doesn't exist
                    try:
                        path.mkdir(parents=True, exist_ok=True)
                        logger.info(f"Created directory: {path}")
                    except Exception as e:
                        logger.warning(f"Could not create directory {path}: {e}")
                        
        return self
        
    @model_validator(mode='after')
    def validate_production_settings(self):
        """Validate critical settings for production environment."""
        if self.environment == Environment.PRODUCTION:
            # Production validations
            if self.debug:
                raise ValueError("Debug mode must be disabled in production")
            if self.reload:
                raise ValueError("Auto-reload must be disabled in production")
            if not self.require_api_key:
                logger.warning("API key requirement is disabled in production")
            if self.enable_debug_endpoints:
                raise ValueError("Debug endpoints must be disabled in production")
            if self.cors_origins == ["*"]:
                raise ValueError("CORS origins must be explicitly set in production")
            # Fail fast if DB credentials are still at development defaults
            if self.postgres_user == "postgres" and not os.environ.get("POSTGRES_USER"):
                raise ValueError(
                    "POSTGRES_USER must be set via environment variable in production"
                )
            if self.postgres_password == "postgres" and not os.environ.get("POSTGRES_PASSWORD"):
                raise ValueError(
                    "POSTGRES_PASSWORD must be set via environment variable in production"
                )

        return self
        
    def get_absolute_path(self, path: str) -> Path:
        """Convert relative path to absolute path based on project root."""
        p = Path(path)
        if not p.is_absolute():
            # Get project root (assuming config.py is in src/utils/)
            project_root = Path(__file__).parent.parent.parent
            p = project_root / p
        return p.resolve()
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return self.model_dump()
        
    def to_json(self, indent: int = 2) -> str:
        """Convert configuration to JSON string."""
        return json.dumps(self.model_dump(), indent=indent, default=str)
        
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == Environment.PRODUCTION
        
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment == Environment.DEVELOPMENT
        
    def get_log_level(self) -> int:
        """Get Python logging level from configuration."""
        return getattr(logging, self.log_level.value)


# Global configuration instance
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """
    Get or create the global configuration instance.
    
    Returns:
        AppConfig: The application configuration
        
    Compliance: SWE-013 (Singleton configuration management)
    """
    global _config
    if _config is None:
        _config = AppConfig()
        logger.info(f"Loaded configuration for environment: {_config.environment}")
    return _config


def reload_config() -> AppConfig:
    """
    Force reload of configuration from environment.
    
    Returns:
        AppConfig: The reloaded configuration
    """
    global _config
    _config = AppConfig()
    logger.info("Configuration reloaded")
    return _config
