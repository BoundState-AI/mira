#!/usr/bin/env python3
"""
Module: M&P Plan Main Entry Point
Purpose: Allow running M&P Plan as a module

BoundState AI 2026
Version: 2.0.0

Usage:
    python -m mira.mp_plan --help
    python -m mira.mp_plan create --program "HLS"
    python -m mira.mp_plan list
"""

from mira.mp_plan.cli import main

if __name__ == "__main__":
    main()
