/**
 * BS-SPEC-GUIDANCE-001-REV2.1 Section 3.7 — Context & Applicability Evaluation
 *
 * Evaluates applies_when conditions against the current GuidanceContext.
 * Conditions are flat key-value AND (Section 3.7.2). null = always active.
 */

import type {
  AppliesWhen,
  GuidanceContext,
  FieldApplicability,
  GuidanceFieldDefinition,
  GuidanceModeName,
  WarningSeverity,
  ModuleModeOverride,
} from './types';

/**
 * Resolve a dot-path (e.g., "context.service_environment") against a context
 * object. Strips the leading "context." prefix if present.
 */
function resolveContextPath(context: GuidanceContext, path: string): unknown {
  const normalizedPath = path.startsWith('context.') ? path.slice(8) : path;
  const parts = normalizedPath.split('.');
  let current: unknown = context;
  for (const part of parts) {
    if (current == null || typeof current !== 'object') return undefined;
    current = (current as Record<string, unknown>)[part];
  }
  return current;
}

/**
 * Evaluate an applies_when condition against a context.
 * - null → always active (returns true)
 * - All conditions must be true (AND semantics)
 * - String value → equality check
 * - String[] value → set membership (OR within the array)
 */
export function evaluateCondition(
  condition: AppliesWhen,
  context: GuidanceContext,
): boolean {
  if (condition === null || condition === undefined) return true;

  for (const [path, expected] of Object.entries(condition)) {
    const actual = resolveContextPath(context, path);
    if (Array.isArray(expected)) {
      if (!expected.includes(String(actual))) return false;
    } else {
      if (String(actual) !== expected) return false;
    }
  }
  return true;
}

/**
 * Determine whether a field is visible given its applicability and context.
 */
export function isFieldVisible(
  field: GuidanceFieldDefinition,
  context: GuidanceContext,
): boolean {
  if (!field.applicability?.visible_when) return true;
  return evaluateCondition(field.applicability.visible_when, context);
}

/**
 * Determine whether a field is required given its applicability and context.
 */
export function isFieldRequired(
  field: GuidanceFieldDefinition,
  context: GuidanceContext,
): boolean {
  if (field.validation.required) return true;
  if (!field.applicability?.required_when) return false;
  return evaluateCondition(field.applicability.required_when, context);
}

/**
 * Determine whether a field gets enhanced guidance given context.
 */
export function isFieldEnhanced(
  field: GuidanceFieldDefinition,
  context: GuidanceContext,
): boolean {
  if (!field.applicability?.enhanced_when) return false;
  return evaluateCondition(field.applicability.enhanced_when, context);
}

/**
 * Filter a field's authorities to only those applicable in the current context.
 */
export function getActiveAuthorities(
  field: GuidanceFieldDefinition,
  context: GuidanceContext,
) {
  if (!field.authorities) return [];
  return field.authorities
    .filter((auth) => evaluateCondition(auth.applies_when, context))
    .sort((a, b) => (a.presentation_order ?? 99) - (b.presentation_order ?? 99));
}

/**
 * Filter a field's warnings to only those whose conditions are active.
 * The condition_ref is evaluated externally — here we just return all warnings.
 * Actual condition evaluation is the engine's responsibility.
 */
export function getActiveWarnings(
  field: GuidanceFieldDefinition,
  _context: GuidanceContext,
) {
  return field.warnings ?? [];
}

/**
 * Filter a field's actions to only those available in the current context.
 */
export function getActiveActions(
  field: GuidanceFieldDefinition,
  context: GuidanceContext,
) {
  if (!field.actions) return [];
  return field.actions.filter((action) =>
    evaluateCondition(action.available_when, context),
  );
}

/**
 * Section 6.1 — Determine the minimum warning severity to display based on
 * mode and module overrides.
 */
export function getMinimumWarningSeverity(
  mode: GuidanceModeName,
  moduleOverride: ModuleModeOverride | undefined,
): WarningSeverity | null {
  if (mode === 'training' || mode === 'live') return null; // show all
  // Expert mode
  if (moduleOverride) return moduleOverride.expert_mode_minimum_severity;
  return 'caution'; // default expert: caution and above
}

/**
 * Apply locale fallback (Section 8.1). Returns localized text or base text.
 */
export function resolveLocalizedText(
  baseText: string,
  localeOverrides: Record<string, string> | undefined,
  locale: string,
): string {
  if (!localeOverrides || locale === 'en') return baseText;
  return localeOverrides[locale] ?? baseText;
}
