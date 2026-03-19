/**
 * mp_plan guidance pack loader for the Universal Guidance Schema.
 */

import packRaw from '@/data/mp-plan-guidance-pack.json';
import authorityRegistryRaw from '@/data/authority-registry.json';

import type {
  AuthorityRegistryEntry,
  GuidanceContext,
  GuidanceModeName,
  GuidancePack,
} from './types';

export const mpPlanGuidancePack = packRaw as unknown as GuidancePack;

const registryEntries = authorityRegistryRaw as unknown as Record<string, AuthorityRegistryEntry>;

export const authorityRegistry = new Map<string, AuthorityRegistryEntry>(
  Object.entries(registryEntries),
);

export function createMpPlanContext(overrides?: Partial<GuidanceContext>): GuidanceContext {
  return {
    platform: 'mira',
    module: 'mp_plan',
    user_mode: 'training' as GuidanceModeName,
    locale: 'en',
    ...overrides,
  };
}

export function getMpPlanField(fieldId: string) {
  return mpPlanGuidancePack.fields[fieldId] ?? null;
}
