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
GPTL Config Loader - Domain Pack YAML loading with validation and hashing
==========================================================================

Loads Domain Pack configurations from YAML files with:
- Full Pydantic validation
- Config hash computation for determinism
- Environment variable overrides
- Hot-reload support
- Audit logging of configuration changes

Compliance: SWE-032 (Data Validation), SWE-033 (Requirements Traceability)
Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from gptl.schema import (
    ConstraintAction,
    ConstraintCondition,
    ConstraintRule,
    DerivationCondition,
    DerivationRule,
    DomainPack,
    EscalationTrigger,
    EvidenceRequirements,
    EvidenceTaxonomy,
    EvidenceType,
    IntentCategory,
    IntentFrame,
    LLMPolicies,
    ModelPolicy,
    ModelPolicyEntry,
    ModelTier,
    RetrievalDeterminismConfig,
    ScoringPolicy,
)

__safety_critical__: bool = True

logger = logging.getLogger(__name__)


class SafetyCriticalError(Exception):
    """Base exception for safety-critical configuration errors."""
    pass


class ConfigValidationError(SafetyCriticalError):
    """Configuration validation failed."""
    pass


class ConfigNotFoundError(SafetyCriticalError):
    """Configuration file not found."""
    pass


class DomainPackLoader:
    """
    Loads and validates Domain Pack configurations.

    Features:
    - YAML loading with Pydantic validation
    - Config hash computation for determinism
    - Hot-reload support
    - Audit logging

    Compliance: SWE-032, SWE-033
    """

    DEFAULT_CONFIG_DIRS = [
        Path(__file__).parent / "domains",  # Inside gptl package
        Path("config/domains"),  # Relative to CWD (dev mode)
        Path.home() / ".gptl" / "domains",
        Path("/etc/gptl/domains"),
    ]

    def __init__(self, config_dirs: list[Path] | None = None):
        """
        Initialize the loader.

        Args:
            config_dirs: List of directories to search for domain configs.
                        If None, uses DEFAULT_CONFIG_DIRS.
        """
        self.config_dirs = config_dirs or self.DEFAULT_CONFIG_DIRS
        self._cache: dict[str, tuple[DomainPack, float]] = {}  # domain_id -> (pack, mtime)
        self._file_paths: dict[str, Path] = {}  # domain_id -> file path
        logger.info(f"DomainPackLoader initialized with {len(self.config_dirs)} search paths")

    def load(self, domain_id: str, force_reload: bool = False) -> DomainPack:
        """
        Load a Domain Pack by ID.

        Args:
            domain_id: The domain identifier (e.g., "mira", "aegis", "rr")
            force_reload: If True, bypass cache and reload from disk

        Returns:
            Validated DomainPack instance

        Raises:
            ConfigNotFoundError: If domain config file not found
            ConfigValidationError: If config fails validation
        """
        # Check cache
        if not force_reload and domain_id in self._cache:
            pack, cached_mtime = self._cache[domain_id]
            file_path = self._file_paths.get(domain_id)

            if file_path and file_path.exists():
                current_mtime = file_path.stat().st_mtime
                if current_mtime <= cached_mtime:
                    logger.debug(f"Using cached DomainPack for '{domain_id}'")
                    return pack

        # Find config file
        file_path = self._find_config_file(domain_id)
        if not file_path:
            raise ConfigNotFoundError(
                f"Domain config not found for '{domain_id}'. "
                f"Searched: {[str(d) for d in self.config_dirs]}"
            )

        # Load and validate
        pack = self._load_from_file(file_path, domain_id)

        # Cache
        self._cache[domain_id] = (pack, file_path.stat().st_mtime)
        self._file_paths[domain_id] = file_path

        logger.info(
            f"Loaded DomainPack '{domain_id}' v{pack.version} "
            f"(config_hash: {pack.config_hash})"
        )

        return pack

    def load_with_overrides(
        self,
        domain_id: str,
        overrides: dict[str, Any] | None = None
    ) -> DomainPack:
        """
        Load a Domain Pack with runtime overrides.

        Args:
            domain_id: The domain identifier
            overrides: Dictionary of override values

        Returns:
            DomainPack with overrides applied

        Note:
            Overrides change the config_hash.
        """
        base_pack = self.load(domain_id)

        if not overrides:
            return base_pack

        # Apply overrides to a copy
        pack_dict = base_pack.model_dump()
        pack_dict = self._deep_merge(pack_dict, overrides)

        # Clear config_hash so it gets recomputed
        pack_dict["config_hash"] = ""

        try:
            pack = DomainPack.model_validate(pack_dict)
            logger.info(
                f"Applied {len(overrides)} overrides to DomainPack '{domain_id}' "
                f"(new config_hash: {pack.config_hash})"
            )
            return pack
        except ValidationError as e:
            raise ConfigValidationError(f"Invalid override: {e}") from e

    def list_available_domains(self) -> list[str]:
        """List all available domain IDs."""
        domains = set()

        for config_dir in self.config_dirs:
            if config_dir.exists():
                for file_path in config_dir.glob("*.yaml"):
                    domains.add(file_path.stem)
                for file_path in config_dir.glob("*.yml"):
                    domains.add(file_path.stem)

        return sorted(domains)

    def clear_cache(self, domain_id: str | None = None):
        """Clear the cache for a domain or all domains."""
        if domain_id:
            self._cache.pop(domain_id, None)
            self._file_paths.pop(domain_id, None)
            logger.info(f"Cleared cache for domain '{domain_id}'")
        else:
            self._cache.clear()
            self._file_paths.clear()
            logger.info("Cleared all domain cache")

    def _find_config_file(self, domain_id: str) -> Path | None:
        """Find the config file for a domain."""
        for config_dir in self.config_dirs:
            for ext in [".yaml", ".yml"]:
                file_path = config_dir / f"{domain_id}{ext}"
                if file_path.exists():
                    return file_path
        return None

    def _load_from_file(self, file_path: Path, domain_id: str) -> DomainPack:
        """Load and validate a Domain Pack from a file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw_config = yaml.safe_load(f)

            if not raw_config:
                raise ConfigValidationError(f"Empty config file: {file_path}")

            # Parse the YAML structure into Pydantic models
            pack = self._parse_domain_pack(raw_config, domain_id)

            return pack

        except yaml.YAMLError as e:
            raise ConfigValidationError(f"Invalid YAML in {file_path}: {e}") from e
        except ValidationError as e:
            raise ConfigValidationError(f"Validation failed for {file_path}: {e}") from e

    def _parse_domain_pack(self, raw: dict[str, Any], domain_id: str) -> DomainPack:
        """Parse raw YAML dict into DomainPack."""

        # Parse evidence taxonomy
        evidence_taxonomy = self._parse_evidence_taxonomy(
            raw.get("evidence_taxonomy", {})
        )

        # Parse evidence derivation rules
        evidence_derivation = self._parse_derivation_rules(
            raw.get("evidence_derivation", [])
        )

        # Parse constraints
        constraints = self._parse_constraints(raw.get("constraints", {}))

        # Parse intent frames
        intent_frames = self._parse_intent_frames(raw.get("intent_frames", []))

        # Parse model policy
        model_policy = self._parse_model_policy(raw.get("model_policy", {}))

        # Parse scoring policy
        scoring_policy = self._parse_scoring_policy(raw.get("scoring_policy", {}))

        # Parse LLM policies
        llm_policies = self._parse_llm_policies(raw.get("llm_policies", {}))

        # Parse retrieval determinism
        retrieval_determinism = self._parse_retrieval_determinism(
            raw.get("retrieval_determinism", {})
        )

        return DomainPack(
            domain_id=raw.get("domain_id", domain_id),
            version=raw.get("version", "1.0.0"),
            config_hash="",  # Will be computed by validator
            model_policy=model_policy,
            evidence_taxonomy=evidence_taxonomy,
            evidence_derivation=evidence_derivation,
            constraints=constraints,
            intent_frames=intent_frames,
            scoring_policy=scoring_policy,
            llm_policies=llm_policies,
            retrieval_determinism=retrieval_determinism,
        )

    def _parse_evidence_taxonomy(self, raw: dict[str, Any]) -> EvidenceTaxonomy:
        """Parse evidence taxonomy from YAML."""
        return EvidenceTaxonomy(
            primary=[EvidenceType(t) for t in raw.get("primary", [])],
            supporting=[EvidenceType(t) for t in raw.get("supporting", [])],
            contextual=[EvidenceType(t) for t in raw.get("contextual", [])],
            noise=[EvidenceType(t) for t in raw.get("noise", [])],
        )

    def _parse_derivation_rules(self, raw: list[dict]) -> list[DerivationRule]:
        """Parse derivation rules from YAML."""
        rules = []
        for rule_data in raw:
            conditions = [
                DerivationCondition(
                    field=c["field"],
                    operator=c.get("operator", "eq"),
                    value=c["value"],
                )
                for c in rule_data.get("conditions", [])
            ]

            any_of = None
            if "any_of" in rule_data:
                any_of = [
                    DerivationCondition(
                        field=c["field"],
                        operator=c.get("operator", "eq"),
                        value=c["value"],
                    )
                    for c in rule_data["any_of"]
                ]

            rules.append(DerivationRule(
                rule_id=rule_data["rule_id"],
                conditions=conditions,
                any_of=any_of,
                result=[EvidenceType(t) for t in rule_data.get("result", [])],
                validate_with_llm=rule_data.get("validate_with_llm", True),
            ))

        return rules

    def _parse_constraints(
        self,
        raw: dict[str, Any]
    ) -> dict[str, list[ConstraintRule]]:
        """Parse constraint rules from YAML."""
        result = {"hard_drop": [], "soft_drop": []}

        for action_type in ["hard_drop", "soft_drop"]:
            for rule_data in raw.get(action_type, []):
                conditions = [
                    ConstraintCondition(
                        field=c["field"],
                        operator=c.get("operator", "eq"),
                        value=c["value"],
                        negate=c.get("negate", False),
                    )
                    for c in rule_data.get("conditions", [])
                ]

                action = (
                    ConstraintAction.HARD_DROP
                    if action_type == "hard_drop"
                    else ConstraintAction.SOFT_DROP
                )

                result[action_type].append(ConstraintRule(
                    rule_id=rule_data["rule_id"],
                    name=rule_data.get("name", rule_data["rule_id"]),
                    description=rule_data.get("description", ""),
                    action=action,
                    conditions=conditions,
                    applies_to_intents=rule_data.get("applies_to_intents", []),
                    priority=rule_data.get("priority", 100),
                    penalty_weight=rule_data.get("penalty_weight"),
                    requires_semantic_check=rule_data.get("requires_semantic_check", False),
                    semantic_check_prompt=rule_data.get("semantic_check_prompt"),
                ))

        return result

    def _parse_intent_frames(self, raw: list[dict]) -> list[IntentFrame]:
        """Parse intent frames from YAML."""
        frames = []

        for frame_data in raw:
            evidence_req_data = frame_data.get("evidence_requirements", {})
            evidence_types = [
                EvidenceType(t) for t in evidence_req_data.get("types", [])
            ]

            evidence_req = EvidenceRequirements(
                types=evidence_types,
                min_count=evidence_req_data.get("min_count", 1),
                required_entity_classes=evidence_req_data.get("required_entity_classes", []),
            )

            frames.append(IntentFrame(
                frame_id=frame_data["frame_id"],
                category=IntentCategory(frame_data["category"]),
                decision_question=frame_data["decision_question"],
                surface_patterns=frame_data.get("surface_patterns", []),
                evidence_requirements=evidence_req,
                constraint_ids=frame_data.get("constraint_ids", []),
                quality_tier_default=frame_data.get("quality_tier_default", "standard"),
            ))

        return frames

    def _parse_model_policy(self, raw: dict[str, Any]) -> ModelPolicy:
        """Parse model policy from YAML."""
        if not raw:
            return ModelPolicy()

        def parse_entry(entry_data: dict | None) -> ModelPolicyEntry | None:
            if not entry_data:
                return None

            trigger_data = entry_data.get("escalation_trigger", {})
            trigger = None
            if trigger_data:
                intent_cats = None
                if "intent_categories" in trigger_data:
                    intent_cats = [
                        IntentCategory(c) for c in trigger_data["intent_categories"]
                    ]
                trigger = EscalationTrigger(
                    confidence_lt=trigger_data.get("confidence_lt"),
                    query_complexity=trigger_data.get("query_complexity"),
                    intent_categories=intent_cats,
                    evidence_conflict_detected=trigger_data.get("evidence_conflict_detected"),
                )

            escalate_to = None
            if entry_data.get("escalate_to"):
                escalate_to = ModelTier(entry_data["escalate_to"])

            return ModelPolicyEntry(
                primary=ModelTier(entry_data["primary"]),
                escalate_to=escalate_to,
                escalation_trigger=trigger,
            )

        return ModelPolicy(
            intent_classification=parse_entry(raw.get("intent_classification")) or ModelPolicy().intent_classification,
            synthesis=parse_entry(raw.get("synthesis")) or ModelPolicy().synthesis,
            feature_extraction=parse_entry(raw.get("feature_extraction")) or ModelPolicy().feature_extraction,
            semantic_checks=parse_entry(raw.get("semantic_checks")) or ModelPolicy().semantic_checks,
            anomaly_explanation=parse_entry(raw.get("anomaly_explanation")) or ModelPolicy().anomaly_explanation,
            confidence_calibration=parse_entry(raw.get("confidence_calibration")) or ModelPolicy().confidence_calibration,
        )

    def _parse_scoring_policy(self, raw: dict[str, Any]) -> ScoringPolicy:
        """Parse scoring policy from YAML."""
        if not raw:
            return ScoringPolicy()

        return ScoringPolicy(
            soft_drop_penalty_weight=raw.get("soft_drop_penalty_weight", 0.1),
            soft_drop_penalty_function=raw.get("soft_drop_penalty_function", "multiplicative"),
            soft_drop_penalty_cap=raw.get("soft_drop_penalty_cap", 0.5),
            log_penalty_in_audit=raw.get("log_penalty_in_audit", True),
        )

    def _parse_llm_policies(self, raw: dict[str, Any]) -> LLMPolicies:
        """Parse LLM policies from YAML."""
        if not raw:
            return LLMPolicies()

        return LLMPolicies(
            l0_derivation_validation=raw.get("l0_derivation_validation", True),
            l2_intent_always_llm=raw.get("l2_intent_always_llm", True),
            l3_semantic_checks_enabled=raw.get("l3_semantic_checks_enabled", True),
            l4_anomaly_explanation=raw.get("l4_anomaly_explanation", True),
            l5_confidence_calibration=raw.get("l5_confidence_calibration", True),
        )

    def _parse_retrieval_determinism(
        self,
        raw: dict[str, Any]
    ) -> RetrievalDeterminismConfig:
        """Parse retrieval determinism config from YAML."""
        if not raw:
            return RetrievalDeterminismConfig()

        return RetrievalDeterminismConfig(
            index_snapshot_required=raw.get("index_snapshot_required", True),
            search_params_locked=raw.get("search_params_locked", True),
            tie_breaking=raw.get("tie_breaking", "doc_id_ascending"),
            random_seed=raw.get("random_seed"),
            nprobe=raw.get("nprobe"),
            ef_search=raw.get("ef_search"),
        )

    def _deep_merge(self, base: dict, override: dict) -> dict:
        """Deep merge two dictionaries."""
        result = base.copy()

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value

        return result


# =============================================================================
# GLOBAL LOADER INSTANCE
# =============================================================================

_loader: DomainPackLoader | None = None


def get_loader() -> DomainPackLoader:
    """Get the global DomainPackLoader instance."""
    global _loader
    if _loader is None:
        _loader = DomainPackLoader()
    return _loader


def load_domain_pack(
    domain_id: str,
    overrides: dict[str, Any] | None = None,
    force_reload: bool = False
) -> DomainPack:
    """
    Load a Domain Pack by ID.

    This is the primary API for loading domain configurations.

    Args:
        domain_id: The domain identifier (e.g., "mira", "aegis", "rr")
        overrides: Optional runtime overrides
        force_reload: If True, bypass cache

    Returns:
        Validated DomainPack instance

    Example:
        >>> pack = load_domain_pack("mira")
        >>> print(pack.config_hash)
        'a1b2c3d4e5f6g7h8'
    """
    loader = get_loader()

    if overrides:
        return loader.load_with_overrides(domain_id, overrides)
    else:
        return loader.load(domain_id, force_reload=force_reload)


def compute_config_hash(pack: DomainPack) -> str:
    """Compute the config hash for a DomainPack."""
    return pack.compute_config_hash()


def validate_domain_pack(raw_config: dict[str, Any], domain_id: str) -> DomainPack:
    """
    Validate a raw config dictionary as a DomainPack.

    Useful for validating configs before writing to disk.

    Args:
        raw_config: Raw configuration dictionary
        domain_id: Domain identifier

    Returns:
        Validated DomainPack

    Raises:
        ConfigValidationError: If validation fails
    """
    loader = get_loader()
    try:
        return loader._parse_domain_pack(raw_config, domain_id)
    except ValidationError as e:
        raise ConfigValidationError(f"Invalid config: {e}") from e


__all__ = [
    "DomainPackLoader",
    "ConfigValidationError",
    "ConfigNotFoundError",
    "SafetyCriticalError",
    "get_loader",
    "load_domain_pack",
    "compute_config_hash",
    "validate_domain_pack",
]
