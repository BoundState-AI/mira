#!/usr/bin/env python3
"""
Module: Conftest
Purpose: Shared fixtures for API tests.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013
Safety Critical: True
"""

import pytest
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def api_client():
    """Create test client for API (session-scoped for efficiency)."""
    from fastapi.testclient import TestClient
    from mira.api.app import app
    return TestClient(app)


__safety_critical__ = True
