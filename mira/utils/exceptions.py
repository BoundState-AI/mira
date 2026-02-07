#!/usr/bin/env python3
"""
Module: Exceptions
Purpose: Copyright (c) 2025 BoundState Inc. All Rights Reserved.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: - SWE-013: Exception handling and error propagation
Safety Critical: True
"""

from __future__ import annotations

__version__ = "3.0.0"
__safety_critical__ = True  # Class B/C: Error handling affects all system operations

import logging
import traceback
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
import json

logger = logging.getLogger(__name__)
error_logger = logging.getLogger("errors")
safety_logger = logging.getLogger("safety")


class ErrorSeverity(str, Enum):
    """NASA error severity levels."""
    CRITICAL = "critical"    # System failure, safety risk
    HIGH = "high"           # Major functionality compromised
    MEDIUM = "medium"       # Partial functionality affected
    LOW = "low"             # Minor issue, workaround available
    INFO = "info"           # Informational only


class ErrorCategory(str, Enum):
    """Error categorization for tracking and analysis."""
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    DATA_INTEGRITY = "data_integrity"
    CONFIGURATION = "configuration"
    EXTERNAL_SERVICE = "external_service"
    RESOURCE = "resource"
    VALIDATION = "validation"
    SECURITY = "security"
    PERFORMANCE = "performance"
    SYSTEM = "system"


class MAPTISException(Exception):
    """Base exception for all MAPTIS-specific errors.
    
    All custom exceptions should inherit from this class to enable
    consistent error handling and logging.
    
    Examples:
        >>> raise MAPTISException(
        ...     "Database connection failed", 
        ...     error_code="DB-001",
        ...     details={"host": "localhost", "port": 5432}
        ... )
    
    Compliance: SWE-061, SWE-134
    """
    
    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        details: dict | None = None,
        req_id: str | None = None
    ):
        """Initialize MAPTIS exception.
        
        Args:
            message: Human-readable error message
            error_code: Machine-readable error code
            details: Additional error details
            req_id: Request ID for tracing
        """
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}
        self.req_id = req_id
        self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> dict:
        """Convert exception to dictionary for API responses."""
        return {
            "error": self.__class__.__name__,
            "error_message": str(self),
            "error_code": self.error_code,
            "details": self.details,
            "req_id": self.req_id,
            "timestamp": self.timestamp.isoformat()
        }


class RateLimitError(MAPTISException):
    """Exception raised when rate limits are exceeded.
    
    Compliance: SWE-055 (Performance protection)
    """
    
    def __init__(
        self,
        message: str = "Rate limit exceeded",
        limit: int | None = None,
        window_seconds: int | None = None,
        retry_after: int | None = None,
        **kwargs
    ):
        """Initialize rate limit error.
        
        Args:
            message: Error message
            limit: Number of requests allowed
            window_seconds: Time window in seconds
            retry_after: Seconds to wait before retrying
            **kwargs: Additional arguments for parent class
        """
        super().__init__(message, error_code="RATE_LIMIT_EXCEEDED", **kwargs)
        self.limit = limit
        self.window_seconds = window_seconds
        self.retry_after = retry_after
        
        # Add rate limit details
        self.details.update({
            "limit": limit,
            "window_seconds": window_seconds,
            "retry_after": retry_after
        })


class InputValidationError(MAPTISException):
    """Invalid input data provided."""
    def __init__(self, message: str, field: str | None = None, **kwargs):
        super().__init__(message, error_code="INVALID_INPUT", **kwargs)
        self.field = field
        if field:
            self.details["field"] = field


class NotFoundError(MAPTISException):
    """Requested resource not found."""
    def __init__(self, message: str, resource_type: str | None = None, resource_id: str | None = None, **kwargs):
        super().__init__(message, error_code="NOT_FOUND", **kwargs)
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.details.update({
            "resource_type": resource_type,
            "resource_id": resource_id
        })


class PermissionDeniedError(MAPTISException):
    """Permission denied for requested operation."""
    def __init__(self, message: str, required_permission: str | None = None, **kwargs):
        super().__init__(message, error_code="PERMISSION_DENIED", **kwargs)
        self.required_permission = required_permission
        if required_permission:
            self.details["required_permission"] = required_permission


class ServiceUnavailableError(MAPTISException):
    """Service temporarily unavailable."""
    def __init__(self, message: str, service_name: str | None = None, retry_after: int | None = None, **kwargs):
        super().__init__(message, error_code="SERVICE_UNAVAILABLE", **kwargs)
        self.service_name = service_name
        self.retry_after = retry_after
        self.details.update({
            "service_name": service_name,
            "retry_after": retry_after
        })


class ExternalServiceError(MAPTISException):
    """External service integration error."""
    def __init__(self, message: str, service: str | None = None, status_code: int | None = None, **kwargs):
        super().__init__(message, error_code="EXTERNAL_SERVICE_ERROR", **kwargs)
        self.service = service
        self.status_code = status_code
        self.details.update({
            "service": service,
            "status_code": status_code
        })


class SecurityError(MAPTISException):
    """Base class for security-related errors."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, error_code="SECURITY_ERROR", **kwargs)


class AuthenticationError(SecurityError):
    """Authentication failed."""
    def __init__(self, message: str = "Authentication failed", **kwargs):
        super().__init__(message, **kwargs)
        self.error_code = "AUTHENTICATION_FAILED"


class AuthorizationError(SecurityError):
    """Authorization failed."""
    def __init__(self, message: str = "Authorization failed", **kwargs):
        super().__init__(message, **kwargs)
        self.error_code = "AUTHORIZATION_FAILED"


def raise_security_error(
    error_class: type[Exception],
    message: str,
    req_id: str | None = None,
    user_id: str | None = None,
    action: str | None = None,
    **kwargs
) -> None:
    """Raise a security error with proper logging and context.
    
    Args:
        error_class: The exception class to raise
        message: Error message
        req_id: Request ID for tracing
        user_id: User ID if available
        action: Action that was attempted
        **kwargs: Additional context for the error
        
    Compliance: SWE-134, NASA-STD-8739.8B (Security event logging)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Log security event
    logger.error(
        f"SECURITY_ERROR: {error_class.__name__} - {message}",
        extra={
            "req_id": req_id,
            "user_id": user_id,
            "action": action,
            "error_type": error_class.__name__,
            **kwargs
        }
    )
    
    # Prepare error kwargs
    error_kwargs = {
        "req_id": req_id,
        **kwargs
    }
    
    # Add user_id to details if available
    if user_id:
        if "details" not in error_kwargs:
            error_kwargs["details"] = {}
        error_kwargs["details"]["user_id"] = user_id
        error_kwargs["details"]["action"] = action
    
    # Raise the error
    raise error_class(message, **error_kwargs)


class SafetyCriticalError(Exception):
    """
    Base exception class for all safety-critical errors in MAPTIS.
    
    Compliance: SWE-134 (Safety-critical error management)
    """
    
    def __init__(
        self,
        message: str,
        error_code: str,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        category: ErrorCategory = ErrorCategory.SYSTEM,
        details: Optional[Dict[str, Any]] = None,
        recovery_suggestions: Optional[List[str]] = None,
        nasa_compliance_ref: Optional[str] = None
    ):
        """
        Initialize safety-critical error.
        
        Args:
            message: Human-readable error message
            error_code: Unique error code (e.g., "MAPTIS-AUTH-001")
            severity: Error severity level
            category: Error category for classification
            details: Additional error details
            recovery_suggestions: List of recovery actions
            nasa_compliance_ref: NASA compliance reference
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.severity = severity
        self.category = category
        self.details = details or {}
        self.recovery_suggestions = recovery_suggestions or []
        self.nasa_compliance_ref = nasa_compliance_ref
        self.timestamp = datetime.utcnow()
        self.traceback = traceback.format_exc()
        
        # Log the error based on severity
        self._log_error()
    
    def _log_error(self):
        """Log error with appropriate severity."""
        log_data = self.to_dict()
        
        if self.severity == ErrorSeverity.CRITICAL:
            safety_logger.critical(f"CRITICAL ERROR: {self.error_code}", extra=log_data)
            error_logger.critical(self.message, extra=log_data)
        elif self.severity == ErrorSeverity.HIGH:
            safety_logger.error(f"HIGH SEVERITY ERROR: {self.error_code}", extra=log_data)
            error_logger.error(self.message, extra=log_data)
        elif self.severity == ErrorSeverity.MEDIUM:
            error_logger.warning(self.message, extra=log_data)
        else:
            error_logger.info(self.message, extra=log_data)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for logging/serialization."""
        return {
            "error_code": self.error_code,
            "error_message": self.message,
            "severity": self.severity.value,
            "category": self.category.value,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
            "recovery_suggestions": self.recovery_suggestions,
            "nasa_compliance_ref": self.nasa_compliance_ref,
            "traceback": self.traceback
        }
    
    def to_response(self) -> Dict[str, Any]:
        """Convert to API response format (without sensitive data)."""
        return {
            "error": {
                "code": self.error_code,
                "message": self.message,
                "severity": self.severity.value,
                "category": self.category.value,
                "timestamp": self.timestamp.isoformat(),
                "recovery_suggestions": self.recovery_suggestions
            }
        }


# Authentication and Authorization Errors

class AuthenticationError(SafetyCriticalError):
    """Authentication failure errors."""
    
    def __init__(
        self,
        message: str,
        auth_method: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs
    ):
        details = kwargs.pop("details", {})
        details.update({
            "auth_method": auth_method,
            "user_id": user_id
        })
        
        super().__init__(
            message=message,
            error_code="MAPTIS-AUTH-001",
            severity=ErrorSeverity.HIGH,
            category=ErrorCategory.AUTHENTICATION,
            details=details,
            recovery_suggestions=[
                "Verify credentials are correct",
                "Check if account is active",
                "Contact system administrator if issue persists"
            ],
            nasa_compliance_ref="SWE-042",
            **kwargs
        )


class AuthorizationError(SafetyCriticalError):
    """Authorization/permission errors."""
    
    def __init__(
        self,
        message: str,
        required_permission: Optional[str] = None,
        user_role: Optional[str] = None,
        resource: Optional[str] = None,
        **kwargs
    ):
        details = kwargs.pop("details", {})
        details.update({
            "required_permission": required_permission,
            "user_role": user_role,
            "resource": resource
        })
        
        super().__init__(
            message=message,
            error_code="MAPTIS-AUTH-002",
            severity=ErrorSeverity.MEDIUM,
            category=ErrorCategory.AUTHORIZATION,
            details=details,
            recovery_suggestions=[
                "Request appropriate permissions from administrator",
                "Verify you're accessing the correct resource",
                "Check your role assignments"
            ],
            nasa_compliance_ref="SWE-042",
            **kwargs
        )


class SecurityError(SafetyCriticalError):
    """Security-related errors."""
    
    def __init__(
        self,
        message: str,
        security_event: str,
        client_info: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        details = kwargs.pop("details", {})
        details.update({
            "security_event": security_event,
            "client_info": client_info or {}
        })
        
        super().__init__(
            message=message,
            error_code="MAPTIS-SEC-001",
            severity=ErrorSeverity.CRITICAL,
            category=ErrorCategory.SECURITY,
            details=details,
            recovery_suggestions=[
                "Contact security administrator immediately",
                "Review recent account activity",
                "Change credentials if compromised"
            ],
            nasa_compliance_ref="NASA-STD-8739.8B",
            **kwargs
        )


# Data and Resource Errors

class DataIntegrityError(SafetyCriticalError):
    """Data integrity and validation errors."""
    
    def __init__(
        self,
        message: str,
        data_type: Optional[str] = None,
        validation_errors: Optional[List[str]] = None,
        affected_records: Optional[int] = None,
        **kwargs
    ):
        details = kwargs.pop("details", {})
        details.update({
            "data_type": data_type,
            "validation_errors": validation_errors or [],
            "affected_records": affected_records
        })
        
        super().__init__(
            message=message,
            error_code="MAPTIS-DATA-001",
            severity=ErrorSeverity.HIGH,
            category=ErrorCategory.DATA_INTEGRITY,
            details=details,
            recovery_suggestions=[
                "Verify data format and structure",
                "Check for data corruption",
                "Restore from backup if necessary",
                "Run data validation tools"
            ],
            nasa_compliance_ref="SWE-032",
            **kwargs
        )


class ResourceNotFoundError(SafetyCriticalError):
    """Resource not found errors."""
    
    def __init__(
        self,
        message: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        search_criteria: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        details = kwargs.pop("details", {})
        details.update({
            "resource_type": resource_type,
            "resource_id": resource_id,
            "search_criteria": search_criteria or {}
        })
        
        super().__init__(
            message=message,
            error_code="MAPTIS-RES-001",
            severity=ErrorSeverity.LOW,
            category=ErrorCategory.RESOURCE,
            details=details,
            recovery_suggestions=[
                "Verify resource identifier is correct",
                "Check if resource has been deleted",
                "Try alternative search criteria"
            ],
            **kwargs
        )


class ResourceExhaustedError(SafetyCriticalError):
    """Resource exhaustion errors (memory, disk, connections)."""
    
    def __init__(
        self,
        message: str,
        resource_name: str,
        current_usage: Optional[float] = None,
        limit: Optional[float] = None,
        **kwargs
    ):
        details = kwargs.pop("details", {})
        details.update({
            "resource_name": resource_name,
            "current_usage": current_usage,
            "limit": limit,
            "usage_percentage": (current_usage / limit * 100) if (current_usage and limit) else None
        })
        
        super().__init__(
            message=message,
            error_code="MAPTIS-RES-002",
            severity=ErrorSeverity.CRITICAL,
            category=ErrorCategory.RESOURCE,
            details=details,
            recovery_suggestions=[
                "Free up system resources",
                "Scale up infrastructure",
                "Optimize resource usage",
                "Contact system administrator"
            ],
            nasa_compliance_ref="SWE-134",
            **kwargs
        )


# Configuration and System Errors

class ConfigurationError(SafetyCriticalError):
    """Configuration-related errors."""
    
    def __init__(
        self,
        message: str,
        config_key: Optional[str] = None,
        expected_type: Optional[str] = None,
        actual_value: Optional[Any] = None,
        **kwargs
    ):
        details = kwargs.pop("details", {})
        details.update({
            "config_key": config_key,
            "expected_type": expected_type,
            "actual_value": str(actual_value) if actual_value is not None else None
        })
        
        super().__init__(
            message=message,
            error_code="MAPTIS-CFG-001",
            severity=ErrorSeverity.HIGH,
            category=ErrorCategory.CONFIGURATION,
            details=details,
            recovery_suggestions=[
                "Check configuration file syntax",
                "Verify environment variables are set",
                "Use configuration template as reference",
                "Review configuration documentation"
            ],
            nasa_compliance_ref="SWE-032",
            **kwargs
        )


class ExternalServiceError(SafetyCriticalError):
    """External service integration errors."""
    
    def __init__(
        self,
        message: str,
        service_name: str,
        endpoint: Optional[str] = None,
        status_code: Optional[int] = None,
        response_time: Optional[float] = None,
        **kwargs
    ):
        details = kwargs.pop("details", {})
        details.update({
            "service_name": service_name,
            "endpoint": endpoint,
            "status_code": status_code,
            "response_time": response_time
        })
        
        super().__init__(
            message=message,
            error_code="MAPTIS-EXT-001",
            severity=ErrorSeverity.MEDIUM,
            category=ErrorCategory.EXTERNAL_SERVICE,
            details=details,
            recovery_suggestions=[
                "Check service status page",
                "Verify network connectivity",
                "Try again with exponential backoff",
                "Use fallback service if available"
            ],
            **kwargs
        )


class ValidationError(SafetyCriticalError):
    """Input validation errors."""
    
    def __init__(
        self,
        message: str,
        field_errors: Optional[Dict[str, List[str]]] = None,
        input_data: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        details = kwargs.pop("details", {})
        details.update({
            "field_errors": field_errors or {},
            "input_summary": {k: type(v).__name__ for k, v in (input_data or {}).items()}
        })
        
        super().__init__(
            message=message,
            error_code="MAPTIS-VAL-001",
            severity=ErrorSeverity.LOW,
            category=ErrorCategory.VALIDATION,
            details=details,
            recovery_suggestions=[
                "Review input requirements",
                "Check data types and formats",
                "Ensure required fields are provided"
            ],
            **kwargs
        )


class PerformanceError(SafetyCriticalError):
    """Performance-related errors."""
    
    def __init__(
        self,
        message: str,
        operation: str,
        elapsed_time: Optional[float] = None,
        threshold: Optional[float] = None,
        **kwargs
    ):
        details = kwargs.pop("details", {})
        details.update({
            "operation": operation,
            "elapsed_time": elapsed_time,
            "threshold": threshold,
            "exceeded_by": (elapsed_time - threshold) if (elapsed_time and threshold) else None
        })
        
        super().__init__(
            message=message,
            error_code="MAPTIS-PERF-001",
            severity=ErrorSeverity.MEDIUM,
            category=ErrorCategory.PERFORMANCE,
            details=details,
            recovery_suggestions=[
                "Optimize query parameters",
                "Use pagination for large results",
                "Check system load",
                "Consider caching strategies"
            ],
            **kwargs
        )


class CacheError(SafetyCriticalError):
    """Cache-related errors."""
    
    def __init__(
        self,
        message: str,
        cache_type: str,
        operation: Optional[str] = None,
        key: Optional[str] = None,
        **kwargs
    ):
        details = kwargs.pop("details", {})
        details.update({
            "cache_type": cache_type,
            "operation": operation,
            "key": key
        })
        
        super().__init__(
            message=message,
            error_code="MAPTIS-CACHE-001",
            severity=ErrorSeverity.LOW,
            category=ErrorCategory.PERFORMANCE,
            details=details,
            recovery_suggestions=[
                "Check cache service connectivity",
                "Verify cache configuration",
                "Clear cache if corrupted",
                "Fall back to direct queries"
            ],
            nasa_compliance_ref="SWE-055",
            **kwargs
        )


# Specialized Material Processing Errors

class MaterialProcessingError(SafetyCriticalError):
    """Material data processing errors."""
    
    def __init__(
        self,
        message: str,
        material_id: Optional[str] = None,
        processing_stage: Optional[str] = None,
        **kwargs
    ):
        details = kwargs.pop("details", {})
        details.update({
            "material_id": material_id,
            "processing_stage": processing_stage
        })
        
        super().__init__(
            message=message,
            error_code="MAPTIS-MAT-001",
            severity=ErrorSeverity.HIGH,
            category=ErrorCategory.DATA_INTEGRITY,
            details=details,
            recovery_suggestions=[
                "Verify material data format",
                "Check material property calculations",
                "Review processing pipeline logs"
            ],
            nasa_compliance_ref="SWE-134",
            **kwargs
        )


class FAISSIndexError(SafetyCriticalError):
    """FAISS vector index errors."""
    
    def __init__(
        self,
        message: str,
        index_operation: str,
        index_size: Optional[int] = None,
        vector_dimension: Optional[int] = None,
        **kwargs
    ):
        details = kwargs.pop("details", {})
        details.update({
            "index_operation": index_operation,
            "index_size": index_size,
            "vector_dimension": vector_dimension
        })
        
        super().__init__(
            message=message,
            error_code="MAPTIS-FAISS-001",
            severity=ErrorSeverity.CRITICAL,
            category=ErrorCategory.SYSTEM,
            details=details,
            recovery_suggestions=[
                "Rebuild FAISS index",
                "Check vector dimensions match",
                "Verify index file integrity",
                "Ensure sufficient memory available"
            ],
            nasa_compliance_ref="SWE-134",
            **kwargs
        )


# Error Handler Utilities

class ErrorHandler:
    """Centralized error handling utilities."""
    
    @staticmethod
    def handle_and_log(error: Exception, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Handle and log any exception, converting to SafetyCriticalError if needed.
        
        Args:
            error: The exception to handle
            context: Additional context information
            
        Returns:
            Error response dictionary suitable for API responses
            
        Examples:
            >>> try:
            ...     risky_operation()
            ... except Exception as e:
            ...     response = ErrorHandler.handle_and_log(e, {"operation": "search"})
            ...     return JSONResponse(status_code=500, content=response)
            
        Compliance: SWE-013 (Exception handling), SWE-134 (Safety-critical management)
        """
        if isinstance(error, SafetyCriticalError):
            # Already a safety-critical error
            return error.to_response()
        
        # Convert to SafetyCriticalError
        safety_error = SafetyCriticalError(
            message=str(error),
            error_code="MAPTIS-SYS-999",
            severity=ErrorSeverity.MEDIUM,
            category=ErrorCategory.SYSTEM,
            details={
                "original_error_type": type(error).__name__,
                "context": context or {}
            },
            recovery_suggestions=[
                "Check system logs for details",
                "Contact technical support"
            ]
        )
        
        return safety_error.to_response()
    
    @staticmethod
    def create_error_report(
        errors: List[SafetyCriticalError],
        report_type: str = "summary"
    ) -> Dict[str, Any]:
        """
        Create an error report from multiple errors.
        
        Args:
            errors: List of SafetyCriticalError instances
            report_type: Type of report ("summary" or "detailed")
            
        Returns:
            Error report dictionary
        """
        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "total_errors": len(errors),
            "by_severity": {},
            "by_category": {},
            "errors": []
        }
        
        # Count by severity and category
        for error in errors:
            severity = error.severity.value
            category = error.category.value
            
            report["by_severity"][severity] = report["by_severity"].get(severity, 0) + 1
            report["by_category"][category] = report["by_category"].get(category, 0) + 1
            
            if report_type == "detailed":
                report["errors"].append(error.to_dict())
            else:
                report["errors"].append({
                    "code": error.error_code,
                    "message": error.message,
                    "timestamp": error.timestamp.isoformat()
                })
        
        return report


# Helper function for raising errors with context
def raise_safety_error(
    error_class: type,
    message: str,
    **kwargs
) -> None:
    """
    Raise a safety-critical error with additional context.
    
    Automatically adds caller information for debugging.
    
    Args:
        error_class: The error class to raise
        message: Error message
        **kwargs: Additional arguments for the error class
        
    Examples:
        >>> raise_safety_error(
        ...     ValidationError,
        ...     "Invalid material ID format",
        ...     field_errors={"material_id": ["Must start with MAT-"]}
        ... )
        
        >>> raise_safety_error(
        ...     FAISSIndexError,
        ...     "Index loading failed",
        ...     index_operation="load",
        ...     index_size=9996
        ... )
        
    Compliance: SWE-013 (Exception handling), SWE-134 (Safety-critical management)
    """
    # Add caller information
    import inspect
    frame = inspect.currentframe()
    if frame and frame.f_back:
        caller_info = inspect.getframeinfo(frame.f_back)
        kwargs.setdefault("details", {}).update({
            "caller_file": caller_info.filename,
            "caller_function": caller_info.function,
            "caller_line": caller_info.lineno
        })
    
    raise error_class(message, **kwargs)


__all__ = [
    # Base class
    "SafetyCriticalError",
    
    # Enums
    "ErrorSeverity",
    "ErrorCategory",
    
    # Error classes
    "AuthenticationError",
    "AuthorizationError",
    "SecurityError",
    "DataIntegrityError",
    "ResourceNotFoundError",
    "ResourceExhaustedError",
    "ConfigurationError",
    "ExternalServiceError",
    "ValidationError",
    "PerformanceError",
    "CacheError",
    "MaterialProcessingError",
    "FAISSIndexError",
    
    # Utilities
    "ErrorHandler",
    "raise_safety_error"
]
