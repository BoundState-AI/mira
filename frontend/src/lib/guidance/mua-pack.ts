/**
 * mua guidance pack loader for the Universal Guidance Schema.
 */

import packRaw from '@/data/mua-guidance-pack.json';
import authorityRegistryRaw from '@/data/authority-registry.json';

import type {
  AuthorityRegistryEntry,
  GuidanceContext,
  GuidanceModeName,
  GuidancePack,
} from './types';

export const muaGuidancePack = packRaw as unknown as GuidancePack;

const registryEntries = authorityRegistryRaw as unknown as Record<string, AuthorityRegistryEntry>;

export const authorityRegistry = new Map<string, AuthorityRegistryEntry>(
  Object.entries(registryEntries),
);

export function createMuaContext(overrides?: Partial<GuidanceContext>): GuidanceContext {
  return {
    platform: 'mira',
    module: 'mua',
    user_mode: 'training' as GuidanceModeName,
    locale: 'en',
    ...overrides,
  };
}

export function getMuaField(fieldId: string) {
  return muaGuidancePack.fields[fieldId] ?? null;
}
