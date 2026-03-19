/**
 * miul guidance pack loader for the Universal Guidance Schema.
 */

import packRaw from '@/data/miul-guidance-pack.json';
import authorityRegistryRaw from '@/data/authority-registry.json';

import type {
  AuthorityRegistryEntry,
  GuidanceContext,
  GuidanceModeName,
  GuidancePack,
} from './types';

export const miulGuidancePack = packRaw as unknown as GuidancePack;

const registryEntries = authorityRegistryRaw as unknown as Record<string, AuthorityRegistryEntry>;

export const authorityRegistry = new Map<string, AuthorityRegistryEntry>(
  Object.entries(registryEntries),
);

export function createMiulContext(overrides?: Partial<GuidanceContext>): GuidanceContext {
  return {
    platform: 'mira',
    module: 'miul',
    user_mode: 'training' as GuidanceModeName,
    locale: 'en',
    ...overrides,
  };
}

export function getMiulField(fieldId: string) {
  return miulGuidancePack.fields[fieldId] ?? null;
}
