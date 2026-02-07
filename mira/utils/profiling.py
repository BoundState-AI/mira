#!/usr/bin/env python3
"""
Module: Profiling
Purpose: Copyright (c) 2025 BoundState Inc. All Rights Reserved.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-055 (performance monitoring), NASA-STD-8739.8B
Safety Critical: False
"""

__version__ = "3.0.0"
import asyncio
import cProfile
import io
import os
import pstats
import time
import tracemalloc
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from mira.utils.config import get_config
from mira.utils.logging_config import get_logger

logger = get_logger(__name__)
perf_logger = get_logger("performance")


class ProfileStats:
    """Container for profiling statistics."""
    
    def __init__(self, name: str):
        self.name = name
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.duration: Optional[float] = None
        self.cpu_stats: Optional[pstats.Stats] = None
        self.memory_start: Optional[int] = None
        self.memory_peak: Optional[int] = None
        self.memory_end: Optional[int] = None
        self.call_count: Optional[int] = None
        
    def complete(self):
        """Mark profiling as complete."""
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "name": self.name,
            "duration_ms": self.duration * 1000 if self.duration else None,
            "memory_mb": {
                "start": self.memory_start / 1024 / 1024 if self.memory_start else None,
                "peak": self.memory_peak / 1024 / 1024 if self.memory_peak else None,
                "end": self.memory_end / 1024 / 1024 if self.memory_end else None,
                "growth": (self.memory_end - self.memory_start) / 1024 / 1024 
                         if self.memory_start and self.memory_end else None
            },
            "call_count": self.call_count
        }


class Profiler:
    """
    Comprehensive profiler for CPU and memory analysis.
    
    Examples:
        >>> profiler = Profiler()
        >>> with profiler.profile("search_operation"):
        ...     results = search_engine.search("aluminum")
        >>> stats = profiler.get_stats("search_operation")
        
    Compliance: SWE-055
    """
    
    def __init__(self, output_dir: Optional[Path] = None):
        """Initialize profiler with output directory."""
        self.output_dir = output_dir or Path("./profiles")
        self.output_dir.mkdir(exist_ok=True)
        self.stats: Dict[str, ProfileStats] = {}
        self.enabled = get_config().enable_profiling
        
    @contextmanager
    def profile(self, name: str, profile_cpu: bool = True, profile_memory: bool = True):
        """
        Profile a code block for CPU and memory usage.
        
        Args:
            name: Name for this profiling session
            profile_cpu: Enable CPU profiling
            profile_memory: Enable memory profiling
            
        Yields:
            ProfileStats object
            
        Examples:
            >>> with profiler.profile("database_load") as stats:
            ...     db.load_materials()
            >>> print(f"Duration: {stats.duration}s")
            
        Compliance: SWE-055
        """
        if not self.enabled:
            yield ProfileStats(name)
            return
            
        stats = ProfileStats(name)
        self.stats[name] = stats
        
        # Start memory tracking
        if profile_memory:
            if not tracemalloc.is_tracing():
                tracemalloc.start()
            stats.memory_start = tracemalloc.get_traced_memory()[0]
            
        # Start CPU profiling
        cpu_profiler = None
        if profile_cpu:
            cpu_profiler = cProfile.Profile()
            cpu_profiler.enable()
            
        try:
            yield stats
        finally:
            # Stop CPU profiling
            if cpu_profiler:
                cpu_profiler.disable()
                s = io.StringIO()
                ps = pstats.Stats(cpu_profiler, stream=s).sort_stats('cumulative')
                ps.print_stats(20)  # Top 20 functions
                stats.cpu_stats = ps
                
                # Save detailed profile
                profile_file = self.output_dir / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.prof"
                cpu_profiler.dump_stats(str(profile_file))
                
            # Stop memory tracking
            if profile_memory:
                current, peak = tracemalloc.get_traced_memory()
                stats.memory_end = current
                stats.memory_peak = peak
                
            stats.complete()
            
            # Log statistics
            perf_logger.info(
                f"Profile completed: {name}",
                extra=stats.to_dict()
            )
    
    def get_stats(self, name: str) -> Optional[ProfileStats]:
        """Get statistics for a named profile."""
        return self.stats.get(name)
    
    def get_all_stats(self) -> Dict[str, ProfileStats]:
        """Get all profiling statistics."""
        return self.stats
    
    def clear_stats(self):
        """Clear all stored statistics."""
        self.stats.clear()
    
    def generate_report(self) -> Dict[str, Any]:
        """
        Generate a profiling report.
        
        Returns:
            Dictionary with profiling summary
            
        Compliance: SWE-055
        """
        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "profiles": {},
            "summary": {
                "total_profiles": len(self.stats),
                "total_duration_s": sum(s.duration or 0 for s in self.stats.values()),
                "max_memory_mb": max(
                    (s.memory_peak or 0) / 1024 / 1024 
                    for s in self.stats.values()
                ) if self.stats else 0
            }
        }
        
        for name, stats in self.stats.items():
            report["profiles"][name] = stats.to_dict()
            
        return report


def profile_async(name: str):
    """
    Decorator for profiling async functions.
    
    Args:
        name: Profile name
        
    Examples:
        >>> @profile_async("search_materials")
        ... async def search_materials(query: str):
        ...     return await db.search(query)
        
    Compliance: SWE-055
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not get_config().enable_profiling:
                return await func(*args, **kwargs)
                
            profiler = get_profiler()
            with profiler.profile(f"{name}.{func.__name__}") as stats:
                stats.call_count = 1
                result = await func(*args, **kwargs)
                return result
                
        return wrapper
    return decorator


def profile_sync(name: str):
    """
    Decorator for profiling synchronous functions.
    
    Args:
        name: Profile name
        
    Examples:
        >>> @profile_sync("calculate_risk")
        ... def calculate_risk(material: Material):
        ...     return risk_analyzer.analyze(material)
        
    Compliance: SWE-055
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not get_config().enable_profiling:
                return func(*args, **kwargs)
                
            profiler = get_profiler()
            with profiler.profile(f"{name}.{func.__name__}") as stats:
                stats.call_count = 1
                result = func(*args, **kwargs)
                return result
                
        return wrapper
    return decorator


class ProfilingMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for request profiling.
    
    Tracks:
    - Request duration
    - Memory usage
    - Endpoint performance
    
    Compliance: SWE-055
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.profiler = get_profiler()
        
    async def dispatch(self, request: Request, call_next):
        """Profile each request."""
        if not get_config().enable_profiling:
            return await call_next(request)
            
        # Generate profile name from endpoint
        profile_name = f"request_{request.method}_{request.url.path.replace('/', '_')}"
        
        with self.profiler.profile(profile_name, profile_cpu=False) as stats:
            # Add request metadata
            stats.metadata = {
                "method": request.method,
                "path": request.url.path,
                "client": request.client.host if request.client else None
            }
            
            response = await call_next(request)
            
            # Add response metadata
            stats.metadata["status_code"] = response.status_code
            
            # Add profiling headers in development
            if get_config().is_development():
                response.headers["X-Profile-Duration-ms"] = str(int(stats.duration * 1000))
                if stats.memory_end and stats.memory_start:
                    response.headers["X-Profile-Memory-Growth-KB"] = str(
                        int((stats.memory_end - stats.memory_start) / 1024)
                    )
                    
            return response


class MemoryMonitor:
    """
    Monitor memory usage over time.
    
    Examples:
        >>> monitor = MemoryMonitor()
        >>> monitor.start()
        >>> # ... do work ...
        >>> stats = monitor.stop()
        >>> print(f"Peak memory: {stats['peak_mb']} MB")
        
    Compliance: SWE-055
    """
    
    def __init__(self):
        self.tracking = False
        self.snapshots: List[Tuple[float, int, int]] = []
        
    def start(self):
        """Start memory monitoring."""
        if not tracemalloc.is_tracing():
            tracemalloc.start()
        self.tracking = True
        self.snapshots = []
        
        # Take initial snapshot
        self._take_snapshot()
        
    def stop(self) -> Dict[str, Any]:
        """Stop monitoring and return statistics."""
        if not self.tracking:
            return {}
            
        self._take_snapshot()
        self.tracking = False
        
        if not self.snapshots:
            return {}
            
        # Calculate statistics
        times, currents, peaks = zip(*self.snapshots)
        
        return {
            "duration_s": times[-1] - times[0],
            "samples": len(self.snapshots),
            "start_mb": currents[0] / 1024 / 1024,
            "end_mb": currents[-1] / 1024 / 1024,
            "peak_mb": max(peaks) / 1024 / 1024,
            "growth_mb": (currents[-1] - currents[0]) / 1024 / 1024,
            "average_mb": sum(currents) / len(currents) / 1024 / 1024
        }
        
    def _take_snapshot(self):
        """Take a memory snapshot."""
        if self.tracking:
            current, peak = tracemalloc.get_traced_memory()
            self.snapshots.append((time.time(), current, peak))
    
    @contextmanager
    def monitor(self, name: str):
        """Context manager for memory monitoring."""
        self.start()
        try:
            yield self
        finally:
            stats = self.stop()
            if stats:
                perf_logger.info(
                    f"Memory profile: {name}",
                    extra=stats
                )


def analyze_profile(profile_path: Path) -> Dict[str, Any]:
    """
    Analyze a saved profile file.
    
    Args:
        profile_path: Path to .prof file
        
    Returns:
        Analysis results
        
    Compliance: SWE-055
    """
    if not profile_path.exists():
        return {"error": "Profile file not found"}
        
    stats = pstats.Stats(str(profile_path))
    
    # Get top functions by cumulative time
    stream = io.StringIO()
    stats.stream = stream
    stats.sort_stats('cumulative')
    stats.print_stats(20)
    
    # Parse statistics
    top_functions = []
    for line in stream.getvalue().split('\n'):
        if line and not line.startswith(' '):
            parts = line.split()
            if len(parts) >= 6 and parts[0].replace('.', '').isdigit():
                top_functions.append({
                    "calls": parts[0],
                    "total_time": float(parts[1]),
                    "per_call": float(parts[2]),
                    "cumulative": float(parts[3]),
                    "function": ' '.join(parts[5:])
                })
    
    return {
        "profile_file": str(profile_path),
        "total_calls": stats.total_calls,
        "total_time": stats.total_tt,
        "top_functions": top_functions[:10]
    }


# Global profiler instance
_profiler: Optional[Profiler] = None


def get_profiler() -> Profiler:
    """Get global profiler instance."""
    global _profiler
    if _profiler is None:
        _profiler = Profiler()
    return _profiler


def reset_profiler():
    """Reset global profiler."""
    global _profiler
    if _profiler:
        _profiler.clear_stats()
    _profiler = None
