#!/usr/bin/env python3
"""
Runtime controls for disabling inactive or scrubbed module surfaces.
"""

from __future__ import annotations

import os


DEFAULT_DISABLED_RUNTIME_KEYS = frozenset(
    {
        "guidance:mua",
        "mua",
        "mua-matchmaker",
        "mua-v6",
        "mua-v7",
        "mua-v10",
        "test-classes",
    }
)


def current_environment() -> str:
    raw = (
        os.getenv("MIRA_ENV")
        or os.getenv("ENVIRONMENT")
        or "development"
    ).strip().lower()
    return raw or "development"


def _parse_runtime_keys(raw: str | None) -> frozenset[str]:
    if raw is None:
        return frozenset()

    normalized = raw.strip().lower()
    if not normalized:
        return frozenset()
    if normalized in {"0", "none", "off"}:
        return frozenset()

    keys = {
        item.strip().lower()
        for item in raw.split(",")
        if item.strip()
    }
    return frozenset(keys)


def disabled_runtime_keys() -> frozenset[str]:
    configured = _parse_runtime_keys(os.getenv("MIRA_DISABLED_RUNTIME_KEYS"))
    if configured:
        return configured
    if current_environment() == "production":
        return DEFAULT_DISABLED_RUNTIME_KEYS
    return frozenset()


def runtime_key_enabled(key: str) -> bool:
    normalized = key.strip().lower()
    return normalized not in disabled_runtime_keys()
