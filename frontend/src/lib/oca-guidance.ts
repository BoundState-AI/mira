import rawGuidance from '@/data/guidance.json';

export type OCAEngineStatus =
  | 'active_screening_input'
  | 'derived_default_override'
  | 'traceability_only'
  | 'reviewer_context'
  | 'topology_inference_input'
  | 'direct_signal'
  | 'partial_proxy'
  | 'cataloged_external'
  | 'requirement_gate'
  | 'decision_output';

export const OCA_ENGINE_STATUS_LABELS: Record<OCAEngineStatus, string> = {
  active_screening_input: 'Direct screening input',
  derived_default_override: 'Derived default / user override',
  traceability_only: 'Stored for traceability',
  reviewer_context: 'Reviewer context only',
  topology_inference_input: 'Topology / inference input',
  direct_signal: 'Directly screened mechanism',
  partial_proxy: 'Partially screened via proxy',
  cataloged_external: 'Cataloged mechanism; no direct UI signal',
  requirement_gate: 'Requirement gate in decision logic',
  decision_output: 'Decision output from the engine',
};

export interface OCAFieldGuidanceEntry {
  field_id: string;
  label: string;
  engine_status: OCAEngineStatus;
  what: string;
  why: string;
  guidance: string;
  source: string;
}

export interface OCAMechanismGuidanceEntry {
  mechanism_id: string;
  label: string;
  aliases?: string[];
  engine_status: OCAEngineStatus;
  what: string;
  why: string;
  guidance: string;
  source: string;
}

export interface OCAMprGuidanceEntry {
  mpr_id: string;
  label: string;
  engine_status: OCAEngineStatus;
  what: string;
  why: string;
  guidance: string;
  source: string;
}

export interface OCADispositionGuidanceEntry {
  disposition_id: string;
  label: string;
  engine_status: OCAEngineStatus;
  what: string;
  why: string;
  guidance: string;
  source: string;
}

interface OcaGuidanceDocument {
  version: number;
  inputs: OCAFieldGuidanceEntry[];
  mechanisms: OCAMechanismGuidanceEntry[];
  mprs: OCAMprGuidanceEntry[];
  dispositions: OCADispositionGuidanceEntry[];
}

const guidance = rawGuidance as OcaGuidanceDocument;

function normalizeLookupKey(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

const inputIndex = new Map(guidance.inputs.map((entry) => [entry.field_id, entry]));
const mprIndex = new Map(guidance.mprs.map((entry) => [entry.mpr_id, entry]));
const dispositionIndex = new Map(guidance.dispositions.map((entry) => [entry.disposition_id, entry]));

const mechanismIndex = new Map<string, OCAMechanismGuidanceEntry>();
for (const entry of guidance.mechanisms) {
  const lookupKeys = [entry.mechanism_id, entry.label, ...(entry.aliases ?? [])];
  for (const key of lookupKeys) {
    mechanismIndex.set(normalizeLookupKey(key), entry);
  }
}

export type OCAHelpEntry =
  | OCAFieldGuidanceEntry
  | OCAMechanismGuidanceEntry
  | OCAMprGuidanceEntry
  | OCADispositionGuidanceEntry;

export function getInputGuidance(fieldId: string): OCAFieldGuidanceEntry | null {
  return inputIndex.get(fieldId) ?? null;
}

export function getMechanismGuidance(mechanismIdOrLabel: string): OCAMechanismGuidanceEntry | null {
  return mechanismIndex.get(normalizeLookupKey(mechanismIdOrLabel)) ?? null;
}

export function getMprGuidance(mprId: string): OCAMprGuidanceEntry | null {
  return mprIndex.get(mprId) ?? null;
}

export function getDispositionGuidance(dispositionId: string): OCADispositionGuidanceEntry | null {
  return dispositionIndex.get(dispositionId) ?? null;
}

export const ocaGuidance = guidance;
