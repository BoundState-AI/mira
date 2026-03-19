/**
 * fracture guidance pack loader for the Universal Guidance Schema.
 */

import packRaw from '@/data/fracture-guidance-pack.json';
import authorityRegistryRaw from '@/data/authority-registry.json';

import type {
  AuthorityRegistryEntry,
  GuidanceContext,
  GuidanceModeName,
  GuidancePack,
} from './types';

export const fractureGuidancePack = packRaw as unknown as GuidancePack;

const registryEntries = authorityRegistryRaw as unknown as Record<string, AuthorityRegistryEntry>;

export const authorityRegistry = new Map<string, AuthorityRegistryEntry>(
  Object.entries(registryEntries),
);

export function createFractureContext(overrides?: Partial<GuidanceContext>): GuidanceContext {
  return {
    platform: 'mira',
    module: 'fracture',
    user_mode: 'training' as GuidanceModeName,
    locale: 'en',
    ...overrides,
  };
}

export function getFractureField(fieldId: string) {
  return fractureGuidancePack.fields[fieldId] ?? null;
}
