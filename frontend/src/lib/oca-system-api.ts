/**
 * OCA System Builder API Client (Phase 2)
 * Per BS-SPEC-OCA-002-REV0 §14
 *
 * BoundState AI 2026
 * Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
 */

const API_BASE = import.meta.env.VITE_API_URL || '/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ComponentArchetype =
  | 'valve' | 'regulator' | 'line' | 'filter' | 'fitting'
  | 'pressure_vessel' | 'relief_valve' | 'check_valve' | 'orifice'
  | 'heat_exchanger' | 'gasket' | 'flex_hose';

export type SystemZoneType =
  | 'unfiltered' | 'filtered' | 'dead_leg' | 'dynamic'
  | 'cavity_resonance' | 'acceptance_test';

export type InferenceSource = 'user_entered' | 'inferred' | 'calculated' | 'imported';
export type InferenceConfidence = 'high' | 'medium' | 'low';
export type SeatContactMode = 'metal_to_metal' | 'metal_to_polymer' | 'polymer_to_polymer';
export type SAVolumeRatio = 'high' | 'med' | 'low';

export interface ComponentFeatureFlags {
  has_moving_contact: boolean;
  has_polymer_seal: boolean;
  has_dead_volume: boolean;
  creates_particles: boolean;
  has_cavity_downstream: boolean;
  wetted_surface_flag: boolean;
  porous_media_flag: boolean;
  electrical_energy_present: boolean;
  dynamic_contact_flag: boolean;
  contamination_trap_flag: boolean;
  filter_integrity_assumed: boolean;
  metal_pair_contact: boolean;
  reactive_metal_present: boolean;
  seat_contact_mode: SeatContactMode | null;
  sa_to_volume_ratio: SAVolumeRatio;
}

export interface InferredFact {
  fact_id: string;
  fact_name: string;
  value: unknown;
  source: InferenceSource;
  confidence: InferenceConfidence;
  rule_id: string;
  missing_assumptions: string[];
  explanation: string;
}

export interface MaterialSlotValue {
  slot_name: string;
  material: {
    material_name: string;
    spec?: string | null;
    identity_confidence?: number;
    flammability_rating?: string;
    is_titanium?: boolean;
    is_nonmetal?: boolean;
  };
}

export interface ComponentConfig {
  valve_type?: string | null;
  actuation_type?: string | null;
  opening_profile?: string | null;
  regulator_type?: string | null;
  chatter_susceptible?: boolean | null;
  soft_seat_creep_flag?: boolean | null;
  wall_thickness_mm?: number | null;
  inner_diameter_mm?: number | null;
  length_m?: number | null;
  is_flex?: boolean | null;
  micron_rating?: number | null;
  element_type?: string | null;
  bypass_path_exists?: boolean | null;
  seal_type?: string | null;
  connection_type?: string | null;
  volume_liters?: number | null;
  mawp_psia?: number | null;
  set_pressure_psia?: number | null;
  bore_diameter_mm?: number | null;
  exposed_to_flow?: boolean | null;
}

export interface MechanismAssessment {
  mechanism_name: string;
  credible_status: 'credible' | 'not_credible' | 'indeterminate';
  rating: number;
  source_ref: string;
  observed_elements: string[];
  missing_elements: string[];
  required_elements: string[];
  reviewer_comments: string[];
}

export interface SystemComponent {
  component_id: string;
  archetype: ComponentArchetype;
  label: string;
  position_x: number;
  position_y: number;
  materials: MaterialSlotValue[];
  config: ComponentConfig;
  features: ComponentFeatureFlags;
  inferred_facts: InferredFact[];
  zones: SystemZoneType[];
  mechanism_assessments: MechanismAssessment[];
  overall_status: 'green' | 'yellow' | 'red' | 'pending';
  highest_rating: number;
  credible_mechanisms: string[];
  connected: boolean;
  is_provisional?: boolean;
  human_confirmed?: boolean;
  is_rigid_metallic_tubing?: boolean;
  is_metallic_flex_hose?: boolean;
  is_all_metal_seal?: boolean;
  is_metallic_pressure_vessel?: boolean;
}

export interface SystemConnection {
  connection_id: string;
  source_component_id: string;
  source_port: string;
  target_component_id: string;
  target_port: string;
}

export interface SystemInputs {
  o2_fraction: number;
  system_pressure_min_psia: number;
  system_pressure_max_psia: number;
  phase: string;
  oxygen_phase: string;
  temp_min_c?: number | null;
  temp_max_c?: number | null;
  design_flow_rate_m3_s?: number | null;
  cleanliness_spec?: string | null;
  mission_phase: string;
  project_name: string;
  hardware_name: string;
  reviewer_name: string;
  bi_directional_flow_risk: boolean;
}

export interface SystemKindlingChain {
  chain_id: string;
  propagation_path: string[];
  materials_in_path: string[];
  chain_broken_at: string | null;
  break_reason: string | null;
  longest_continuous_length: number;
  reaction_effect: string;
}

export interface PathInspectorResult {
  component_id: string;
  upstream_contributors: { component_id: string; label: string; contributions: string }[];
  local_mechanism_triggers: { mechanism: string; abbreviation: string; status: string; rating: string; observed_elements: string }[];
  downstream_propagation_risk: string[];
  controls_that_would_change: { action: string; expected_effect: string; mechanism: string }[];
}

export interface SystemAssessmentResult {
  system_id: string;
  system_disposition: string;
  system_reaction_effect: string;
  components: SystemComponent[];
  kindling_chains: SystemKindlingChain[];
  triggered_requirements: { requirement_id: string; title: string; tier: string; satisfied: boolean; is_prohibition: boolean; prohibition_detail?: string }[];
  blocked_states: { state_type: string; description: string; missing_fields: string[]; resolution_hint: string }[];
  hazard_controls: { component_ref: string; ignition_hazard: string; probability_rating: number; recommendation: string; confidence: string }[];
  has_titanium: boolean;
  mpr67_active: boolean;
}

export interface ComponentUpdateRequest {
  label?: string;
  materials?: MaterialSlotValue[];
  config?: Partial<ComponentConfig>;
  inferred_facts?: InferredFact[];
  is_provisional?: boolean;
  human_confirmed?: boolean;
  is_rigid_metallic_tubing?: boolean;
  is_metallic_flex_hose?: boolean;
  is_all_metal_seal?: boolean;
  is_metallic_pressure_vessel?: boolean;
}

export interface VisionMockupQuestion {
  question_id: string;
  severity: 'blocking' | 'review';
  prompt: string;
  target_temp_id?: string | null;
  field_path?: string | null;
}

export interface VisionMockupComponent {
  temp_id: string;
  archetype: ComponentArchetype;
  label: string;
  position_x: number;
  position_y: number;
  materials: MaterialSlotValue[];
  config: ComponentConfig;
  is_provisional: boolean;
  human_confirmed: boolean;
  inferred_facts: InferredFact[];
  confidence: InferenceConfidence;
}

export interface VisionMockupConnection {
  source_temp_id: string;
  source_port: string;
  target_temp_id: string;
  target_port: string;
  label?: string | null;
  confidence: InferenceConfidence;
}

export interface VisionMockupResult {
  system_id: string;
  model_used: string;
  suggested_inputs_patch: Partial<SystemInputs>;
  components: VisionMockupComponent[];
  connections: VisionMockupConnection[];
  questions: VisionMockupQuestion[];
  warnings: string[];
}

// Component library archetype definition
export interface ArchetypeDefinition {
  archetype_id: string;
  display_name: string;
  description: string;
  material_slots: { slot: string; required: boolean; default: unknown }[];
  config_fields: { field: string; type: string; options?: string[]; default: unknown }[];
  default_features: Record<string, unknown>;
  ports: { input: number; output: number };
  icon: string;
}

// ---------------------------------------------------------------------------
// API Functions
// ---------------------------------------------------------------------------

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Request failed: ${response.statusText}`);
  }
  return response.json();
}

export async function ocaSystemsPing(): Promise<{ status: string }> {
  return fetchJSON(`${API_BASE}/oca/systems/ping`);
}

export async function ocaCreateSystem(name: string, inputs: Partial<SystemInputs> = {}): Promise<{ system_id: string; name: string }> {
  return fetchJSON(`${API_BASE}/oca/systems`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, inputs }),
  });
}

export async function ocaGetSystem(systemId: string): Promise<Record<string, unknown>> {
  return fetchJSON(`${API_BASE}/oca/systems/${systemId}`);
}

export async function ocaDeleteSystem(systemId: string): Promise<{ status: string }> {
  return fetchJSON(`${API_BASE}/oca/systems/${systemId}`, { method: 'DELETE' });
}

export async function ocaUpdateInputs(systemId: string, inputs: Partial<SystemInputs>): Promise<{ status: string }> {
  return fetchJSON(`${API_BASE}/oca/systems/${systemId}/inputs`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(inputs),
  });
}

export async function ocaAddComponent(
  systemId: string,
  archetype: ComponentArchetype,
  label: string,
  positionX: number,
  positionY: number,
  materials: MaterialSlotValue[] = [],
  config: Partial<ComponentConfig> = {},
): Promise<{ component_id: string; features: ComponentFeatureFlags; zones: SystemZoneType[]; inferred_facts: InferredFact[] }> {
  return fetchJSON(`${API_BASE}/oca/systems/${systemId}/components`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ archetype, label, position_x: positionX, position_y: positionY, materials, config }),
  });
}

export async function ocaRemoveComponent(systemId: string, componentId: string): Promise<{ status: string }> {
  return fetchJSON(`${API_BASE}/oca/systems/${systemId}/components/${componentId}`, { method: 'DELETE' });
}

export async function ocaUpdateComponent(
  systemId: string,
  componentId: string,
  updates: ComponentUpdateRequest,
): Promise<{ status: string; component?: SystemComponent }> {
  return fetchJSON(`${API_BASE}/oca/systems/${systemId}/components/${componentId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
}

export async function ocaAddConnection(
  systemId: string,
  sourceId: string,
  targetId: string,
): Promise<{ connection_id: string; affected_component_ids: string[] }> {
  return fetchJSON(`${API_BASE}/oca/systems/${systemId}/connections`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_component_id: sourceId, target_component_id: targetId }),
  });
}

export async function ocaRemoveConnection(systemId: string, connectionId: string): Promise<{ status: string }> {
  return fetchJSON(`${API_BASE}/oca/systems/${systemId}/connections/${connectionId}`, { method: 'DELETE' });
}

export async function ocaAssessSystem(systemId: string): Promise<SystemAssessmentResult> {
  return fetchJSON(`${API_BASE}/oca/systems/${systemId}/assess`, { method: 'POST' });
}

export async function ocaGetTopology(systemId: string): Promise<Record<string, unknown>> {
  return fetchJSON(`${API_BASE}/oca/systems/${systemId}/topology`);
}

export async function ocaGetKindlingChain(systemId: string): Promise<{ chains: SystemKindlingChain[]; worst_case_effect: string }> {
  return fetchJSON(`${API_BASE}/oca/systems/${systemId}/kindling-chain`);
}

export async function ocaGetPathInspector(systemId: string, componentId: string): Promise<PathInspectorResult> {
  return fetchJSON(`${API_BASE}/oca/systems/${systemId}/path/${componentId}`);
}

export async function ocaExportSystem(systemId: string): Promise<Record<string, unknown>> {
  return fetchJSON(`${API_BASE}/oca/systems/${systemId}/export`, { method: 'POST' });
}

export async function ocaGetComponentLibrary(systemId: string): Promise<{ archetypes: ArchetypeDefinition[] }> {
  return fetchJSON(`${API_BASE}/oca/systems/${systemId}/library`);
}

export async function ocaVisionMockup(
  systemId: string,
  payload: {
    image: File;
    flowDirectionHint?: string;
    notes?: string;
  },
): Promise<VisionMockupResult> {
  const formData = new FormData();
  formData.append('image', payload.image);
  formData.append('flow_direction_hint', payload.flowDirectionHint ?? 'unknown');
  formData.append('notes', payload.notes ?? '');

  return fetchJSON(`${API_BASE}/oca/systems/${systemId}/vision/mockup`, {
    method: 'POST',
    body: formData,
  });
}

// Mechanism abbreviation display map
export const MECHANISM_ABBREV: Record<string, string> = {
  particle_impact: 'PI',
  rapid_pressurization: 'RP',
  flow_friction: 'FF',
  resonance: 'RS',
  mechanical_impact: 'MI',
  galling_friction: 'GF',
  fresh_metal_exposure: 'FM',
  static_discharge: 'SD',
  electrical_arc: 'EA',
  chemical_reaction: 'CR',
  thermal_runaway: 'TR',
  other: 'OT',
};

// Zone display colors
export const ZONE_COLORS: Record<SystemZoneType, string> = {
  unfiltered: '#ef4444',
  filtered: '#22c55e',
  dead_leg: '#f97316',
  dynamic: '#a855f7',
  cavity_resonance: '#ec4899',
  acceptance_test: '#3b82f6',
};

export const ZONE_LABELS: Record<SystemZoneType, string> = {
  unfiltered: 'Unfiltered Zone',
  filtered: 'Filtered Zone',
  dead_leg: 'Dead-Leg Zone',
  dynamic: 'Dynamic Component Zone',
  cavity_resonance: 'Cavity / Resonance Zone',
  acceptance_test: 'Acceptance-Test Zone',
};
