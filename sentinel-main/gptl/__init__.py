# Copyright 2025 BoundStateAI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
GPTL - Grounded Precision Translation Layer
============================================

GPTL is a negative selection system for document retrieval that:
- Subtracts the 80% that CANNOT be relevant before expensive operations
- Uses Claude (Haiku/Sonnet/Opus) for intelligent filtering and synthesis
- Produces auditable, deterministic, bounded outputs

Philosophy:
    "We don't retrieve truth. We eliminate impossibility - then show our work."

Quick Start:
    >>> from gptl import GPTLEngine, GPTLRequest, load_domain_pack
    >>>
    >>> # Load domain configuration
    >>> domain = load_domain_pack("mira")
    >>> engine = GPTLEngine(domain)
    >>>
    >>> # Process a query
    >>> request = GPTLRequest(query="What material for hydrogen?", ...)
    >>> result = engine.process(request, document_provider)
    >>> print(result.response.intelligence.finding)

For advanced usage, import from submodules:
    - gptl.schema: All Pydantic models
    - gptl.engine: Pipeline orchestration
    - gptl.claude_client: Claude API wrapper
    - gptl.feature_extractor: L0 feature extraction
    - gptl.negative_selection: L3 constraint cascade
    - gptl.intent_framing: L2 intent classification
    - gptl.signal_extraction: L4 anomaly detection
    - gptl.synthesis: L5 intelligence output

Compliance: NASA-STD-8739.8B, SWE-032, SWE-033
Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

__version__ = "0.4.0"  # Phase 5 - Refined API
__safety_critical__ = True


# =============================================================================
# PUBLIC API - Essential types for typical usage
# =============================================================================

# Core schema types (user-facing)
from gptl.schema import (
    # Enums
    ConstraintAction,
    DocType,
    EvidenceType,
    IntentCategory,
    ModelTier,
    # Document features
    DocFeatures,
    DocFlags,
    EntitySet,
    # Intent
    IntentFrame,
    IntentClassificationResult,
    # Constraints
    ConstraintRule,
    ConstraintViolation,
    ViolationReport,
    # Output
    EvidenceCitation,
    IntelligenceOutput,
    # Audit
    AuditTrail,
    GPTLMetrics,
    ModelCall,
    # API contracts
    GPTLRequest,
    GPTLResponse,
    # Domain configuration
    DomainPack,
)

# Config loading
from gptl.config_loader import (
    load_domain_pack,
    compute_config_hash,
)

# Main engine
from gptl.engine import (
    GPTLEngine,
    PipelineResult,
    DocumentProvider,
    InMemoryDocumentProvider,
    create_engine,
)

# Claude client (for custom integrations)
from gptl.claude_client import (
    BaseClaudeClient,
    MockClaudeClient,
    get_default_client,
    set_default_client,
)

# Negative selection (commonly extended)
from gptl.negative_selection import (
    Candidate,
    NegativeSelectionEngine,
    create_negative_selection_engine,
)

# Feature extraction (for ingestion pipelines)
from gptl.feature_extractor import (
    FeatureExtractor,
    create_feature_extractor,
)


# =============================================================================
# PUBLIC API EXPORTS
# =============================================================================

__all__ = [
    # Version
    "__version__",

    # --- Core Types ---
    # Enums
    "EvidenceType",
    "DocType",
    "ConstraintAction",
    "IntentCategory",
    "ModelTier",

    # Document model
    "DocFeatures",
    "DocFlags",
    "EntitySet",

    # Intent
    "IntentFrame",
    "IntentClassificationResult",

    # Constraints
    "ConstraintRule",
    "ConstraintViolation",
    "ViolationReport",

    # Output
    "EvidenceCitation",
    "IntelligenceOutput",

    # Audit
    "AuditTrail",
    "GPTLMetrics",
    "ModelCall",

    # API contracts
    "GPTLRequest",
    "GPTLResponse",

    # --- Configuration ---
    "DomainPack",
    "load_domain_pack",
    "compute_config_hash",

    # --- Engine ---
    "GPTLEngine",
    "PipelineResult",
    "DocumentProvider",
    "InMemoryDocumentProvider",
    "create_engine",

    # --- Claude Client ---
    "BaseClaudeClient",
    "MockClaudeClient",
    "get_default_client",
    "set_default_client",

    # --- Negative Selection ---
    "Candidate",
    "NegativeSelectionEngine",
    "create_negative_selection_engine",

    # --- Feature Extraction ---
    "FeatureExtractor",
    "create_feature_extractor",
]


# =============================================================================
# LAZY IMPORTS FOR ADVANCED USAGE
# =============================================================================
# Users can still access everything via submodule imports:
#   from gptl.schema import BaseCondition, DerivationRule, ...
#   from gptl.prompts import get_prompt, PROMPT_REGISTRY, ...
#   from gptl.evidence_taxonomy import DerivationEngine, ...
#   from gptl.shadow_mode import ShadowModeController, ...
#   from gptl.intent_framing import IntentFramingEngine, ...
#   from gptl.signal_extraction import SignalExtractionEngine, ...
#   from gptl.synthesis import SynthesisEngine, ...
