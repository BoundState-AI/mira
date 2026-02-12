#!/usr/bin/env python3
"""
MCP server that gives Claude Code direct access to the MIRA API.

Exposes generic mira_get / mira_post / mira_delete tools so Claude
can call any endpoint on the running backend without hardcoding routes.

Usage:
    claude mcp add -s project -t stdio mira-api -- \
        /c/Users/jwilde2/.conda/envs/boundstate-intent/python.exe \
        /c/BoundState/scripts/mcp_mira_server.py
"""

from __future__ import annotations

import json
import os
import httpx
from mcp.server.fastmcp import FastMCP

API_BASE = os.environ.get("MIRA_API_BASE", "http://localhost:8080")

mcp = FastMCP("mira-api")


@mcp.tool()
def mira_get(path: str) -> str:
    """GET request to the MIRA API.

    Args:
        path: API path starting with / (e.g. /mp-plan/v2/ping, /miul/v4/sessions)
    """
    url = f"{API_BASE}{path}"
    try:
        r = httpx.get(url, timeout=30)
        return _format(r)
    except httpx.ConnectError:
        return f"Connection refused: {url} — is the backend running?"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def mira_post(path: str, body: str = "{}") -> str:
    """POST request to the MIRA API with a JSON body.

    Args:
        path: API path starting with / (e.g. /mp-plan/v2/sessions)
        body: JSON string for the request body (default: {})
    """
    url = f"{API_BASE}{path}"
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        return f"Invalid JSON body: {e}"
    try:
        r = httpx.post(url, json=payload, timeout=60)
        return _format(r)
    except httpx.ConnectError:
        return f"Connection refused: {url} — is the backend running?"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def mira_delete(path: str) -> str:
    """DELETE request to the MIRA API.

    Args:
        path: API path starting with / (e.g. /mp-plan/v2/sessions/{session_id})
    """
    url = f"{API_BASE}{path}"
    try:
        r = httpx.delete(url, timeout=30)
        return _format(r)
    except httpx.ConnectError:
        return f"Connection refused: {url} — is the backend running?"
    except Exception as e:
        return f"Error: {e}"


def _format(r: httpx.Response) -> str:
    """Format an HTTP response for Claude."""
    status = f"HTTP {r.status_code}"
    ct = r.headers.get("content-type", "")
    if "json" in ct:
        try:
            data = r.json()
            body = json.dumps(data, indent=2, default=str)
            # Truncate very large responses
            if len(body) > 8000:
                body = body[:8000] + "\n... (truncated)"
        except Exception:
            body = r.text[:8000]
    else:
        body = r.text[:8000] if r.text else "(empty)"
    return f"{status}\n{body}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
