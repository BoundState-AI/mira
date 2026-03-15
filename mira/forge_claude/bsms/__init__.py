"""FORGE BSMS runtime generation — Step 5b.

Generates the Bouncer-Sonnet-Rules-Sonnet pipeline code
for generated applications.
"""

from mira.forge_claude.bsms.pipeline_gen import generate_bsms_pipeline

__all__ = ["generate_bsms_pipeline"]
