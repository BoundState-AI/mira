#!/usr/bin/env python3
"""
Module: Cache
Purpose: Copyright (c) 2025 BoundState Inc. All Rights Reserved.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-055 (async operations), NASA-STD-8739.8B
Safety Critical: False
"""

__version__ = "3.0.0"
import json
import hashlib
from typing import Any, Optional, Union, Callable
from datetime import timedelta
from functools import wraps
import asyncio

from fastapi import Request

try:
    from redis import asyncio as aioredis
    from redis.exceptions import RedisError
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    aioredis = None
    RedisError = Exception

from mira.utils.config import get_config
from mira.utils.exceptions import CacheError, raise_safety_error
from mira.utils.performance_logger import track_performance
from mira.utils.logging_config import get_logger

logger = get_logger(__name__)


class RedisCache:
    """
    High-performance Redis cache with NASA compliance.
    
    Features:
    - Async operations for scalability
    - Connection pooling
    - Automatic retry logic
    - Performance tracking
    - Error resilience
    
    Examples:
        >>> cache = RedisCache()
        >>> await cache.initialize()
        >>> await cache.set("key", {"data": "value"}, ttl=3600)
        >>> result = await cache.get("key")
    
    Compliance: SWE-055, SWE-134
    """
    
    def __init__(self):
        """Initialize Redis cache configuration."""
        self.redis_client: Optional[aioredis.Redis] = None
        self.pool: Optional[aioredis.ConnectionPool] = None
        self.initialized = False
        self._lock = asyncio.Lock()
        
    async def initialize(self) -> None:
        """
        Initialize Redis connection with pooling.
        
        Raises:
            CacheError: If Redis connection fails
            
        Compliance: SWE-055 (async operations)
        """
        if self.initialized:
            return
            
        async with self._lock:
            if self.initialized:  # Double-check pattern
                return
                
            try:
                # Create connection pool for high concurrency
                self.pool = aioredis.ConnectionPool(
                    host=get_config().redis_host,
                    port=get_config().redis_port,
                    password=get_config().redis_password,
                    db=get_config().redis_db,
                    max_connections=get_config().redis_max_connections,
                    decode_responses=True,
                    socket_keepalive=True,
                    socket_keepalive_options={
                        1: 1,  # TCP_KEEPIDLE
                        2: 1,  # TCP_KEEPINTVL
                        3: 5,  # TCP_KEEPCNT
                    }
                )
                
                self.redis_client = aioredis.Redis(
                    connection_pool=self.pool,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True,
                    retry_on_error=[RedisError]
                )
                
                # Test connection
                await self.redis_client.ping()
                self.initialized = True
                
                logger.info(
                    "Redis cache initialized",
                    extra={
                        "host": get_config().redis_host,
                        "port": get_config().redis_port,
                        "max_connections": get_config().redis_max_connections
                    }
                )

            except Exception as e:
                raise_safety_error(
                    CacheError,
                    f"Failed to initialize Redis cache: {e}",
                    cache_type="redis",
                    host=get_config().redis_host,
                    port=get_config().redis_port
                )
    
    async def close(self) -> None:
        """
        Close Redis connections gracefully.
        
        Compliance: SWE-134 (error handling)
        """
        if self.redis_client:
            await self.redis_client.close()
        if self.pool:
            await self.pool.disconnect()
        self.initialized = False
        logger.info("Redis cache closed")
    
    def _generate_key(self, namespace: str, key: Union[str, dict]) -> str:
        """
        Generate cache key with namespace.
        
        Args:
            namespace: Cache namespace (e.g., "search", "materials")
            key: Key or dict to hash
            
        Returns:
            Namespaced cache key
            
        Examples:
            >>> cache._generate_key("search", "aluminum sheet")
            'maptis:search:a7b9c2d4e5f6'
            
            >>> cache._generate_key("materials", {"id": "MAT-001"})
            'maptis:materials:b8c3d5e6f7a8'
        """
        if isinstance(key, dict):
            # Sort dict for consistent hashing
            key_str = json.dumps(key, sort_keys=True)
        else:
            key_str = str(key)
            
        # Create hash for consistent key length
        key_hash = hashlib.md5(key_str.encode()).hexdigest()[:12]
        
        return f"{config.cache_prefix}:{namespace}:{key_hash}"
    
    @track_performance(operation_name="cache_get")
    async def get(self, namespace: str, key: Union[str, dict]) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            namespace: Cache namespace
            key: Cache key
            
        Returns:
            Cached value or None if not found
            
        Compliance: SWE-055, SWE-134
        """
        if not self.initialized or not config.cache_enabled:
            return None
            
        cache_key = self._generate_key(namespace, key)
        
        try:
            value = await self.redis_client.get(cache_key)
            if value:
                # Deserialize JSON data
                return json.loads(value)
            return None
            
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON in cache for key: {cache_key}")
            # Delete corrupted entry
            await self.delete(namespace, key)
            return None
            
        except Exception as e:
            logger.error(f"Cache get error: {e}", extra={"key": cache_key})
            # Fail gracefully - don't break the app if cache fails
            return None
    
    @track_performance(operation_name="cache_set")
    async def set(
        self, 
        namespace: str, 
        key: Union[str, dict], 
        value: Any, 
        ttl: Optional[int] = None
    ) -> bool:
        """
        Set value in cache with optional TTL.
        
        Args:
            namespace: Cache namespace
            key: Cache key
            value: Value to cache (must be JSON serializable)
            ttl: Time to live in seconds
            
        Returns:
            True if successful, False otherwise
            
        Examples:
            >>> await cache.set("search", "aluminum", results, ttl=3600)
            True
            
        Compliance: SWE-055, SWE-032
        """
        if not self.initialized or not config.cache_enabled:
            return False
            
        cache_key = self._generate_key(namespace, key)
        ttl = ttl or config.cache_ttl_seconds
        
        try:
            # Serialize to JSON
            serialized = json.dumps(value)
            
            # Set with expiration
            await self.redis_client.setex(
                cache_key,
                timedelta(seconds=ttl),
                serialized
            )
            return True
            
        except (TypeError, ValueError) as e:
            logger.error(f"Cache serialization error: {e}", extra={"key": cache_key})
            return False
            
        except Exception as e:
            logger.error(f"Cache set error: {e}", extra={"key": cache_key})
            return False
    
    async def delete(self, namespace: str, key: Union[str, dict]) -> bool:
        """
        Delete value from cache.
        
        Args:
            namespace: Cache namespace
            key: Cache key
            
        Returns:
            True if deleted, False otherwise
            
        Compliance: SWE-055
        """
        if not self.initialized:
            return False
            
        cache_key = self._generate_key(namespace, key)
        
        try:
            result = await self.redis_client.delete(cache_key)
            return bool(result)
        except Exception as e:
            logger.error(f"Cache delete error: {e}", extra={"key": cache_key})
            return False
    
    async def clear_namespace(self, namespace: str) -> int:
        """
        Clear all keys in a namespace.
        
        Args:
            namespace: Cache namespace to clear
            
        Returns:
            Number of keys deleted
            
        Compliance: SWE-055, SWE-134
        """
        if not self.initialized:
            return 0
            
        pattern = f"{config.cache_prefix}:{namespace}:*"
        
        try:
            # Use SCAN for memory efficiency with large datasets
            deleted = 0
            async for key in self.redis_client.scan_iter(match=pattern, count=100):
                if await self.redis_client.delete(key):
                    deleted += 1
                    
            logger.info(f"Cleared {deleted} keys from namespace: {namespace}")
            return deleted
            
        except Exception as e:
            logger.error(f"Cache clear error: {e}", extra={"namespace": namespace})
            return 0
    
    async def get_stats(self) -> dict:
        """
        Get cache statistics.
        
        Returns:
            Cache statistics including memory usage and hit rates
            
        Compliance: SWE-055
        """
        if not self.initialized:
            return {"status": "disabled"}
            
        try:
            info = await self.redis_client.info("stats")
            memory = await self.redis_client.info("memory")
            
            return {
                "status": "active",
                "connected_clients": info.get("connected_clients", 0),
                "total_commands": info.get("total_commands_processed", 0),
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
                "hit_rate": self._calculate_hit_rate(
                    info.get("keyspace_hits", 0),
                    info.get("keyspace_misses", 0)
                ),
                "memory_used_mb": memory.get("used_memory", 0) / 1024 / 1024,
                "memory_peak_mb": memory.get("used_memory_peak", 0) / 1024 / 1024,
            }
            
        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {"status": "error", "error": str(e)}
    
    def _calculate_hit_rate(self, hits: int, misses: int) -> float:
        """Calculate cache hit rate percentage."""
        total = hits + misses
        return (hits / total * 100) if total > 0 else 0.0


# Global cache instance
_cache: Optional[RedisCache] = None


async def get_cache() -> RedisCache:
    """
    Get global cache instance.
    
    Returns:
        Initialized Redis cache
        
    Compliance: SWE-055
    """
    global _cache
    if _cache is None:
        _cache = RedisCache()
        await _cache.initialize()
    return _cache


def cache_key_wrapper(
    namespace: str,
    ttl: Optional[int] = None,
    key_func: Optional[Callable] = None
):
    """
    Decorator for caching function results.
    
    Args:
        namespace: Cache namespace
        ttl: Time to live in seconds
        key_func: Function to generate cache key from args
        
    Examples:
        >>> @cache_key_wrapper("search", ttl=3600)
        ... async def search_materials(query: str):
        ...     # Expensive search operation
        ...     return results
        
        >>> @cache_key_wrapper(
        ...     "materials",
        ...     key_func=lambda material_id: {"id": material_id}
        ... )
        ... async def get_material(material_id: str):
        ...     # Database lookup
        ...     return material
        
    Compliance: SWE-055, SWE-032
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Skip caching if disabled
            if not config.cache_enabled:
                return await func(*args, **kwargs)
            
            # Generate cache key
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                # Default: use all args and kwargs
                cache_key = {
                    "args": args,
                    "kwargs": kwargs
                }
            
            # Get cache instance
            cache = await get_cache()
            
            # Try to get from cache
            cached_result = await cache.get(namespace, cache_key)
            if cached_result is not None:
                logger.debug(f"Cache hit for {func.__name__}")
                return cached_result
            
            # Execute function
            result = await func(*args, **kwargs)
            
            # Cache the result
            await cache.set(namespace, cache_key, result, ttl=ttl)
            
            return result
            
        return wrapper
    return decorator


async def invalidate_search_cache():
    """
    Invalidate all search-related caches.
    
    Use when materials database is updated.
    
    Compliance: SWE-055
    """
    cache = await get_cache()
    await cache.clear_namespace("search")
    await cache.clear_namespace("intent")
    logger.info("Search cache invalidated")


async def warmup_cache(materials_db, search_engine):
    """
    Warm up cache with common queries.
    
    Args:
        materials_db: Materials database instance
        search_engine: Search engine instance
        
    Compliance: SWE-055
    """
    cache = await get_cache()
    
    # Common search terms to pre-cache
    common_queries = [
        "aluminum", "titanium", "steel", "composite",
        "oxygen compatible", "high temperature", "corrosion resistant",
        "aerospace", "cryogenic", "pressure vessel"
    ]
    
    logger.info("Warming up cache with common queries")
    
    for query in common_queries:
        try:
            # Perform search
            results = search_engine.search(query, top_k=20)
            
            # Cache results
            await cache.set(
                "search",
                query,
                results,
                ttl=config.cache_warmup_ttl
            )
            
        except Exception as e:
            logger.warning(f"Failed to warm cache for query '{query}': {e}")
    
    logger.info(f"Cache warmup completed for {len(common_queries)} queries")
