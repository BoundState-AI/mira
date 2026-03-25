#!/usr/bin/env python3
"""
Module: OCA Systems Router (Phase 2)
Purpose: Visual System Builder API endpoints per BS-SPEC-OCA-002-REV0 §14.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6001B, NASA-STD-6016C, SWE-013, SWE-032
Safety Critical: True
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from mira.api.auth import authorize_owner_or_admin, get_request_user
from mira.oca.system_store import get_oca_system_store
from mira.oca.system_models import (
    AddComponentRequest,
    AddComponentResponse,
    AddConnectionRequest,
    AddConnectionResponse,
    ComponentConfig,
    CreateSystemRequest,
    CreateSystemResponse,
    InferredFact,
    MaterialSlotValue,
    OCASystemAssembly,
    SystemAssessmentResponse,
    SystemComponent,
    SystemConnection,
    SystemExportResponse,
    SystemKindlingChainResponse,
    TopologyResponse,
    VisionMockupResponse,
)

LOGGER = logging.getLogger(__name__)

router = APIRouter()


def _get_system(system_id: str) -> OCASystemAssembly:
    return get_oca_system_store().get(system_id)


def _save_system(system: OCASystemAssembly) -> None:
    get_oca_system_store().save(system)


def _delete_system(system_id: str) -> None:
    get_oca_system_store().delete(system_id)


async def _load_system_for_request(system_id: str, http_request: Request) -> OCASystemAssembly:
    try:
        system = await asyncio.to_thread(_get_system, system_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"System {system_id} not found") from exc
    authorize_owner_or_admin(http_request, system.owner_username, resource_label="oca system")
    return system


# =============================================================================
# ENDPOINTS (per Spec §14)
# =============================================================================


@router.get("/ping")
async def ping() -> dict[str, str]:
    """Health check for OCA Systems endpoint."""
    return {"status": "ok", "domain": "oca-systems", "version": "1.0.0"}


@router.post("", response_model=CreateSystemResponse)
async def create_system(request: CreateSystemRequest, http_request: Request) -> CreateSystemResponse:
    """Create a new system assembly."""
    try:
        actor = get_request_user(http_request)
        system = OCASystemAssembly(
            name=request.name,
            description=request.description,
            owner_username=actor.username if actor else None,
            inputs=request.inputs,
        )
        await asyncio.to_thread(_save_system, system)

        LOGGER.info(f"[OCA Systems] Created system: {system.system_id} '{system.name}'")

        return CreateSystemResponse(
            system_id=system.system_id,
            name=system.name,
            blocked_states=system.system_blocked_states,
        )
    except Exception as exc:
        LOGGER.error(f"[OCA Systems] Create error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{system_id}")
async def get_system(system_id: str, http_request: Request) -> dict[str, Any]:
    """Get full system state."""
    system = await _load_system_for_request(system_id, http_request)
    return system.model_dump()


@router.delete("/{system_id}")
async def delete_system(system_id: str, http_request: Request) -> dict[str, str]:
    """Delete a system assembly."""
    await _load_system_for_request(system_id, http_request)
    await asyncio.to_thread(_delete_system, system_id)
    return {"status": "deleted"}


@router.put("/{system_id}/inputs")
async def update_inputs(system_id: str, inputs: dict[str, Any], http_request: Request) -> dict[str, str]:
    """Update system-level inputs."""
    system = await _load_system_for_request(system_id, http_request)
    if system.locked:
        raise HTTPException(status_code=409, detail="System is locked")

    from mira.oca.system_models import SystemInputs
    system.inputs = SystemInputs(**{**system.inputs.model_dump(), **inputs})
    system.updated_at = datetime.utcnow()
    system.audit_log.append({
        "action": "update_inputs",
        "changes": inputs,
        "timestamp": datetime.utcnow().isoformat(),
    })
    await asyncio.to_thread(_save_system, system)
    return {"status": "updated"}


@router.post("/{system_id}/vision/mockup", response_model=VisionMockupResponse)
async def build_vision_mockup(
    system_id: str,
    http_request: Request,
    image: UploadFile = File(...),
    flow_direction_hint: str = Form("unknown"),
    notes: str = Form(""),
) -> VisionMockupResponse:
    """Generate a provisional canvas mockup from an uploaded system image."""
    try:
        system = await _load_system_for_request(system_id, http_request)
        payload = await image.read()

        from mira.oca.system_vision import OCASystemVisionService

        service = OCASystemVisionService()
        result = VisionMockupResponse.model_validate(await asyncio.to_thread(
            service.build_mockup,
            system_id=system_id,
            image_bytes=payload,
            media_type=image.content_type or "",
            filename=image.filename or "upload.png",
            flow_direction_hint=flow_direction_hint,
            notes=notes,
            current_inputs=system.inputs,
        ))

        system.audit_log.append({
            "action": "vision_mockup_preview",
            "filename": image.filename or "upload.png",
            "components": len(result.components),
            "connections": len(result.connections),
            "questions": len(result.questions),
            "timestamp": datetime.utcnow().isoformat(),
        })
        system.updated_at = datetime.utcnow()
        await asyncio.to_thread(_save_system, system)
        return result
    except ValueError as exc:
        LOGGER.warning(f"[OCA Systems] Vision mockup rejected: {exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.error(f"[OCA Systems] Vision mockup error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate vision mockup") from exc


@router.post("/{system_id}/components", response_model=AddComponentResponse)
async def add_component(
    system_id: str,
    request: AddComponentRequest,
    http_request: Request,
) -> AddComponentResponse:
    """Add a component to the canvas."""
    try:
        system = await _load_system_for_request(system_id, http_request)
        if system.locked:
            raise HTTPException(status_code=409, detail="System is locked")

        from mira.oca.system_engine import derive_features

        # Create component
        comp = SystemComponent(
            archetype=request.archetype,
            label=request.label or request.archetype.value,
            position_x=request.position_x,
            position_y=request.position_y,
            materials=request.materials,
            config=request.config,
        )

        # Derive features
        comp.features = derive_features(request.archetype, request.config, request.materials)

        system.components.append(comp)
        system.updated_at = datetime.utcnow()
        system.audit_log.append({
            "action": "add_component",
            "component_id": comp.component_id,
            "archetype": request.archetype.value,
            "label": comp.label,
            "timestamp": datetime.utcnow().isoformat(),
        })
        await asyncio.to_thread(_save_system, system)

        LOGGER.info(f"[OCA Systems] Added {request.archetype.value} to {system_id}")

        return AddComponentResponse(
            component_id=comp.component_id,
            features=comp.features,
            zones=comp.zones,
            inferred_facts=comp.inferred_facts,
        )
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.error(f"[OCA Systems] Add component error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/{system_id}/components/{component_id}")
async def update_component(
    system_id: str,
    component_id: str,
    updates: dict[str, Any],
    http_request: Request,
) -> dict[str, Any]:
    """Update a component's properties."""
    system = await _load_system_for_request(system_id, http_request)
    if system.locked:
        raise HTTPException(status_code=409, detail="System is locked")

    comp = None
    for c in system.components:
        if c.component_id == component_id:
            comp = c
            break

    if not comp:
        raise HTTPException(status_code=404, detail=f"Component {component_id} not found")

    if "config" in updates:
        base_config = comp.config.model_dump() if hasattr(comp.config, "model_dump") else dict(comp.config)
        comp.config = ComponentConfig(**{**base_config, **updates["config"]})

    if "materials" in updates:
        comp.materials = [
            item if isinstance(item, MaterialSlotValue) else MaterialSlotValue(**item)
            for item in updates["materials"]
        ]
    if "inferred_facts" in updates:
        comp.inferred_facts = [
            item if isinstance(item, InferredFact) else InferredFact(**item)
            for item in updates["inferred_facts"]
        ]

    # Apply scalar updates after nested-model coercion.
    for key, value in updates.items():
        if key in {"component_id", "archetype", "config", "materials", "inferred_facts"}:
            continue
        if hasattr(comp, key):
            setattr(comp, key, value)

    # Re-derive features if materials or config changed
    if "materials" in updates or "config" in updates:
        from mira.oca.system_engine import derive_features
        comp.features = derive_features(comp.archetype, comp.config, comp.materials)

    system.updated_at = datetime.utcnow()
    system.audit_log.append({
        "action": "update_component",
        "component_id": component_id,
        "changes": list(updates.keys()),
        "timestamp": datetime.utcnow().isoformat(),
    })
    await asyncio.to_thread(_save_system, system)

    return {"status": "updated", "component": comp.model_dump()}


@router.delete("/{system_id}/components/{component_id}")
async def remove_component(
    system_id: str,
    component_id: str,
    http_request: Request,
) -> dict[str, str]:
    """Remove a component from the canvas."""
    system = await _load_system_for_request(system_id, http_request)
    if system.locked:
        raise HTTPException(status_code=409, detail="System is locked")

    system.components = [c for c in system.components if c.component_id != component_id]
    system.connections = [
        conn for conn in system.connections
        if conn.source_component_id != component_id and conn.target_component_id != component_id
    ]
    system.updated_at = datetime.utcnow()
    system.audit_log.append({
        "action": "remove_component",
        "component_id": component_id,
        "timestamp": datetime.utcnow().isoformat(),
    })
    await asyncio.to_thread(_save_system, system)

    return {"status": "removed"}


@router.post("/{system_id}/connections", response_model=AddConnectionResponse)
async def add_connection(
    system_id: str,
    request: AddConnectionRequest,
    http_request: Request,
) -> AddConnectionResponse:
    """Connect two components."""
    try:
        system = await _load_system_for_request(system_id, http_request)
        if system.locked:
            raise HTTPException(status_code=409, detail="System is locked")

        # Validate components exist
        comp_ids = {c.component_id for c in system.components}
        if request.source_component_id not in comp_ids:
            raise HTTPException(status_code=404, detail=f"Source component {request.source_component_id} not found")
        if request.target_component_id not in comp_ids:
            raise HTTPException(status_code=404, detail=f"Target component {request.target_component_id} not found")

        conn = SystemConnection(
            source_component_id=request.source_component_id,
            source_port=request.source_port,
            target_component_id=request.target_component_id,
            target_port=request.target_port,
        )
        system.connections.append(conn)
        system.updated_at = datetime.utcnow()
        system.audit_log.append({
            "action": "add_connection",
            "connection_id": conn.connection_id,
            "source": request.source_component_id,
            "target": request.target_component_id,
            "timestamp": datetime.utcnow().isoformat(),
        })
        await asyncio.to_thread(_save_system, system)

        # Determine affected components
        from mira.oca.system_engine import build_adjacency, get_downstream_ids
        forward, _ = build_adjacency(system.components, system.connections)
        affected = get_downstream_ids(request.source_component_id, forward)
        affected.add(request.source_component_id)
        affected.add(request.target_component_id)

        return AddConnectionResponse(
            connection_id=conn.connection_id,
            topology_changed=True,
            affected_component_ids=list(affected),
        )
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.error(f"[OCA Systems] Connection error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/{system_id}/connections/{connection_id}")
async def remove_connection(
    system_id: str,
    connection_id: str,
    http_request: Request,
) -> dict[str, str]:
    """Remove a connection."""
    system = await _load_system_for_request(system_id, http_request)
    if system.locked:
        raise HTTPException(status_code=409, detail="System is locked")

    system.connections = [c for c in system.connections if c.connection_id != connection_id]
    system.updated_at = datetime.utcnow()
    system.audit_log.append({
        "action": "remove_connection",
        "connection_id": connection_id,
        "timestamp": datetime.utcnow().isoformat(),
    })
    await asyncio.to_thread(_save_system, system)
    return {"status": "removed"}


@router.post("/{system_id}/assess", response_model=SystemAssessmentResponse)
async def assess_system(system_id: str, http_request: Request) -> SystemAssessmentResponse:
    """Run full system OCA assessment."""
    try:
        system = await _load_system_for_request(system_id, http_request)

        from mira.oca.system_engine import run_system_assessment
        await asyncio.to_thread(run_system_assessment, system)
        await asyncio.to_thread(_save_system, system)

        return SystemAssessmentResponse(
            system_id=system_id,
            system_disposition=system.system_disposition or "insufficient_evidence",
            system_reaction_effect=system.system_reaction_effect or "A",
            components=system.components,
            kindling_chains=system.kindling_chains,
            triggered_requirements=system.system_triggered_requirements,
            blocked_states=system.system_blocked_states,
            hazard_controls=system.system_hazard_controls,
            has_titanium=system.has_titanium,
            mpr67_active=system.mpr67_active,
        )
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.error(f"[OCA Systems] Assessment error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{system_id}/topology", response_model=TopologyResponse)
async def get_topology(system_id: str, http_request: Request) -> TopologyResponse:
    """Return inferred topology with zones and assumptions."""
    try:
        system = await _load_system_for_request(system_id, http_request)

        from mira.oca.system_engine import run_topology_inference
        topology = await asyncio.to_thread(run_topology_inference, system)
        system.topology = topology
        system.updated_at = datetime.utcnow()
        await asyncio.to_thread(_save_system, system)

        return TopologyResponse(
            system_id=system_id,
            topology=topology,
            zones=topology.zone_assignments,
        )
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.error(f"[OCA Systems] Topology error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{system_id}/kindling-chain", response_model=SystemKindlingChainResponse)
async def get_kindling_chain(system_id: str, http_request: Request) -> SystemKindlingChainResponse:
    """Return system propagation map."""
    try:
        system = await _load_system_for_request(system_id, http_request)

        if not system.kindling_chains:
            from mira.oca.system_engine import run_system_assessment
            await asyncio.to_thread(run_system_assessment, system)
            await asyncio.to_thread(_save_system, system)

        from mira.oca.models import ReactionEffect
        worst = ReactionEffect.A
        effect_order = [ReactionEffect.A, ReactionEffect.B, ReactionEffect.C, ReactionEffect.D]
        for chain in system.kindling_chains:
            if effect_order.index(chain.reaction_effect) > effect_order.index(worst):
                worst = chain.reaction_effect

        return SystemKindlingChainResponse(
            system_id=system_id,
            chains=system.kindling_chains,
            worst_case_effect=worst,
        )
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.error(f"[OCA Systems] Kindling chain error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{system_id}/path/{component_id}")
async def get_path_inspector(system_id: str, component_id: str, http_request: Request) -> dict[str, Any]:
    """Path inspector for specific component."""
    try:
        system = await _load_system_for_request(system_id, http_request)

        from mira.oca.system_engine import inspect_component_path
        result = await asyncio.to_thread(inspect_component_path, system, component_id)

        return result.model_dump()
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.error(f"[OCA Systems] Path inspector error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{system_id}/export")
async def export_system(system_id: str, http_request: Request) -> dict[str, Any]:
    """System-level report, BOM, MIUL seed, zone map export."""
    try:
        system = await _load_system_for_request(system_id, http_request)

        # Ensure assessment has been run
        if not system.system_disposition:
            from mira.oca.system_engine import run_system_assessment
            await asyncio.to_thread(run_system_assessment, system)
            await asyncio.to_thread(_save_system, system)

        from mira.oca.system_engine import generate_system_export
        return await asyncio.to_thread(generate_system_export, system)
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.error(f"[OCA Systems] Export error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{system_id}/library")
async def get_component_library(system_id: str, http_request: Request) -> dict[str, Any]:
    """Return the component archetype library."""
    await _load_system_for_request(system_id, http_request)
    import json
    from pathlib import Path

    lib_path = Path(__file__).parent.parent.parent / "oca" / "data" / "oca_component_library.json"
    if not lib_path.exists():
        raise HTTPException(status_code=500, detail="Component library not found")

    with open(lib_path) as f:
        return json.load(f)


@router.post("/{system_id}/lock")
async def lock_system(system_id: str, http_request: Request) -> dict[str, Any]:
    """Lock system for export."""
    system = await _load_system_for_request(system_id, http_request)
    system.locked = True
    system.updated_at = datetime.utcnow()
    system.audit_log.append({
        "action": "lock_system",
        "timestamp": datetime.utcnow().isoformat(),
    })
    await asyncio.to_thread(_save_system, system)
    return {"system_id": system_id, "locked": True, "locked_at": datetime.utcnow().isoformat()}


__safety_critical__ = True
