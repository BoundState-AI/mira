#!/usr/bin/env python3
"""
Module: M&P Plan CLI
Purpose: Command-line interface for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Provides command-line access to M&P Plan Generator capabilities:
- Session creation and management
- Material and environment entry
- Compute loop execution
- Artifact generation

Usage:
    python -m mira.mp_plan.cli create --program "HLS" --vehicle ORION
    python -m mira.mp_plan.cli add-material <session_id> --name "Kapton" --app "Wire insulation"
    python -m mira.mp_plan.cli compute <session_id>
    python -m mira.mp_plan.cli generate <session_id> --output ./output/

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

__version__ = "2.0.0"
__safety_critical__ = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
LOGGER = logging.getLogger("mp_plan.cli")


def get_session_manager():
    """Get the session manager instance."""
    from mira.mp_plan.session_manager import get_session_manager
    return get_session_manager()


def cmd_create(args: argparse.Namespace) -> int:
    """Create a new session."""
    manager = get_session_manager()

    session = manager.create_session(
        program_name=args.program,
        program_phase=args.phase,
        vehicle_preset=args.vehicle,
    )

    print(f"Created session: {session.session_id}")
    print(f"  Program: {session.program_name or 'Not specified'}")
    print(f"  Phase: {session.program_phase or 'Not specified'}")
    print(f"  Environments: {len(session.environments)}")

    if args.vehicle:
        print(f"  Vehicle preset applied: {args.vehicle}")

    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List all sessions."""
    manager = get_session_manager()
    summaries = manager.list_sessions()

    if not summaries:
        print("No sessions found.")
        return 0

    print(f"Found {len(summaries)} session(s):\n")
    for s in summaries:
        status = "READY" if s["can_generate"] else "BLOCKED"
        print(f"  {s['session_id']} - {s['program_name'] or 'Unnamed'}")
        print(f"    Materials: {s['material_count']}, Environments: {s['environment_count']}")
        print(f"    Nonconformances: {s['nonconformance_count']}, Status: {status}")
        if s["blockers"]:
            print(f"    Blockers: {', '.join(s['blockers'][:3])}")
        print()

    return 0


def cmd_show(args: argparse.Namespace) -> int:
    """Show session details."""
    manager = get_session_manager()
    session = manager.get_session(args.session_id)

    if not session:
        print(f"Session not found: {args.session_id}", file=sys.stderr)
        return 1

    can_generate, blockers = session.can_generate()

    print(f"Session: {session.session_id}")
    print(f"  Program: {session.program_name or 'Not specified'}")
    print(f"  Phase: {session.program_phase or 'Not specified'}")
    print(f"  Created: {session.created_at.isoformat()}")
    print(f"  Updated: {session.updated_at.isoformat()}")
    print()

    print("Environments:")
    for env in session.environments:
        print(f"  - {env.name}: O2={env.o2_pct}%, {env.pressure_psia} psia")

    print()
    print("Materials:")
    for mat in session.materials:
        print(f"  - {mat.name} ({mat.application})")
        if mat.maptis_code:
            print(f"    MAPTIS: {mat.maptis_code}")

    print()
    print(f"Deficiencies: {len(session.deficiencies)}")
    print(f"Nonconformances: {len(session.nonconformances)}")
    print(f"Closures: {len(session.closure_decisions)}")
    print(f"Accepted Open: {len(session.accepted_open_gaps)}")

    print()
    print(f"Can Generate: {'Yes' if can_generate else 'No'}")
    if blockers:
        print("Blockers:")
        for b in blockers:
            print(f"  - {b}")

    return 0


def cmd_add_environment(args: argparse.Namespace) -> int:
    """Add an environment to a session."""
    manager = get_session_manager()

    env = manager.add_environment(
        session_id=args.session_id,
        name=args.name,
        o2_pct=args.o2,
        pressure_psia=args.pressure,
        temp_range_c=(args.temp_min, args.temp_max),
        habitable=args.habitable,
        vacuum_exposure=args.vacuum,
        lunar_dust=args.lunar_dust,
    )

    if not env:
        print(f"Session not found: {args.session_id}", file=sys.stderr)
        return 1

    print(f"Added environment: {env.name}")
    print(f"  O2: {env.o2_pct}%")
    print(f"  Pressure: {env.pressure_psia} psia")
    print(f"  Temperature: {env.temp_range_c[0]}°C to {env.temp_range_c[1]}°C")

    return 0


def cmd_add_material(args: argparse.Namespace) -> int:
    """Add a material to a session."""
    manager = get_session_manager()

    material = manager.add_material(
        session_id=args.session_id,
        name=args.name,
        application=args.application,
        quantity=args.quantity,
        maptis_code=args.maptis,
        mass_g=args.mass,
        surface_area_cm2=args.area,
    )

    if not material:
        print(f"Session not found: {args.session_id}", file=sys.stderr)
        return 1

    print(f"Added material: {material.name}")
    print(f"  Application: {material.application}")
    print(f"  ID: {material.id}")
    if material.maptis_code:
        print(f"  MAPTIS: {material.maptis_code}")

    return 0


def cmd_compute(args: argparse.Namespace) -> int:
    """Run compute loop."""
    from mira.mp_plan.compute_loop import run_compute_loop

    manager = get_session_manager()
    session = manager.get_session(args.session_id)

    if not session:
        print(f"Session not found: {args.session_id}", file=sys.stderr)
        return 1

    print(f"Running compute loop for session {args.session_id}...")

    session = run_compute_loop(session, max_iterations=args.iterations)
    manager.update_session(session)

    can_generate, blockers = session.can_generate()

    print()
    print("Compute Results:")
    print(f"  Deficiencies: {len(session.deficiencies)}")
    print(f"  Nonconformances: {len(session.nonconformances)}")
    print(f"  Blocking Questions: {len(session.blocking_questions)}")

    if session.blocking_questions:
        print()
        print("Blocking Questions:")
        for q in session.blocking_questions[:5]:
            print(f"  - [{q.question_type}] {q.question_text[:60]}...")

    print()
    print(f"Can Generate: {'Yes' if can_generate else 'No'}")
    if blockers:
        print("Blockers:")
        for b in blockers[:5]:
            print(f"  - {b}")

    return 0


def cmd_closure_options(args: argparse.Namespace) -> int:
    """Show closure options for a gap."""
    from mira.mp_plan.gap_resolution import check_all_paths

    manager = get_session_manager()
    session = manager.get_session(args.session_id)

    if not session:
        print(f"Session not found: {args.session_id}", file=sys.stderr)
        return 1

    # Find the gap
    gap = next(
        (n for n in session.nonconformances if n.nonconformance_id.startswith(args.gap_id)),
        None,
    )
    if not gap:
        print(f"Gap not found: {args.gap_id}", file=sys.stderr)
        return 1

    # Find material and environment
    material = next((m for m in session.materials if m.id == gap.material_id), None)
    environment = next((e for e in session.environments if e.environment_id == gap.environment_id), None)

    if not material or not environment:
        print("Could not find material or environment for gap", file=sys.stderr)
        return 1

    print(f"Closure Options for Gap: {gap.nonconformance_id[:12]}")
    print(f"  Material: {material.name}")
    print(f"  Environment: {environment.name}")
    print(f"  Gap Type: {gap.gap_type.value if hasattr(gap.gap_type, 'value') else gap.gap_type}")
    print()

    results = check_all_paths(gap, material, environment, session)

    for result in results:
        status = "ELIGIBLE" if result.eligible else "NOT ELIGIBLE"
        conf = f"({result.confidence:.0%} confidence)"
        print(f"  [{status}] {result.path_title} {conf}")
        print(f"    Citation: {result.citation}")
        print(f"    {result.rationale[:80]}...")
        print()

    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    """Generate artifacts."""
    from mira.mp_plan.generation import (
        generate_mp_plan_docx,
        generate_miul_xlsx,
        generate_review_packet,
        generate_applicability_matrix_xlsx,
        generate_gap_register_xlsx,
        generate_manifest_json,
    )

    manager = get_session_manager()
    session = manager.get_session(args.session_id)

    if not session:
        print(f"Session not found: {args.session_id}", file=sys.stderr)
        return 1

    can_generate, blockers = session.can_generate()
    if not can_generate and not args.force:
        print("Cannot generate - session has blockers:", file=sys.stderr)
        for b in blockers:
            print(f"  - {b}", file=sys.stderr)
        print("\nUse --force to generate anyway.", file=sys.stderr)
        return 1

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts_generated = []

    if "all" in args.artifacts or "mp_plan" in args.artifacts:
        content = generate_mp_plan_docx(session)
        path = output_dir / f"mp_plan_{session.session_id[:8]}.docx"
        path.write_bytes(content)
        artifacts_generated.append(("M&P Plan", path))

    if "all" in args.artifacts or "miul" in args.artifacts:
        content = generate_miul_xlsx(session)
        path = output_dir / f"miul_{session.session_id[:8]}.xlsx"
        path.write_bytes(content)
        artifacts_generated.append(("MIUL", path))

    if "all" in args.artifacts or "matrix" in args.artifacts:
        content = generate_applicability_matrix_xlsx(session)
        path = output_dir / f"applicability_matrix_{session.session_id[:8]}.xlsx"
        path.write_bytes(content)
        artifacts_generated.append(("Applicability Matrix", path))

    if "all" in args.artifacts or "gaps" in args.artifacts:
        content = generate_gap_register_xlsx(session)
        path = output_dir / f"gap_register_{session.session_id[:8]}.xlsx"
        path.write_bytes(content)
        artifacts_generated.append(("Gap Register", path))

    if "all" in args.artifacts or "manifest" in args.artifacts:
        content = generate_manifest_json(session)
        path = output_dir / f"manifest_{session.session_id[:8]}.json"
        path.write_bytes(content)
        artifacts_generated.append(("Manifest", path))

    if "all" in args.artifacts or "review" in args.artifacts:
        packet = generate_review_packet(session)
        content = packet.model_dump_json(indent=2).encode()
        path = output_dir / f"review_packet_{session.session_id[:8]}.json"
        path.write_bytes(content)
        artifacts_generated.append(("Review Packet", path))

    print(f"Generated {len(artifacts_generated)} artifact(s):")
    for name, path in artifacts_generated:
        print(f"  - {name}: {path}")

    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    """Delete a session."""
    manager = get_session_manager()

    if manager.delete_session(args.session_id):
        print(f"Deleted session: {args.session_id}")
        return 0
    else:
        print(f"Session not found: {args.session_id}", file=sys.stderr)
        return 1


def cmd_paths(args: argparse.Namespace) -> int:
    """List available closure paths."""
    from mira.mp_plan.gap_resolution import CLOSURE_PATH_REGISTRY

    print("Available Closure Paths:\n")

    for path_id, path_class in CLOSURE_PATH_REGISTRY.items():
        instance = path_class()
        print(f"  {path_id}")
        print(f"    Title: {instance.path_title}")
        print(f"    Citation: {instance.citation}")
        print(f"    Description: {instance.path_description}")
        print(f"    Required Inputs: {', '.join(instance.required_inputs)}")
        print()

    return 0


def cmd_presets(args: argparse.Namespace) -> int:
    """List available vehicle presets."""
    from mira.mp_plan.policy import create_default_policy_pack

    policy = create_default_policy_pack()

    print("Available Vehicle Presets:\n")

    for name, config in policy.vehicle_environments.items():
        print(f"  {name}")
        print(f"    Name: {config.get('name', name)}")
        print(f"    O2: {config.get('o2_pct')}%")
        print(f"    Pressure: {config.get('pressure_psia')} psia")
        print(f"    Habitable: {config.get('habitable', False)}")
        print()

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        prog="mp-plan",
        description="M&P Plan Generator V2 - Command Line Interface",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # create command
    create_parser = subparsers.add_parser("create", help="Create a new session")
    create_parser.add_argument("--program", "-p", help="Program name")
    create_parser.add_argument("--phase", help="Program phase")
    create_parser.add_argument("--vehicle", "-v", help="Vehicle preset (e.g., ORION, ISS, GATEWAY)")

    # list command
    subparsers.add_parser("list", help="List all sessions")

    # show command
    show_parser = subparsers.add_parser("show", help="Show session details")
    show_parser.add_argument("session_id", help="Session ID")

    # add-environment command
    env_parser = subparsers.add_parser("add-environment", help="Add an environment")
    env_parser.add_argument("session_id", help="Session ID")
    env_parser.add_argument("--name", "-n", required=True, help="Environment name")
    env_parser.add_argument("--o2", type=float, required=True, help="O2 percentage")
    env_parser.add_argument("--pressure", type=float, required=True, help="Pressure in psia")
    env_parser.add_argument("--temp-min", type=float, default=18.0, help="Min temperature (°C)")
    env_parser.add_argument("--temp-max", type=float, default=27.0, help="Max temperature (°C)")
    env_parser.add_argument("--habitable", action="store_true", help="Habitable environment")
    env_parser.add_argument("--vacuum", action="store_true", help="Vacuum exposure")
    env_parser.add_argument("--lunar-dust", action="store_true", help="Lunar dust exposure")

    # add-material command
    mat_parser = subparsers.add_parser("add-material", help="Add a material")
    mat_parser.add_argument("session_id", help="Session ID")
    mat_parser.add_argument("--name", "-n", required=True, help="Material name")
    mat_parser.add_argument("--application", "-a", required=True, help="Application")
    mat_parser.add_argument("--quantity", "-q", type=int, default=1, help="Quantity")
    mat_parser.add_argument("--maptis", help="MAPTIS code")
    mat_parser.add_argument("--mass", type=float, help="Mass in grams")
    mat_parser.add_argument("--area", type=float, help="Surface area in cm²")

    # compute command
    compute_parser = subparsers.add_parser("compute", help="Run compute loop")
    compute_parser.add_argument("session_id", help="Session ID")
    compute_parser.add_argument("--iterations", "-i", type=int, default=1, help="Max iterations")

    # closure-options command
    closure_parser = subparsers.add_parser("closure-options", help="Show closure options for a gap")
    closure_parser.add_argument("session_id", help="Session ID")
    closure_parser.add_argument("gap_id", help="Gap ID (or prefix)")

    # generate command
    gen_parser = subparsers.add_parser("generate", help="Generate artifacts")
    gen_parser.add_argument("session_id", help="Session ID")
    gen_parser.add_argument("--output", "-o", default="./output", help="Output directory")
    gen_parser.add_argument(
        "--artifacts",
        nargs="+",
        default=["all"],
        choices=["all", "mp_plan", "miul", "matrix", "gaps", "manifest", "review"],
        help="Artifacts to generate",
    )
    gen_parser.add_argument("--force", "-f", action="store_true", help="Generate even with blockers")

    # delete command
    delete_parser = subparsers.add_parser("delete", help="Delete a session")
    delete_parser.add_argument("session_id", help="Session ID")

    # paths command
    subparsers.add_parser("paths", help="List available closure paths")

    # presets command
    subparsers.add_parser("presets", help="List available vehicle presets")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "create": cmd_create,
        "list": cmd_list,
        "show": cmd_show,
        "add-environment": cmd_add_environment,
        "add-material": cmd_add_material,
        "compute": cmd_compute,
        "closure-options": cmd_closure_options,
        "generate": cmd_generate,
        "delete": cmd_delete,
        "paths": cmd_paths,
        "presets": cmd_presets,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
