#!/usr/bin/env python3
"""
Module: Logging Config
Purpose: Copyright (c) 2025 BoundState Inc. All Rights Reserved.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: - SWE-013: Comprehensive logging and audit trails
Safety Critical: True
"""

from __future__ import annotations

__safety_critical__ = True  # Class B/C: Logging is critical for system auditing

import logging
import logging.handlers
import json
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
try:
    from pythonjsonlogger import jsonlogger
    HAS_JSONLOGGER = True
except ImportError:
    HAS_JSONLOGGER = False
    jsonlogger = None

try:
    import colorlog
    HAS_COLORLOG = True
except ImportError:
    HAS_COLORLOG = False
    colorlog = None

from .config import get_config


class NASAComplianceFilter(logging.Filter):
    """Add NASA compliance fields to all log records."""
    
    def filter(self, record):
        """Add NASA-specific fields to log record."""
        # Add NASA compliance fields
        record.nasa_site = get_config().nasa_site
        record.nasa_project = get_config().nasa_program
        record.nasa_safety_class = get_config().nasa_software_class
        record.nasa_compliance = "SWE-013/NASA-STD-8739.8B"

        # Add system context
        record.system = "MAPTIS-NLP"
        record.version = "3.0.0"
        record.environment = get_config().environment
        
        # Add security context if available
        if hasattr(record, "request"):
            record.client_ip = getattr(record.request, "client_ip", "unknown")
            record.user_id = getattr(record.request, "user_id", "anonymous")
            
        return True


if HAS_JSONLOGGER:
    class SafetyCriticalFormatter(jsonlogger.JsonFormatter):
        """Custom JSON formatter for safety-critical systems."""

        def add_fields(self, log_record, record, message_dict):
            """Add custom fields to log record."""
            super().add_fields(log_record, record, message_dict)

            # Add timestamp in ISO format
            log_record['timestamp'] = datetime.utcnow().isoformat()

            # Add log level name
            log_record['level'] = record.levelname

            # Add source location
            log_record['source'] = {
                'file': record.pathname,
                'line': record.lineno,
                'function': record.funcName,
                'module': record.module
            }

            # Add thread/process info for debugging
            log_record['execution'] = {
                'process': record.process,
                'process_name': record.processName,
                'thread': record.thread,
                'thread_name': record.threadName
            }

            # Move NASA fields to compliance section
            if hasattr(record, 'nasa_site'):
                log_record['compliance'] = {
                    'nasa_site': record.nasa_site,
                    'nasa_project': record.nasa_project,
                    'safety_class': record.nasa_safety_class,
                    'standards': record.nasa_compliance
                }


    class PerformanceLogFormatter(jsonlogger.JsonFormatter):
        """Specialized formatter for performance logs."""

        def add_fields(self, log_record, record, message_dict):
            """Add performance-specific fields."""
            super().add_fields(log_record, record, message_dict)

            # Extract performance metrics
            if hasattr(record, 'duration_ms'):
                log_record['performance'] = {
                    'duration_ms': record.duration_ms,
                    'memory_delta_mb': getattr(record, 'memory_delta_mb', None),
                    'cpu_percent': getattr(record, 'cpu_percent', None)
                }

            # Add operation context
            if hasattr(record, 'operation'):
                log_record['operation'] = record.operation

            log_record['timestamp'] = datetime.utcnow().isoformat()


    class SecurityAuditFormatter(jsonlogger.JsonFormatter):
        """Specialized formatter for security audit logs."""

        def add_fields(self, log_record, record, message_dict):
            """Add security audit fields."""
            super().add_fields(log_record, record, message_dict)

            # Security event details
            if hasattr(record, 'event_type'):
                log_record['security_event'] = {
                    'type': record.event_type,
                    'severity': getattr(record, 'severity', 'INFO'),
                    'timestamp': datetime.utcnow().isoformat()
                }

            # Actor information
            if hasattr(record, 'user_id'):
                log_record['actor'] = {
                    'user_id': record.user_id,
                    'username': getattr(record, 'username', None),
                    'role': getattr(record, 'role', None),
                    'client_ip': getattr(record, 'client_ip', None)
                }

            # Resource information
            if hasattr(record, 'resource'):
                log_record['resource'] = record.resource
else:
    # Fallback to basic formatters if jsonlogger not available
    def _make_basic_formatter():
        return logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    # Create simple wrapper classes that return basic formatters
    class SafetyCriticalFormatter:
        def __new__(cls):
            return _make_basic_formatter()

    class PerformanceLogFormatter:
        def __new__(cls):
            return _make_basic_formatter()

    class SecurityAuditFormatter:
        def __new__(cls):
            return _make_basic_formatter()


def setup_logging(
    log_level: str = "INFO",
    log_dir: Optional[str] = None,
    enable_console: bool = True,
    enable_file: bool = True,
    enable_syslog: bool = False,
    max_bytes: int = 100 * 1024 * 1024,  # 100MB
    backup_count: int = 10
) -> Dict[str, logging.Logger]:
    """
    Setup comprehensive logging configuration for MAPTIS.
    
    Args:
        log_level: Default log level
        log_dir: Directory for log files
        enable_console: Enable console logging
        enable_file: Enable file logging
        enable_syslog: Enable syslog logging
        max_bytes: Max size for log files
        backup_count: Number of backup files to keep
        
    Returns:
        Dictionary of configured loggers
    """
    
    # Create log directory if needed
    if log_dir is None:
        log_dir = get_config().get_absolute_path(get_config().log_dir)
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    # Define log files
    log_files = {
        'general': log_path / 'maptis.log',
        'errors': log_path / 'errors.log',
        'security': log_path / 'security.log',
        'performance': log_path / 'performance.log',
        'metrics': log_path / 'metrics.log',
        'safety': log_path / 'safety_critical.log'
    }
    
    # Create NASA compliance filter
    nasa_filter = NASAComplianceFilter()
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Console handler with color support
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level.upper()))
        
        if HAS_COLORLOG and sys.stdout.isatty():  # Use colors if terminal and colorlog available
            console_format = colorlog.ColoredFormatter(
                "%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt='%Y-%m-%d %H:%M:%S',
                log_colors={
                    'DEBUG': 'cyan',
                    'INFO': 'green',
                    'WARNING': 'yellow',
                    'ERROR': 'red',
                    'CRITICAL': 'red,bg_white',
                }
            )
            console_handler.setFormatter(console_format)
        else:
            console_format = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            console_handler.setFormatter(console_format)
            
        console_handler.addFilter(nasa_filter)
        root_logger.addHandler(console_handler)
    
    # File handlers
    handlers = {}
    
    if enable_file:
        # General application log
        general_handler = logging.handlers.RotatingFileHandler(
            log_files['general'],
            maxBytes=max_bytes,
            backupCount=backup_count
        )
        general_handler.setLevel(logging.INFO)
        general_handler.setFormatter(SafetyCriticalFormatter())
        general_handler.addFilter(nasa_filter)
        handlers['general'] = general_handler
        
        # Error log
        error_handler = logging.handlers.RotatingFileHandler(
            log_files['errors'],
            maxBytes=max_bytes,
            backupCount=backup_count
        )
        error_handler.setLevel(logging.WARNING)
        error_handler.setFormatter(SafetyCriticalFormatter())
        error_handler.addFilter(nasa_filter)
        handlers['errors'] = error_handler
        
        # Security audit log
        security_handler = logging.handlers.RotatingFileHandler(
            log_files['security'],
            maxBytes=max_bytes,
            backupCount=backup_count * 2  # Keep more security logs
        )
        security_handler.setLevel(logging.INFO)
        security_handler.setFormatter(SecurityAuditFormatter())
        security_handler.addFilter(nasa_filter)
        handlers['security'] = security_handler
        
        # Performance log
        perf_handler = logging.handlers.RotatingFileHandler(
            log_files['performance'],
            maxBytes=max_bytes,
            backupCount=backup_count
        )
        perf_handler.setLevel(logging.INFO)
        perf_handler.setFormatter(PerformanceLogFormatter())
        handlers['performance'] = perf_handler
        
        # Metrics log (for aggregation)
        metrics_handler = logging.handlers.RotatingFileHandler(
            log_files['metrics'],
            maxBytes=max_bytes,
            backupCount=backup_count
        )
        metrics_handler.setLevel(logging.INFO)
        metrics_handler.setFormatter(PerformanceLogFormatter())
        handlers['metrics'] = metrics_handler
        
        # Safety-critical log
        safety_handler = logging.handlers.RotatingFileHandler(
            log_files['safety'],
            maxBytes=max_bytes,
            backupCount=backup_count * 3  # Keep more safety logs
        )
        safety_handler.setLevel(logging.WARNING)
        safety_handler.setFormatter(SafetyCriticalFormatter())
        safety_handler.addFilter(nasa_filter)
        handlers['safety'] = safety_handler
    
    # Syslog handler (for centralized logging)
    if enable_syslog and sys.platform != 'win32':
        syslog_handler = logging.handlers.SysLogHandler(
            address=('localhost', 514),
            facility=logging.handlers.SysLogHandler.LOG_LOCAL0
        )
        syslog_handler.setLevel(logging.WARNING)
        syslog_format = logging.Formatter(
            'MAPTIS[%(process)d]: %(levelname)s - %(message)s'
        )
        syslog_handler.setFormatter(syslog_format)
        handlers['syslog'] = syslog_handler
    
    # Configure specialized loggers
    loggers = {}
    
    # General application logger
    app_logger = logging.getLogger('maptis')
    app_logger.setLevel(logging.DEBUG)
    app_logger.propagate = False
    if 'general' in handlers:
        app_logger.addHandler(handlers['general'])
    if 'errors' in handlers:
        app_logger.addHandler(handlers['errors'])
    loggers['app'] = app_logger
    
    # Error logger
    error_logger = logging.getLogger('errors')
    error_logger.setLevel(logging.WARNING)
    error_logger.propagate = False
    if 'errors' in handlers:
        error_logger.addHandler(handlers['errors'])
    if 'safety' in handlers:
        error_logger.addHandler(handlers['safety'])
    loggers['errors'] = error_logger
    
    # Security logger
    security_logger = logging.getLogger('security')
    security_logger.setLevel(logging.INFO)
    security_logger.propagate = False
    if 'security' in handlers:
        security_logger.addHandler(handlers['security'])
    if enable_syslog and 'syslog' in handlers:
        security_logger.addHandler(handlers['syslog'])
    loggers['security'] = security_logger
    
    # Performance logger
    perf_logger = logging.getLogger('performance')
    perf_logger.setLevel(logging.INFO)
    perf_logger.propagate = False
    if 'performance' in handlers:
        perf_logger.addHandler(handlers['performance'])
    loggers['performance'] = perf_logger
    
    # Metrics logger
    metrics_logger = logging.getLogger('metrics')
    metrics_logger.setLevel(logging.INFO)
    metrics_logger.propagate = False
    if 'metrics' in handlers:
        metrics_logger.addHandler(handlers['metrics'])
    loggers['metrics'] = metrics_logger
    
    # Safety logger
    safety_logger = logging.getLogger('safety')
    safety_logger.setLevel(logging.WARNING)
    safety_logger.propagate = False
    if 'safety' in handlers:
        safety_logger.addHandler(handlers['safety'])
    if enable_syslog and 'syslog' in handlers:
        safety_logger.addHandler(handlers['syslog'])
    loggers['safety'] = safety_logger
    
    # Add file handlers to root logger
    if enable_file:
        root_logger.addHandler(handlers['general'])
    
    # Log startup message
    app_logger.info(
        "MAPTIS NLP Platform logging initialized",
        extra={
            "log_level": log_level,
            "log_dir": str(log_path),
            "handlers": list(handlers.keys()),
            "environment": get_config().environment
        }
    )
    
    return loggers


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with NASA compliance.
    
    Args:
        name: Logger name (usually __name__)
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    
    # Ensure NASA filter is applied
    if not any(isinstance(f, NASAComplianceFilter) for f in logger.filters):
        logger.addFilter(NASAComplianceFilter())
        
    return logger


def log_exception(logger: logging.Logger, 
                 error: Exception,
                 context: Optional[Dict[str, Any]] = None,
                 user_id: Optional[str] = None):
    """
    Log an exception with full context.
    
    Args:
        logger: Logger instance
        error: Exception to log
        context: Additional context
        user_id: User ID if available
    """
    import traceback
    
    error_data = {
        'error_type': type(error).__name__,
        'error_message': str(error),
        'traceback': traceback.format_exc(),
        'context': context or {}
    }
    
    if user_id:
        error_data['user_id'] = user_id
        
    logger.error(
        f"Exception occurred: {type(error).__name__}",
        extra=error_data,
        exc_info=True
    )


def create_audit_log_entry(
    event_type: str,
    user_id: str,
    resource: str,
    action: str,
    result: str,
    details: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create a standardized audit log entry.
    
    Args:
        event_type: Type of event
        user_id: User performing action
        resource: Resource being accessed
        action: Action performed
        result: Result of action
        details: Additional details
        
    Returns:
        Audit log entry dictionary
    """
    return {
        'audit_event': {
            'type': event_type,
            'timestamp': datetime.utcnow().isoformat(),
            'user_id': user_id,
            'resource': resource,
            'action': action,
            'result': result,
            'details': details or {},
            'compliance': {
                'standard': 'NASA-STD-8739.8B',
                'requirement': 'SWE-013'
            }
        }
    }


# Logging level configuration for different environments
ENVIRONMENT_LOG_LEVELS = {
    'development': {
        'default': 'DEBUG',
        'security': 'INFO',
        'performance': 'DEBUG',
        'third_party': 'WARNING'
    },
    'staging': {
        'default': 'INFO',
        'security': 'INFO',
        'performance': 'INFO',
        'third_party': 'WARNING'
    },
    'production': {
        'default': 'WARNING',
        'security': 'INFO',
        'performance': 'INFO',
        'third_party': 'ERROR'
    }
}


def configure_third_party_logging():
    """Configure logging levels for third-party libraries."""
    env = get_config().environment
    levels = ENVIRONMENT_LOG_LEVELS.get(env, ENVIRONMENT_LOG_LEVELS['production'])
    
    # Reduce noise from third-party libraries
    logging.getLogger('urllib3').setLevel(levels['third_party'])
    logging.getLogger('requests').setLevel(levels['third_party'])
    logging.getLogger('asyncio').setLevel(levels['third_party'])
    logging.getLogger('faiss').setLevel(levels['third_party'])
    logging.getLogger('sentence_transformers').setLevel(levels['third_party'])
    logging.getLogger('transformers').setLevel(levels['third_party'])
    logging.getLogger('torch').setLevel(levels['third_party'])


# Initialize logging on import
def initialize_logging():
    """Initialize logging configuration on module import."""
    env = get_config().environment
    levels = ENVIRONMENT_LOG_LEVELS.get(env, ENVIRONMENT_LOG_LEVELS['production'])
    
    setup_logging(
        log_level=levels['default'],
        enable_console=True,
        enable_file=True,
        enable_syslog=(env == 'production')
    )
    
    configure_third_party_logging()


# Initialize logging when module is imported
initialize_logging()


__all__ = [
    'setup_logging',
    'get_logger',
    'log_exception',
    'create_audit_log_entry',
    'NASAComplianceFilter',
    'SafetyCriticalFormatter',
    'PerformanceLogFormatter',
    'SecurityAuditFormatter'
]
