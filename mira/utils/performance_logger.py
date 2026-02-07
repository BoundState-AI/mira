#!/usr/bin/env python3
"""
Module: Performance Logger
Purpose: Copyright (c) 2025 BoundState Inc. All Rights Reserved.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: - SWE-013: Performance monitoring and logging
Safety Critical: True
"""

from __future__ import annotations

__safety_critical__ = True  # Class B/C: Performance monitoring affects system reliability

import time
import logging

# Handle optional psutil dependency
try:
    import psutil
except ImportError:
    # Fallback: Create mock psutil module
    class MockProcess:
        def memory_info(self):
            class MemInfo:
                rss = 0
            return MemInfo()

    class MockPsutil:
        @staticmethod
        def Process():
            return MockProcess()

        @staticmethod
        def cpu_percent(interval=None):
            return 0.0

        @staticmethod
        def cpu_count():
            return 1

        @staticmethod
        def virtual_memory():
            class MemInfo:
                total = 0
                used = 0
                available = 0
                percent = 0.0
            return MemInfo()

        @staticmethod
        def disk_usage(path):
            class DiskInfo:
                total = 0
                used = 0
                free = 0
                percent = 0.0
            return DiskInfo()

    psutil = MockPsutil()
from typing import Optional, Dict, Any, List, Callable, Union
from datetime import datetime, timedelta
from contextlib import contextmanager
from functools import wraps
import asyncio
import json
import threading
from collections import defaultdict, deque
import statistics

from .exceptions import PerformanceError, ErrorSeverity

logger = logging.getLogger(__name__)
perf_logger = logging.getLogger("performance")
metrics_logger = logging.getLogger("metrics")


class PerformanceMetrics:
    """Container for performance metrics."""
    
    def __init__(self):
        self.start_time: float = 0
        self.end_time: float = 0
        self.duration: float = 0
        self.memory_start: float = 0
        self.memory_end: float = 0
        self.memory_delta: float = 0
        self.cpu_percent: float = 0
        self.operation_name: str = ""
        self.tags: Dict[str, Any] = {}
        self.success: bool = True
        self.error: Optional[str] = None
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "operation": self.operation_name,
            "duration_ms": round(self.duration * 1000, 2),
            "memory_delta_mb": round(self.memory_delta / 1024 / 1024, 2),
            "cpu_percent": round(self.cpu_percent, 2),
            "success": self.success,
            "error": self.error,
            "timestamp": datetime.fromtimestamp(self.start_time).isoformat(),
            "tags": self.tags
        }


class PerformanceTracker:
    """
    Central performance tracking system for the MAPTIS platform.
    
    Tracks operation performance, resource usage, and system health metrics.
    """
    
    def __init__(self, 
                 window_size: int = 1000,
                 alert_thresholds: Optional[Dict[str, float]] = None):
        """
        Initialize performance tracker.
        
        Args:
            window_size: Size of sliding window for metrics
            alert_thresholds: Thresholds for performance alerts
        """
        self.window_size = window_size
        self.metrics_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))
        self.alert_thresholds = alert_thresholds or {
            "duration_ms": 5000,      # 5 seconds
            "memory_delta_mb": 100,   # 100 MB
            "cpu_percent": 80,        # 80% CPU
            "error_rate": 0.1         # 10% error rate
        }
        self.active_operations: Dict[str, PerformanceMetrics] = {}
        self._lock = threading.Lock()
        
    def start_operation(self, operation_name: str, tags: Optional[Dict[str, Any]] = None) -> str:
        """
        Start tracking a new operation.
        
        Args:
            operation_name: Name of the operation
            tags: Additional tags for the operation
            
        Returns:
            Operation ID
        """
        operation_id = f"{operation_name}_{time.time()}"
        
        metrics = PerformanceMetrics()
        metrics.operation_name = operation_name
        metrics.start_time = time.time()
        metrics.memory_start = psutil.Process().memory_info().rss
        metrics.tags = tags or {}
        
        with self._lock:
            self.active_operations[operation_id] = metrics
            
        return operation_id
        
    def end_operation(self, operation_id: str, success: bool = True, error: Optional[str] = None):
        """
        End tracking for an operation.
        
        Args:
            operation_id: Operation ID
            success: Whether operation succeeded
            error: Error message if failed
        """
        with self._lock:
            if operation_id not in self.active_operations:
                logger.warning(f"Unknown operation ID: {operation_id}")
                return
                
            metrics = self.active_operations.pop(operation_id)
            
        metrics.end_time = time.time()
        metrics.duration = metrics.end_time - metrics.start_time
        metrics.memory_end = psutil.Process().memory_info().rss
        metrics.memory_delta = metrics.memory_end - metrics.memory_start
        metrics.cpu_percent = psutil.cpu_percent(interval=0.1)
        metrics.success = success
        metrics.error = error
        
        # Log metrics
        self._log_metrics(metrics)
        
        # Store in history
        self.metrics_history[metrics.operation_name].append(metrics)
        
        # Check for performance issues
        self._check_performance_alerts(metrics)
        
    def _log_metrics(self, metrics: PerformanceMetrics):
        """Log performance metrics."""
        metrics_dict = metrics.to_dict()
        
        if metrics.success:
            perf_logger.info(
                f"Operation completed: {metrics.operation_name}",
                extra=metrics_dict
            )
        else:
            perf_logger.warning(
                f"Operation failed: {metrics.operation_name}",
                extra=metrics_dict
            )
            
        # Log to metrics logger for aggregation
        metrics_logger.info(json.dumps(metrics_dict))
        
    def _check_performance_alerts(self, metrics: PerformanceMetrics):
        """Check if metrics exceed alert thresholds."""
        alerts = []
        
        if metrics.duration * 1000 > self.alert_thresholds["duration_ms"]:
            alerts.append(f"Slow operation: {metrics.duration:.2f}s")
            
        if metrics.memory_delta / 1024 / 1024 > self.alert_thresholds["memory_delta_mb"]:
            alerts.append(f"High memory usage: {metrics.memory_delta / 1024 / 1024:.2f}MB")
            
        if metrics.cpu_percent > self.alert_thresholds["cpu_percent"]:
            alerts.append(f"High CPU usage: {metrics.cpu_percent:.1f}%")
            
        if alerts:
            logger.warning(
                f"Performance alerts for {metrics.operation_name}: {', '.join(alerts)}",
                extra={"metrics": metrics.to_dict()}
            )
            
    def get_statistics(self, operation_name: str, window: Optional[int] = None) -> Dict[str, Any]:
        """
        Get performance statistics for an operation.
        
        Args:
            operation_name: Name of the operation
            window: Number of recent operations to analyze
            
        Returns:
            Statistics dictionary
        """
        history = list(self.metrics_history[operation_name])
        if window:
            history = history[-window:]
            
        if not history:
            return {"error": "No data available"}
            
        durations = [m.duration * 1000 for m in history]
        memory_deltas = [m.memory_delta / 1024 / 1024 for m in history]
        cpu_usages = [m.cpu_percent for m in history]
        error_count = sum(1 for m in history if not m.success)
        
        return {
            "operation": operation_name,
            "sample_count": len(history),
            "duration_ms": {
                "mean": statistics.mean(durations),
                "median": statistics.median(durations),
                "min": min(durations),
                "max": max(durations),
                "stdev": statistics.stdev(durations) if len(durations) > 1 else 0
            },
            "memory_delta_mb": {
                "mean": statistics.mean(memory_deltas),
                "median": statistics.median(memory_deltas),
                "min": min(memory_deltas),
                "max": max(memory_deltas)
            },
            "cpu_percent": {
                "mean": statistics.mean(cpu_usages),
                "max": max(cpu_usages)
            },
            "error_rate": error_count / len(history),
            "last_updated": datetime.now().isoformat()
        }
        
    def get_system_metrics(self) -> Dict[str, Any]:
        """Get current system metrics."""
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        return {
            "timestamp": datetime.now().isoformat(),
            "cpu": {
                "percent": cpu_percent,
                "count": psutil.cpu_count()
            },
            "memory": {
                "total_mb": memory.total / 1024 / 1024,
                "used_mb": memory.used / 1024 / 1024,
                "available_mb": memory.available / 1024 / 1024,
                "percent": memory.percent
            },
            "disk": {
                "total_gb": disk.total / 1024 / 1024 / 1024,
                "used_gb": disk.used / 1024 / 1024 / 1024,
                "free_gb": disk.free / 1024 / 1024 / 1024,
                "percent": disk.percent
            }
        }


# Global performance tracker instance
performance_tracker = PerformanceTracker()


@contextmanager
def track_performance(operation_name: str, 
                     tags: Optional[Dict[str, Any]] = None,
                     raise_on_threshold: bool = False,
                     threshold_ms: float = 5000):
    """
    Context manager for tracking operation performance.
    
    Args:
        operation_name: Name of the operation
        tags: Additional tags
        raise_on_threshold: Raise PerformanceError if threshold exceeded
        threshold_ms: Performance threshold in milliseconds
        
    Example:
        with track_performance("database_query", tags={"query_type": "search"}):
            # Perform operation
            results = database.search(query)
    """
    operation_id = performance_tracker.start_operation(operation_name, tags)
    error_occurred = None
    
    try:
        yield operation_id
    except Exception as e:
        error_occurred = str(e)
        raise
    finally:
        performance_tracker.end_operation(
            operation_id, 
            success=(error_occurred is None),
            error=error_occurred
        )
        
        # Check threshold if requested
        if raise_on_threshold and error_occurred is None:
            metrics = performance_tracker.metrics_history[operation_name][-1]
            if metrics.duration * 1000 > threshold_ms:
                raise PerformanceError(
                    f"Operation '{operation_name}' exceeded performance threshold",
                    operation=operation_name,
                    elapsed_time=metrics.duration,
                    threshold=threshold_ms / 1000
                )


def track_performance_decorator(operation_name: Optional[str] = None,
                               tags: Optional[Dict[str, Any]] = None,
                               log_args: bool = False,
                               log_result: bool = False):
    """
    Decorator for tracking function performance.
    
    Args:
        operation_name: Name of the operation (defaults to function name)
        tags: Additional tags
        log_args: Log function arguments
        log_result: Log function result
        
    Example:
        @track_performance_decorator(tags={"api": "v1"})
        def process_request(request_data):
            # Process request
            return response
    """
    def decorator(func):
        nonlocal operation_name
        if operation_name is None:
            operation_name = func.__name__
            
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            op_tags = tags.copy() if tags else {}
            
            if log_args:
                op_tags["args"] = str(args)[:100]  # Truncate for safety
                op_tags["kwargs"] = str(kwargs)[:100]
                
            with track_performance(operation_name, tags=op_tags) as op_id:
                result = func(*args, **kwargs)
                
                if log_result:
                    op_tags["result_type"] = type(result).__name__
                    
                return result
                
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            op_tags = tags.copy() if tags else {}
            
            if log_args:
                op_tags["args"] = str(args)[:100]
                op_tags["kwargs"] = str(kwargs)[:100]
                
            with track_performance(operation_name, tags=op_tags) as op_id:
                result = await func(*args, **kwargs)
                
                if log_result:
                    op_tags["result_type"] = type(result).__name__
                    
                return result
                
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
            
    return decorator


class PerformanceBenchmark:
    """
    Performance benchmarking utilities for comparing operations.
    
    Example:
        benchmark = PerformanceBenchmark()
        
        with benchmark.measure("algorithm_v1"):
            result1 = algorithm_v1(data)
            
        with benchmark.measure("algorithm_v2"):
            result2 = algorithm_v2(data)
            
        comparison = benchmark.compare()
    """
    
    def __init__(self):
        self.measurements: Dict[str, List[float]] = defaultdict(list)
        
    @contextmanager
    def measure(self, name: str):
        """Measure operation performance."""
        start = time.perf_counter()
        try:
            yield
        finally:
            duration = time.perf_counter() - start
            self.measurements[name].append(duration)
            
    def compare(self) -> Dict[str, Any]:
        """Compare benchmark results."""
        results = {}
        
        for name, durations in self.measurements.items():
            if durations:
                results[name] = {
                    "runs": len(durations),
                    "mean_ms": statistics.mean(durations) * 1000,
                    "median_ms": statistics.median(durations) * 1000,
                    "min_ms": min(durations) * 1000,
                    "max_ms": max(durations) * 1000,
                    "stdev_ms": statistics.stdev(durations) * 1000 if len(durations) > 1 else 0
                }
                
        # Calculate relative performance
        if len(results) >= 2:
            baseline_name = list(results.keys())[0]
            baseline_mean = results[baseline_name]["mean_ms"]
            
            for name in results:
                if name != baseline_name:
                    results[name]["relative_to_baseline"] = {
                        "baseline": baseline_name,
                        "speedup": baseline_mean / results[name]["mean_ms"],
                        "percent_difference": ((baseline_mean - results[name]["mean_ms"]) / baseline_mean) * 100
                    }
                    
        return results


class PerformanceProfiler:
    """
    Detailed performance profiler for identifying bottlenecks.
    
    Tracks nested operations and creates a performance flame graph.
    """
    
    def __init__(self):
        self.call_stack: List[Dict[str, Any]] = []
        self.completed_calls: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        
    @contextmanager
    def profile(self, operation_name: str, metadata: Optional[Dict[str, Any]] = None):
        """Profile a code section."""
        start_time = time.perf_counter()
        start_memory = psutil.Process().memory_info().rss
        
        call_info = {
            "operation": operation_name,
            "start_time": start_time,
            "start_memory": start_memory,
            "metadata": metadata or {},
            "children": []
        }
        
        with self._lock:
            if self.call_stack:
                # Add as child of current operation
                self.call_stack[-1]["children"].append(call_info)
            else:
                # Top-level operation
                self.completed_calls.append(call_info)
                
            self.call_stack.append(call_info)
            
        try:
            yield
        finally:
            end_time = time.perf_counter()
            end_memory = psutil.Process().memory_info().rss
            
            with self._lock:
                self.call_stack.pop()
                
            call_info["duration_ms"] = (end_time - start_time) * 1000
            call_info["memory_delta_mb"] = (end_memory - start_memory) / 1024 / 1024
            
    def get_profile_data(self) -> List[Dict[str, Any]]:
        """Get profiling data."""
        return self.completed_calls.copy()
        
    def reset(self):
        """Reset profiler data."""
        with self._lock:
            self.call_stack.clear()
            self.completed_calls.clear()


# Specialized logging functions

def log_slow_operation(operation_name: str, 
                      duration_ms: float,
                      threshold_ms: float,
                      context: Optional[Dict[str, Any]] = None):
    """Log slow operation warning."""
    perf_logger.warning(
        f"Slow operation detected: {operation_name}",
        extra={
            "operation": operation_name,
            "duration_ms": duration_ms,
            "threshold_ms": threshold_ms,
            "exceeded_by_ms": duration_ms - threshold_ms,
            "context": context or {}
        }
    )


def log_resource_usage(operation_name: str,
                      memory_mb: float,
                      cpu_percent: float,
                      context: Optional[Dict[str, Any]] = None):
    """Log resource usage metrics."""
    metrics_logger.info(
        f"Resource usage for {operation_name}",
        extra={
            "operation": operation_name,
            "memory_mb": memory_mb,
            "cpu_percent": cpu_percent,
            "timestamp": datetime.now().isoformat(),
            "context": context or {}
        }
    )


def log_api_performance(endpoint: str,
                       method: str,
                       status_code: int,
                       duration_ms: float,
                       request_size: int,
                       response_size: int):
    """Log API endpoint performance."""
    perf_logger.info(
        f"API request: {method} {endpoint}",
        extra={
            "endpoint": endpoint,
            "method": method,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "request_size": request_size,
            "response_size": response_size,
            "timestamp": datetime.now().isoformat()
        }
    )


# Export commonly used components
__all__ = [
    "PerformanceMetrics",
    "PerformanceTracker",
    "performance_tracker",
    "track_performance",
    "track_performance_decorator",
    "PerformanceBenchmark",
    "PerformanceProfiler",
    "log_slow_operation",
    "log_resource_usage",
    "log_api_performance"
]
