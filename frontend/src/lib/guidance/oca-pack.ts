/**
 * OCA Guidance Pack loader for the Universal Guidance Schema.
 *
 * Loads the migrated OCA guidance pack (oca-guidance-pack.json) and the
 * authority registry, providing them in the format expected by GuidanceProvider.
 *
 * Also provides backward-compatible lookup functions so existing OCA components
 * can migrate incrementally.
 */

import ocaPackRaw from '@/data/oca-guidance-pack.json';
import authorityRegistryRaw from '@/data/authority-registry.json';

import type {
  AuthorityRegistryEntry,
  GuidanceContext,
  GuidanceModeName,
  GuidancePack,
} from './types';

// ---------------------------------------------------------------------------
// Pack & Registry
// ---------------------------------------------------------------------------

export const ocaGuidancePack = ocaPackRaw as unknown as GuidancePack;

const registryEntries = authorityRegistryRaw as unknown as Record<string, AuthorityRegistryEntry>;

export const authorityRegistry = new Map<string, AuthorityRegistryEntry>(
  Object.entries(registryEntries),
);

// ---------------------------------------------------------------------------
// Default context factory
// ---------------------------------------------------------------------------

export function createOcaContext(overrides?: Partial<GuidanceContext>): GuidanceContext {
  return {
    platform: 'mira',
    module: 'oca',
    user_mode: 'training' as GuidanceModeName,
    locale: 'en',
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Backward-compatible lookup helpers
//
// These mirror the old oca-guidance.ts API so existing components can use
// them during incremental migration.
// ---------------------------------------------------------------------------

function normalizeLookupKey(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

/**
 * Get a field definition from the pack by field_id.
 * Supports both old-style field_ids (e.g., "workbench.material_name")
 * and new-style mechanism/mpr/disposition keys.
 */
export function getOcaField(fieldId: string) {
  return ocaGuidancePack.fields[fieldId] ?? null;
}

/**
 * Get mechanism guidance by mechanism_id or label.
 */
export function getOcaMechanismField(mechanismIdOrLabel: string) {
  const directKey = `mechanism.${mechanismIdOrLabel}`;
  if (ocaGuidancePack.fields[directKey]) {
    return ocaGuidancePack.fields[directKey];
  }

  // Fuzzy search by label
  const normalized = normalizeLookupKey(mechanismIdOrLabel);
  for (const [key, field] of Object.entries(ocaGuidancePack.fields)) {
    if (!key.startsWith('mechanism.')) continue;
    if (normalizeLookupKey(field.label) === normalized) return field;
    if (field.examples?.some((e) => normalizeLookupKey(e) === normalized)) return field;
  }
  return null;
}

/**
 * Get MPR guidance by mpr_id.
 */
export function getOcaMprField(mprId: string) {
  return ocaGuidancePack.fields[`mpr.${mprId}`] ?? null;
}

/**
 * Get disposition guidance by disposition_id.
 */
export function getOcaDispositionField(dispositionId: string) {
  return ocaGuidancePack.fields[`disposition.${dispositionId}`] ?? null;
}
