export const UNAVAILABLE_MODULE_IDS = new Set<string>([
  "query",
  "test-classes",
  "mua-v10",
]);

export const HIDDEN_MODULE_IDS = new Set<string>([
  "forge",
  "forge-explorer",
]);

export const MODULE_UNAVAILABLE_TOOLTIP =
  "Temporarily unavailable while MAPTIS data-rights issues with Amentum are being resolved.";

export const MODULE_UNAVAILABLE_NOTICE = {
  badge: "Coming Soon!",
  title: "Module not available",
  description:
    "This module is temporarily unavailable while MAPTIS data-rights issues with Amentum are being resolved.",
} as const;

export function isUnavailableModuleId(id: string): boolean {
  return UNAVAILABLE_MODULE_IDS.has(id);
}

export function isHiddenModuleId(id: string): boolean {
  return HIDDEN_MODULE_IDS.has(id);
}
