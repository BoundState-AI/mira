/**
 * h2 guidance pack loader for the Universal Guidance Schema.
 */

import packRaw from '@/data/h2-guidance-pack.json';
import authorityRegistryRaw from '@/data/authority-registry.json';

import type {
  AuthorityRegistryEntry,
  GuidanceContext,
  GuidanceModeName,
  GuidancePack,
} from './types';

export const h2GuidancePack = packRaw as unknown as GuidancePack;

const registryEntries = authorityRegistryRaw as unknown as Record<string, AuthorityRegistryEntry>;

export const authorityRegistry = new Map<string, AuthorityRegistryEntry>(
  Object.entries(registryEntries),
);

export function createH2Context(overrides?: Partial<GuidanceContext>): GuidanceContext {
  return {
    platform: 'mira',
    module: 'h2',
    user_mode: 'training' as GuidanceModeName,
    locale: 'en',
    ...overrides,
  };
}

export function getH2Field(fieldId: string) {
  return h2GuidancePack.fields[fieldId] ?? null;
}
