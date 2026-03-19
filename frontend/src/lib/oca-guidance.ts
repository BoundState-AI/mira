import {
  authorityRegistry,
  getOcaDispositionField,
  getOcaField,
  getOcaMechanismField,
  getOcaMprField,
  ocaGuidancePack,
} from '@/lib/guidance/oca-pack';

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

export type OCAHelpEntry =
  | OCAFieldGuidanceEntry
  | OCAMechanismGuidanceEntry
  | OCAMprGuidanceEntry
  | OCADispositionGuidanceEntry;

function pickEngineStatus(tags: string[] | undefined): OCAEngineStatus {
  const candidates = tags ?? [];
  for (const tag of candidates) {
    if (tag in OCA_ENGINE_STATUS_LABELS) {
      return tag as OCAEngineStatus;
    }
  }
  return 'reviewer_context';
}

function formatSource(fieldName: string): string {
  const primaryAuthority = ocaGuidancePack.fields[fieldName]?.authorities?.[0];
  if (!primaryAuthority) {
    return 'BoundState OCA guidance pack';
  }

  const entry = authorityRegistry.get(primaryAuthority.authority_ref);
  if (!entry) {
    return primaryAuthority.authority_ref;
  }

  const parts = [entry.document_id];
  if (entry.revision) parts.push(entry.revision);
  if (entry.section) parts.push(`§${entry.section}`);
  if (entry.requirement_id) parts.push(entry.requirement_id);
  return parts.join(' ');
}

function toFieldEntry(fieldId: string): OCAFieldGuidanceEntry | null {
  const field = getOcaField(fieldId);
  if (!field) return null;

  return {
    field_id: fieldId,
    label: field.label,
    engine_status: pickEngineStatus(field.tags),
    what: field.what,
    why: field.why,
    guidance: field.how ?? '',
    source: formatSource(fieldId),
  };
}

function toMechanismEntry(mechanismIdOrLabel: string): OCAMechanismGuidanceEntry | null {
  const field = getOcaMechanismField(mechanismIdOrLabel);
  if (!field) return null;

  const mechanismId = Object.entries(ocaGuidancePack.fields).find(
    ([key, candidate]) =>
      key.startsWith('mechanism.') &&
      candidate.label === field.label,
  )?.[0].replace(/^mechanism\./, '') ?? mechanismIdOrLabel;

  return {
    mechanism_id: mechanismId,
    label: field.label,
    aliases: field.examples,
    engine_status: pickEngineStatus(field.tags),
    what: field.what,
    why: field.why,
    guidance: field.how ?? '',
    source: formatSource(`mechanism.${mechanismId}`),
  };
}

function toMprEntry(mprId: string): OCAMprGuidanceEntry | null {
  const field = getOcaMprField(mprId);
  if (!field) return null;

  return {
    mpr_id: mprId,
    label: field.label,
    engine_status: pickEngineStatus(field.tags),
    what: field.what,
    why: field.why,
    guidance: field.how ?? '',
    source: formatSource(`mpr.${mprId}`),
  };
}

function toDispositionEntry(dispositionId: string): OCADispositionGuidanceEntry | null {
  const field = getOcaDispositionField(dispositionId);
  if (!field) return null;

  return {
    disposition_id: dispositionId,
    label: field.label,
    engine_status: pickEngineStatus(field.tags),
    what: field.what,
    why: field.why,
    guidance: field.how ?? '',
    source: formatSource(`disposition.${dispositionId}`),
  };
}

function buildCompatibilityDocument(): OcaGuidanceDocument {
  const inputs: OCAFieldGuidanceEntry[] = [];
  const mechanisms: OCAMechanismGuidanceEntry[] = [];
  const mprs: OCAMprGuidanceEntry[] = [];
  const dispositions: OCADispositionGuidanceEntry[] = [];

  for (const fieldId of Object.keys(ocaGuidancePack.fields)) {
    if (fieldId.startsWith('mechanism.')) {
      const mechanism = toMechanismEntry(fieldId.replace(/^mechanism\./, ''));
      if (mechanism) mechanisms.push(mechanism);
      continue;
    }
    if (fieldId.startsWith('mpr.')) {
      const mpr = toMprEntry(fieldId.replace(/^mpr\./, ''));
      if (mpr) mprs.push(mpr);
      continue;
    }
    if (fieldId.startsWith('disposition.')) {
      const disposition = toDispositionEntry(fieldId.replace(/^disposition\./, ''));
      if (disposition) dispositions.push(disposition);
      continue;
    }

    const input = toFieldEntry(fieldId);
    if (input) inputs.push(input);
  }

  return {
    version: Number.parseFloat(ocaGuidancePack.schema_version) || 1,
    inputs,
    mechanisms,
    mprs,
    dispositions,
  };
}

export function getInputGuidance(fieldId: string): OCAFieldGuidanceEntry | null {
  return toFieldEntry(fieldId);
}

export function getMechanismGuidance(mechanismIdOrLabel: string): OCAMechanismGuidanceEntry | null {
  return toMechanismEntry(mechanismIdOrLabel);
}

export function getMprGuidance(mprId: string): OCAMprGuidanceEntry | null {
  return toMprEntry(mprId);
}

export function getDispositionGuidance(dispositionId: string): OCADispositionGuidanceEntry | null {
  return toDispositionEntry(dispositionId);
}

export const ocaGuidance = buildCompatibilityDocument();
