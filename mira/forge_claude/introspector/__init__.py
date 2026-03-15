"""Step 1: Schema Introspector — connect to any database and produce a schema manifest."""

from mira.forge_claude.introspector.engine import introspect_database
from mira.forge_claude.introspector.manifest import SchemaManifest

__all__ = ["introspect_database", "SchemaManifest"]
