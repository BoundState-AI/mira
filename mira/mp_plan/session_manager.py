#!/usr/bin/env python3
"""
Module: Session Manager
Purpose: Session CRUD and persistence for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

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


class SessionManager:
    """
    Manages M&P Plan Generator sessions.

    Provides CRUD operations and persistence for sessions.
    """

    def __init__(
        self,
        storage_dir: Optional[Path] = None,
        default_policy_pack: Optional[PolicyPack] = None,
    ):
        """
        Initialize session manager.

        Args:
            storage_dir: Directory for session persistence (None for in-memory only).
            default_policy_pack: Default policy pack for new sessions.
        """
        self._sessions: dict[str, PlanGeneratorSession] = {}
        self._storage_dir = storage_dir
        self._default_policy = default_policy_pack or create_default_policy_pack()

        if storage_dir:
            storage_dir.mkdir(parents=True, exist_ok=True)

    def create_session(
        self,
        program_name: Optional[str] = None,
        program_phase: Optional[str] = None,
        policy_pack_id: Optional[str] = None,
        vehicle_preset: Optional[str] = None,
    ) -> PlanGeneratorSession:
        """
        Create a new session.

        Args:
            program_name: Optional program name.
            program_phase: Optional program phase.
            policy_pack_id: Optional policy pack ID.
            vehicle_preset: Optional vehicle preset to auto-add environment.

        Returns:
            New PlanGeneratorSession.
        """
        session_id = str(uuid.uuid4())[:8]

        session = PlanGeneratorSession(
            session_id=session_id,
            program_name=program_name,
            program_phase=program_phase,
            policy_pack_id=policy_pack_id or "default",
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

        self._sessions[session_id] = session

        # Persist to disk if storage configured
        if self._storage_dir:
            self._save_session(session)

        LOGGER.info(f"Created session: {session_id}")

        return session

    def get_session(self, session_id: str) -> Optional[PlanGeneratorSession]:
        """
        Get session by ID.

        Args:
            session_id: Session identifier.

        Returns:
            Session if found, None otherwise.
        """
        # Check in-memory first
        if session_id in self._sessions:
            return self._sessions[session_id]

        # Try loading from disk
        if self._storage_dir:
            session = self._load_session(session_id)
            if session:
                self._sessions[session_id] = session
                return session

        return None

    def update_session(self, session: PlanGeneratorSession) -> None:
        """
        Update a session.

        Args:
            session: Session to update.
        """
        session.updated_at = datetime.now()
        self._sessions[session.session_id] = session

        # Persist if storage configured
        if self._storage_dir:
            self._save_session(session)

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.

        Args:
            session_id: Session identifier.

        Returns:
            True if deleted, False if not found.
        """
        if session_id in self._sessions:
            del self._sessions[session_id]

            # Remove from disk
            if self._storage_dir:
                path = self._storage_dir / f"{session_id}.json"
                if path.exists():
                    path.unlink()

            LOGGER.info(f"Deleted session: {session_id}")
            return True

        return False

    def list_sessions(self) -> list[dict]:
        """
        List all sessions.

        Returns:
            List of session summaries.
        """
        summaries = []

        # In-memory sessions
        for session in self._sessions.values():
            summaries.append(self._session_summary(session))

        # Disk sessions not in memory
        if self._storage_dir:
            for path in self._storage_dir.glob("*.json"):
                session_id = path.stem
                if session_id not in self._sessions:
                    session = self._load_session(session_id)
                    if session:
                        summaries.append(self._session_summary(session))

        return summaries

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

    def add_material(
        self,
        session_id: str,
        name: str,
        application: str,
        quantity: int = 1,
        maptis_code: Optional[str] = None,
        mass_g: Optional[float] = None,
        surface_area_cm2: Optional[float] = None,
    ) -> Optional[MaterialEntry]:
        """
        Add a material to a session.

        Args:
            session_id: Session identifier.
            name: Material name.
            application: Material application.
            quantity: Item quantity.
            maptis_code: Optional MAPTIS code.
            mass_g: Optional mass in grams.
            surface_area_cm2: Optional surface area.

        Returns:
            Created MaterialEntry, or None if session not found.
        """
        session = self.get_session(session_id)
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

        self.update_session(session)
        LOGGER.info(f"Added material to session {session_id}: {name}")

        return material

    def add_environment(
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
        """
        Add an environment to a session.

        Args:
            session_id: Session identifier.
            name: Environment name.
            o2_pct: Oxygen percentage.
            pressure_psia: Pressure in psia.
            temp_range_c: Temperature range (min, max) in Celsius.
            habitable: Whether habitable.
            vacuum_exposure: Whether exposed to vacuum.
            lunar_dust: Whether exposed to lunar dust.

        Returns:
            Created EnvironmentDefinition, or None if session not found.
        """
        session = self.get_session(session_id)
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

        self.update_session(session)
        LOGGER.info(f"Added environment to session {session_id}: {name}")

        return env

    def _save_session(self, session: PlanGeneratorSession) -> None:
        """Save session to disk."""
        if not self._storage_dir:
            return

        path = self._storage_dir / f"{session.session_id}.json"
        with open(path, "w") as f:
            f.write(session.model_dump_json(indent=2))

    def _load_session(self, session_id: str) -> Optional[PlanGeneratorSession]:
        """Load session from disk."""
        if not self._storage_dir:
            return None

        path = self._storage_dir / f"{session_id}.json"
        if not path.exists():
            return None

        try:
            with open(path, "r") as f:
                data = json.load(f)
            return PlanGeneratorSession(**data)
        except Exception as e:
            LOGGER.error(f"Error loading session {session_id}: {e}")
            return None


# Global session manager instance
_session_manager: Optional[SessionManager] = None

# Default storage directory for sessions (persists across server restarts)
_DEFAULT_STORAGE_DIR = Path(__file__).parent.parent.parent.parent / "data" / "mp_plan_sessions"


def get_session_manager() -> SessionManager:
    """Get the global session manager instance with persistent storage."""
    global _session_manager
    if _session_manager is None:
        # Use persistent storage so sessions survive server restarts
        _session_manager = SessionManager(storage_dir=_DEFAULT_STORAGE_DIR)
        LOGGER.info(f"Session manager initialized with storage: {_DEFAULT_STORAGE_DIR}")
    return _session_manager
