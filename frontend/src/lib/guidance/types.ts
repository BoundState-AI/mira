/**
 * BS-SPEC-GUIDANCE-001-REV2.1 — Universal Guidance Schema Type Definitions
 *
 * This file defines the complete type system for the three-layer guidance
 * architecture: Schema (content), Renderer (presentation), Mode (behavior).
 *
 * All types here map 1:1 to the specification. Section numbers reference
 * BS-SPEC-GUIDANCE-001-REV2.1.
 */

// ---------------------------------------------------------------------------
// Section 3.7.2 — Applicability Conditions
// ---------------------------------------------------------------------------

/**
 * Flat key-value AND conditions. All conditions must be true for the element
 * to be active. `null` means always active.
 *
 * Keys are dot-paths into the context object (e.g., "context.service_environment").
 * Values are either a single string (equality) or string[] (set membership).
 *
 * Per Section 3.7.3: if a condition cannot be expressed as flat key-value AND,
 * escalate to a policy_hook or rule_engine_hook. Do NOT invent ad hoc grammar.
 */
export type AppliesWhen = Record<string, string | string[]> | null;

// ---------------------------------------------------------------------------
// Section 3.5 — Authority Model
// ---------------------------------------------------------------------------

/** Section 3.5.2 — Authority source types */
export type AuthoritySourceType =
  | 'official_pdf'
  | 'internal_controlled_copy'
  | 'external_reference'
  | 'derived_summary';

/** Section 3.5.4 — Authority types */
export type AuthorityType =
  | 'requirement'
  | 'guidance'
  | 'best_practice'
  | 'local_policy';

/** Section 3.5.1 — Authority Registry Entry */
export interface AuthorityRegistryEntry {
  authority_id: string;
  document_id: string;
  revision: string;
  section: string;
  requirement_id: string | null;
  requirement_type: 'shall' | 'should' | 'may' | null;
  verbatim_excerpt: string | null;
  boundstate_summary: string;
  interpretation: string | null;
  source_type: AuthoritySourceType;
  source_url: string | null;
  internal_doc_handle: string | null;
  page_ref: string | null;
  document_hash: string | null;
  verification_method: 'manual_review' | 'automated_hash' | null;
  last_verified: string;
  status: 'active' | 'superseded' | 'withdrawn';
  legal_disclaimer: string;
}

/** Section 3.5.3 — Authority Reference in Field Schema */
export interface AuthorityRef {
  authority_ref: string;
  type: AuthorityType;
  relationship: 'primary' | 'supplementary' | 'overlay';
  applies_when: AppliesWhen;
  presentation_order?: number;
  overlay_note?: string;
}

// ---------------------------------------------------------------------------
// Section 3.6 — Validation Model
// ---------------------------------------------------------------------------

/** Section 3.6.1 — Validation severity levels */
export type ValidationSeverity = 'error' | 'warning' | 'info';

/** Section 3.6.2 — Warning/display severity (separate vocabulary) */
export type WarningSeverity = 'caution' | 'info';

export interface ValidationRule {
  type: 'string' | 'number' | 'boolean' | 'enum' | 'date';
  severity: ValidationSeverity;
  required: boolean;
  pattern?: string;
  min_length?: number;
  max_length?: number;
  min?: number;
  max?: number;
  unit?: string;
  unit_alternatives?: string[];
  auto_convert?: boolean;
  precision?: number;
  enum_values?: string[];
}

// ---------------------------------------------------------------------------
// Section 3.8 — Heritage Model
// ---------------------------------------------------------------------------

export interface HeritageModel {
  auto_extracted_from: string | null;
  extraction_method: string | null;
  extraction_confidence: number | null;
  extraction_timestamp?: string | null;
  user_confirmed: boolean;
  display_when_present: string;
}

// ---------------------------------------------------------------------------
// Section 3.9 — Escalation Model
// ---------------------------------------------------------------------------

export type EscalationActionType =
  | 'flag_for_review'
  | 'display_block_reason'
  | 'suggest_alternative'
  | 'link_to_resource';

export interface EscalationAction {
  action_type: EscalationActionType;
  target_role?: string;
  message_template: string;
  target_url?: string;
  available_when?: AppliesWhen;
}

export interface EscalationModel {
  type: 'recommendation';
  on_unresolved_warning?: EscalationAction;
  on_validation_failure?: EscalationAction;
}

// ---------------------------------------------------------------------------
// Warnings and Actions
// ---------------------------------------------------------------------------

export type WarningSourceType = 'heuristic' | 'system' | 'engine';

export interface GuidanceWarning {
  condition_ref: string;
  severity: WarningSeverity;
  message: string;
  source_type: WarningSourceType;
}

export type GuidanceActionType = 'lookup' | 'navigate' | 'link' | 'run';

export interface GuidanceAction {
  action: GuidanceActionType;
  target: string;
  prompt: string;
  available_when: AppliesWhen;
}

// ---------------------------------------------------------------------------
// Lookup Assist
// ---------------------------------------------------------------------------

export interface LookupAssist {
  source: string;
  fuzzy_match: boolean;
  fuzzy_threshold?: number;
  user_must_confirm: boolean;
}

// ---------------------------------------------------------------------------
// Section 4.4 — Policy Hooks (read-only reference to engine state)
// ---------------------------------------------------------------------------

export interface PolicyHook {
  hook_ref: string;
  description: string;
  source_engine: string;
  display_as: 'warning' | 'info' | 'blocker';
  severity: WarningSeverity;
  message_template: string;
  engine_blocking_state_ref: string;
  display_when_blocked: string;
}

// ---------------------------------------------------------------------------
// Section 4.5 — Rule Engine Hooks
// ---------------------------------------------------------------------------

export interface RuleEngineHook {
  rule_ref: string;
  version: string;
  input_contract: string[];
  output_contract: Record<string, string>;
  registry: string;
  display_result_as: 'validation_indicator' | 'warning' | 'info';
  on_fail_message: string;
}

// ---------------------------------------------------------------------------
// Section 3.7.2 — Applicability
// ---------------------------------------------------------------------------

export interface FieldApplicability {
  visible_when: AppliesWhen;
  required_when: AppliesWhen;
  enhanced_when: AppliesWhen;
}

// ---------------------------------------------------------------------------
// Section 3.3/3.4 — Field Definition
// ---------------------------------------------------------------------------

export interface GuidanceFieldDefinition {
  label: string;
  what: string;
  why: string;
  how?: string;
  common_errors?: string[];
  examples?: string[];
  authorities?: AuthorityRef[];
  applicability?: FieldApplicability;
  validation: ValidationRule;
  lookup_assist?: LookupAssist;
  heritage?: HeritageModel;
  actions?: GuidanceAction[];
  warnings?: GuidanceWarning[];
  escalation?: EscalationModel;
  related_fields?: string[];
  tags?: string[];
  policy_hooks?: PolicyHook[];
  rule_engine_hooks?: RuleEngineHook[];
}

// ---------------------------------------------------------------------------
// Section 7 — Workflow Model
// ---------------------------------------------------------------------------

export interface WorkflowCompletionCondition {
  all_required_fields_valid?: boolean;
  at_least_one_gap_documented?: boolean;
  [key: string]: boolean | undefined;
}

export interface WorkflowStep {
  step_id: string;
  title: string;
  description: string;
  fields: string[];
  prerequisites: string[];
  completion_conditions: WorkflowCompletionCondition;
  guidance_on_entry: string;
  next_best_action: string;
  missing_evidence?: {
    check: string;
    if_present: string;
    if_absent: string;
  };
  document_checklist?: Array<{
    doc: string;
    required: boolean;
    apostille?: boolean;
  }>;
  generation?: number;
  side?: 'paternal' | 'maternal';
}

export interface WorkflowDefinition {
  workflow_id: string;
  type?: 'sequential' | 'tree_traversal';
  steps: WorkflowStep[];
  tree_rules?: {
    max_generations: number;
    stop_when: string;
    guidance_at_terminus: string;
  };
}

// ---------------------------------------------------------------------------
// Section 3.7.1 — Context Object
// ---------------------------------------------------------------------------

export interface UpstreamVerdict {
  verdict: string;
  mitigations?: number;
  material?: string;
  environment?: string;
  gaps?: string[];
}

export interface GuidanceContext {
  platform: 'mira' | 'aegis' | 'sentinel' | 'sentinel_citz' | 'forge';
  module: string;
  center?: string;
  program?: string;
  mission_type?: 'crewed' | 'uncrewed' | 'cargo';
  hardware_class?: 'human_rated' | 'robotic' | 'ground_support';
  service_environment?: string;
  pressure_regime?: 'low' | 'medium' | 'high';
  material_class?: 'metallic' | 'nonmetallic' | 'composite';
  upstream_verdicts?: Record<string, UpstreamVerdict | null>;
  user_mode: GuidanceModeName;
  locale: string;
}

// ---------------------------------------------------------------------------
// Section 6 — GuidanceMode
// ---------------------------------------------------------------------------

export type GuidanceModeName = 'training' | 'live' | 'expert';

/** Section 6.1 — Module mode overrides for expert minimum severity */
export interface ModuleModeOverride {
  expert_mode_minimum_severity: WarningSeverity;
  rationale: string;
}

/** Section 6.2 — Mode promotion/demotion rules */
export interface ModeTransitionConditions {
  [key: string]: string;
}

export interface ModeTransitionRule {
  conditions: ModeTransitionConditions;
  prompt: string;
  user_must_confirm: boolean;
  mode_floor?: {
    applies_when: AppliesWhen;
    minimum_mode: GuidanceModeName;
    override_requires: string;
  };
}

export interface ModeRules {
  recommend_promotion: {
    training_to_live?: ModeTransitionRule;
    live_to_expert?: ModeTransitionRule;
  };
  recommend_demotion: {
    to_live?: ModeTransitionRule;
    to_training?: ModeTransitionRule;
  };
  overrides: {
    user_can_lock_mode: boolean;
    organization_can_set_default: boolean;
    organization_can_set_maximum: boolean;
    hazard_class_can_set_mode_floor: boolean;
  };
}

// ---------------------------------------------------------------------------
// Section 8 — Locale
// ---------------------------------------------------------------------------

export interface LocaleFieldOverride {
  what?: string;
  why?: string;
  how?: string;
  common_errors?: string[];
}

export interface LocaleOverrides {
  [locale: string]: {
    fields?: Record<string, LocaleFieldOverride>;
  };
}

// ---------------------------------------------------------------------------
// Section 3.1 — Schema Envelope (Guidance Pack)
// ---------------------------------------------------------------------------

export interface ChangeLogEntry {
  version: string;
  date: string;
  notes: string;
}

export type GuidancePackStatus = 'draft' | 'review' | 'approved' | 'superseded';

export interface GuidancePack {
  guidance_pack_id: string;
  schema_version: string;
  platform: string;
  module: string;
  locale: string;
  status: GuidancePackStatus;
  authored_by: string;
  reviewed_by: string[];
  approved_by: string;
  effective_date: string;
  supersedes: string | null;
  change_log: ChangeLogEntry[];
  fields: Record<string, GuidanceFieldDefinition>;
  workflows?: Record<string, WorkflowDefinition>;
  contexts?: Record<string, unknown>;
  module_mode_overrides?: Record<string, ModuleModeOverride>;
  mode_rules?: ModeRules;
  locale_overrides?: LocaleOverrides;
}

// ---------------------------------------------------------------------------
// Section 5.5 — Telemetry Events
// ---------------------------------------------------------------------------

export type GuidanceTelemetryEventType =
  | 'guidance.viewed'
  | 'guidance.authority.expanded'
  | 'guidance.warning.dismissed'
  | 'guidance.action.clicked'
  | 'guidance.lookup.opened'
  | 'guidance.heritage.confirmed'
  | 'guidance.heritage.rejected'
  | 'guidance.validation.failed'
  | 'guidance.walkthrough.completed'
  | 'guidance.walkthrough.abandoned'
  | 'guidance.mode.changed'
  | 'guidance.schema.verified'
  | 'guidance.schema.stale';

/**
 * Telemetry payload. Per Section 5.5.2 (NON-NEGOTIABLE):
 * - NEVER include actual user-entered values
 * - Log characteristics (e.g. input_length), not content
 * - Subject to CUI/ITAR/export control review before deployment
 */
export interface GuidanceTelemetryEvent {
  type: GuidanceTelemetryEventType;
  timestamp: string;
  field?: string;
  tab?: 'what' | 'why' | 'how' | 'do';
  authority_ref?: string;
  condition_ref?: string;
  action_type?: string;
  target?: string;
  source?: string;
  extraction_confidence?: number;
  rule?: string;
  severity?: ValidationSeverity | WarningSeverity;
  module?: string;
  duration?: number;
  step_reached?: string;
  old_mode?: GuidanceModeName;
  new_mode?: GuidanceModeName;
  trigger?: string;
  pack_id?: string;
  version?: string;
  loaded_version?: string;
  latest_version?: string;
}

export type GuidanceTelemetryHandler = (event: GuidanceTelemetryEvent) => void;

// ---------------------------------------------------------------------------
// Provider Props (Section 5.1)
// ---------------------------------------------------------------------------

export interface GuidanceProviderProps {
  schema: GuidancePack;
  context: GuidanceContext;
  mode: GuidanceModeName;
  locale?: string;
  telemetryEnabled?: boolean;
  onEvent?: GuidanceTelemetryHandler;
  onModeChange?: (newMode: GuidanceModeName, trigger: string) => void;
  authorityRegistry?: Map<string, AuthorityRegistryEntry>;
  children: React.ReactNode;
}
