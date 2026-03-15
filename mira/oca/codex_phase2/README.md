# MIRA OCA Phase 2 Data Pack Scaffold

This directory contains the initial production scaffold for **BS-SPEC-OCA-002-REV0 (Phase 2: Visual System Builder)**.

## Included artifacts

- `oca_component_library.json` — component archetypes, default properties, and default feature susceptibility.
- `oca_component_features.json` — normalized feature flags and derived rules.
- `oca_topology_inference_rules.json` — directed-graph inference and staged recompute rules.
- `oca_mechanism_trace_rules.json` — mechanism mappings with required characteristic elements and control levers.
- `oca_system_rules.json` — interaction logic, blocked-state policy, and API extension contract.
- `oca_velocity_thresholds.json` — velocity formulae, units, and PI threshold binding.

## Notes

- Rules are encoded as **assumption-driven conditional logic**, not absolutes.
- Tier boundaries are explicit where Tier A requirement boundaries are defined.
- These artifacts are intended to be consumed by the OCA engine/UI implementation layer.
