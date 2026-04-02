#!/usr/bin/env python3
"""
Module: Session Manager
Purpose: Session CRUD and persistence for M&P Plan Generator V2.

Persists session state through the shared ``SessionStore`` from
``mira.core.session_store``.  All data is serialized via
``PlanGeneratorSession.model_dump(mode="json")`` and deserialized
via ``model_validate()`` on every read.

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from .models import (
    EnvironmentDefinition,
    MaterialEntry,
    MaterialEnvironmentUsage,
    PlanGeneratorSession,
)
from .policy import PolicyPack, create_default_policy_pack

LOGGER = logging.getLogger(__name__)

__version__ = "2.0.0"
__safety_critical__ = False

_MODULE = "mp_plan"


class SessionManager:
    """
    Manages M&P Plan Generator sessions.

    Provides CRUD operations with persistence through the shared
    ``SessionStore``.  Async methods (``acreate_session``, etc.) are
    the primary API for FastAPI handlers.  Sync wrappers are available
    for tests and non-async callers.
    """

    def __init__(
        self,
        default_policy_pack: Optional[PolicyPack] = None,
        storage_dir: Any | None = None,
    ):
        from mira.core.session_store import get_session_store
        self._store = get_session_store()
        self._default_policy = default_policy_pack or create_default_policy_pack()
        if storage_dir is not None:
            LOGGER.warning(
                "SessionManager(storage_dir=...) is deprecated and ignored; "
                "MP Plan sessions now persist through SessionStore."
            )

    # -- sync/async bridge --------------------------------------------------

    @staticmethod
    def _run_sync(coro: Any) -> Any:
        """Execute an async coroutine synchronously for non-async callers."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError(
            "SessionManager sync methods cannot be used inside a running event loop. "
            "Use the async SessionManager methods instead."
        )

    # -- internal store helpers ---------------------------------------------

    async def _save_async(self, session: PlanGeneratorSession) -> None:
        from mira.core.session_store import save_model
        await save_model(_MODULE, session.session_id, session, self._store)

    async def _load_async(self, session_id: str) -> Optional[PlanGeneratorSession]:
        from mira.core.session_store import load_model
        return await load_model(_MODULE, session_id, PlanGeneratorSession, self._store)

    async def _delete_async(self, session_id: str) -> bool:
        return await self._store.delete_module_data(_MODULE, session_id)

    async def _list_keys_async(self) -> list[str]:
        return await self._store.list_module_keys(_MODULE)

    # -- async CRUD ---------------------------------------------------------

    async def acreate_session(
        self,
        program_name: Optional[str] = None,
        program_phase: Optional[str] = None,
        policy_pack_id: Optional[str] = None,
        vehicle_preset: Optional[str] = None,
        owner_username: Optional[str] = None,
    ) -> PlanGeneratorSession:
        """Create a new session and persist it."""
        session_id = str(uuid.uuid4())[:8]

        session = PlanGeneratorSession(
            session_id=session_id,
            program_name=program_name,
            program_phase=program_phase,
            policy_pack_id=policy_pack_id or "default",
            owner_username=owner_username,
            source="session_manager",
        )

        # Auto-add environment from vehicle preset
        if vehicle_preset and vehicle_preset.upper() in self._default_policy.vehicle_environments:
            preset = self._default_policy.vehicle_environments[vehicle_preset.upper()]
            env = EnvironmentDefinition(
                name=preset["name"],
                o2_pct=preset["o2_pct"],
                pressure_psia=preset["pressure_psia"],
                temp_range_c=tuple(preset["temp_range_c"]),
                habitable=preset["habitable"],
                vacuum_exposure=preset.get("vacuum_exposure", False),
                lunar_dust=preset.get("lunar_dust", False),
                phase=preset.get("phase", "nominal"),
                source=preset.get("source", "policy_pack"),
            )
            session.environments.append(env)
            LOGGER.info(f"Auto-added environment: {env.name}")

        await self._save_async(session)
        LOGGER.info(f"Created session: {session_id}")
        return session

    async def aget_session(self, session_id: str) -> Optional[PlanGeneratorSession]:
        """Get session by ID, or None if not found."""
        return await self._load_async(session_id)

    async def aupdate_session(self, session: PlanGeneratorSession) -> None:
        """Persist updated session state.  Bumps ``updated_at``."""
        session.updated_at = datetime.now()
        await self._save_async(session)

    async def adelete_session(self, session_id: str) -> bool:
        """Delete a session.  Returns True if it existed."""
        existed = await self._delete_async(session_id)
        if existed:
            LOGGER.info(f"Deleted session: {session_id}")
        return existed

    async def alist_sessions(self) -> list[dict]:
        """List all sessions as summary dicts."""
        summaries = []
        for key in await self._list_keys_async():
            session = await self._load_async(key)
            if session is not None:
                summaries.append(self._session_summary(session))
        return summaries

    async def aadd_material(
        self,
        session_id: str,
        name: str,
        application: str,
        quantity: int = 1,
        maptis_code: Optional[str] = None,
        mass_g: Optional[float] = None,
        surface_area_cm2: Optional[float] = None,
    ) -> Optional[MaterialEntry]:
        """Add a material to a session."""
        session = await self._load_async(session_id)
        if not session:
            return None

        material = MaterialEntry(
            name=name,
            application=application,
            quantity=quantity,
            maptis_code=maptis_code,
            mass_g=mass_g,
            surface_area_cm2=surface_area_cm2,
            source="session_manager",
        )

        session.materials.append(material)

        # Auto-create environment mappings
        for env in session.environments:
            usage = MaterialEnvironmentUsage(
                material_id=material.id,
                environment_id=env.environment_id,
                location="unspecified",
            )
            session.material_environment_usages.append(usage)

        await self.aupdate_session(session)
        LOGGER.info(f"Added material to session {session_id}: {name}")
        return material

    async def aadd_environment(
        self,
        session_id: str,
        name: str,
        o2_pct: float,
        pressure_psia: float,
        temp_range_c: tuple[float, float],
        habitable: bool,
        vacuum_exposure: bool = False,
        lunar_dust: bool = False,
    ) -> Optional[EnvironmentDefinition]:
        """Add an environment to a session."""
        session = await self._load_async(session_id)
        if not session:
            return None

        env = EnvironmentDefinition(
            name=name,
            o2_pct=o2_pct,
            pressure_psia=pressure_psia,
            temp_range_c=temp_range_c,
            habitable=habitable,
            vacuum_exposure=vacuum_exposure,
            lunar_dust=lunar_dust,
            source="session_manager",
        )

        session.environments.append(env)

        # Auto-create mappings for existing materials
        for material in session.materials:
            usage = MaterialEnvironmentUsage(
                material_id=material.id,
                environment_id=env.environment_id,
                location="unspecified",
            )
            session.material_environment_usages.append(usage)

        await self.aupdate_session(session)
        LOGGER.info(f"Added environment to session {session_id}: {name}")
        return env

    # -- sync wrappers (for tests / non-async callers) ----------------------

    def create_session(self, **kwargs) -> PlanGeneratorSession:
        return self._run_sync(self.acreate_session(**kwargs))

    def get_session(self, session_id: str) -> Optional[PlanGeneratorSession]:
        return self._run_sync(self.aget_session(session_id))

    def update_session(self, session: PlanGeneratorSession) -> None:
        self._run_sync(self.aupdate_session(session))

    def delete_session(self, session_id: str) -> bool:
        return self._run_sync(self.adelete_session(session_id))

    def list_sessions(self) -> list[dict]:
        return self._run_sync(self.alist_sessions())

    def add_material(self, session_id: str, **kwargs) -> Optional[MaterialEntry]:
        return self._run_sync(self.aadd_material(session_id, **kwargs))

    def add_environment(self, session_id: str, **kwargs) -> Optional[EnvironmentDefinition]:
        return self._run_sync(self.aadd_environment(session_id, **kwargs))

    # -- helpers ------------------------------------------------------------

    def _session_summary(self, session: PlanGeneratorSession) -> dict:
        """Create session summary dict."""
        can_generate, blockers = session.can_generate()
        return {
            "session_id": session.session_id,
            "program_name": session.program_name,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "material_count": len(session.materials),
            "environment_count": len(session.environments),
            "nonconformance_count": len(session.nonconformances),
            "blocking_question_count": len(session.blocking_questions),
            "can_generate": can_generate,
            "blockers": blockers,
        }


# Global session manager instance
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get the global session manager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
        LOGGER.info("Session manager initialized with shared SessionStore backend")
    return _session_manager
