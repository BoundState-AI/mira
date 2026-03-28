from __future__ import annotations

import importlib
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BOUNDSTATE_ROOT = REPO_ROOT.parent
SENTINEL_MAIN_ROOT = REPO_ROOT / "sentinel-main"
FORGE_ROOT = BOUNDSTATE_ROOT / "boundstate_forge"


def ensure_external_paths() -> None:
    for path in (SENTINEL_MAIN_ROOT, FORGE_ROOT):
        path_str = str(path)
        if path.exists() and path_str not in sys.path:
            sys.path.insert(0, path_str)


def _alias_module(alias: str, target: str) -> None:
    if alias in sys.modules:
        return
    module = importlib.import_module(target)
    sys.modules[alias] = module


def bootstrap_forge_aliases() -> None:
    ensure_external_paths()

    aliases = {
        "mira.forge_claude.contracts": "forge_claude.contracts",
        "mira.forge_claude.contracts.models": "forge_claude.contracts.models",
        "mira.forge_claude.contracts.generator": "forge_claude.contracts.generator",
        "mira.forge_claude.contracts.resolver": "forge_claude.contracts.resolver",
        "mira.forge_claude.data_profile": "forge_claude.data_profile",
        "mira.forge_claude.data_profile.analyzer": "forge_claude.data_profile.analyzer",
        "mira.forge_claude.chat": "forge_claude.chat",
        "mira.forge_claude.chat.personality": "forge_claude.chat.personality",
        "mira.forge_claude.chat.module_context": "forge_claude.chat.module_context",
        "mira.forge_claude.bsms_engine": "forge_claude.bsms_engine",
        "mira.forge_claude.bsms_engine.evidence": "forge_claude.bsms_engine.evidence",
        "mira.forge_claude.bsms_engine.bouncer": "forge_claude.bsms_engine.bouncer",
        "mira.forge_claude.bsms_engine.pipeline": "forge_claude.bsms_engine.pipeline",
        "mira.forge_claude.prompt_compiler": "forge_claude.prompt_compiler",
        "mira.forge_claude.prompt_compiler.compiler": "forge_claude.prompt_compiler.compiler",
        "mira.forge_claude.forge_pipeline": "forge_claude.forge_pipeline",
    }

    for alias, target in aliases.items():
        try:
            _alias_module(alias, target)
        except ModuleNotFoundError:
            continue


def import_gptl_schema():
    ensure_external_paths()
    return importlib.import_module("gptl.schema")


def import_gptl_engine():
    ensure_external_paths()
    return importlib.import_module("gptl.engine")


def import_gptl_feature_extractor():
    ensure_external_paths()
    return importlib.import_module("gptl.feature_extractor")


def import_forge_contract_models():
    ensure_external_paths()
    bootstrap_forge_aliases()
    return importlib.import_module("forge_claude.contracts.models")


def import_forge_evidence_module():
    ensure_external_paths()
    bootstrap_forge_aliases()
    return importlib.import_module("forge_claude.bsms_engine.evidence")


def import_forge_bouncer_module():
    ensure_external_paths()
    bootstrap_forge_aliases()
    return importlib.import_module("forge_claude.bsms_engine.bouncer")


def import_forge_personality_module():
    ensure_external_paths()
    bootstrap_forge_aliases()
    return importlib.import_module("forge_claude.chat.personality")
