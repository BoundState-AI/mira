/**
 * BS-SPEC-GUIDANCE-001-REV2.1 Section 5.3 — GuidanceField
 *
 * Wrapper for any input. Reads schema, renders overlays, manages
 * validation state, surfaces warnings.
 *
 * Usage:
 * ```tsx
 * <GuidanceField name="material_designation">
 *   <MaterialInput />
 * </GuidanceField>
 * ```
 */

import React from 'react';

import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';

import { useFieldGuidance } from './GuidanceProvider';
import { GuidancePopover } from './GuidancePopover';
import { GuidanceValidationIndicator } from './GuidanceValidationIndicator';
import { GuidanceHeritageBanner } from './GuidanceHeritageBanner';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface GuidanceFieldProps {
  /** Field key in the guidance pack's `fields` map */
  name: string;
  /** Override the label from schema */
  label?: string;
  /** HTML for= attribute for the label */
  htmlFor?: string;
  /** Current validation state (provided by form library) */
  validationState?: 'valid' | 'invalid' | 'warning' | 'pending';
  /** Validation message from form library */
  validationMessage?: string;
  /** Heritage data override (populated by engine at runtime) */
  heritageSource?: string;
  heritageConfidence?: number;
  heritageConfirmed?: boolean;
  onHeritageConfirm?: () => void;
  onHeritageReject?: () => void;
  /** Custom class */
  className?: string;
  children: React.ReactNode;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function GuidanceField({
  name,
  label: labelOverride,
  htmlFor,
  validationState,
  validationMessage,
  heritageSource,
  heritageConfidence,
  heritageConfirmed,
  onHeritageConfirm,
  onHeritageReject,
  className,
  children,
}: GuidanceFieldProps) {
  const guidance = useFieldGuidance(name);

  // If no guidance exists for this field, render children only
  if (!guidance) {
    return <div className={className}>{children}</div>;
  }

  const { field, visible, required, enhanced, authorities, actions, mode, telemetry, authorityRegistry } = guidance;

  // Applicability: if not visible in current context, don't render
  if (!visible) return null;

  const displayLabel = labelOverride ?? field.label;

  // Heritage banner (Section 3.8)
  const showHeritage = heritageSource && !heritageConfirmed;
  const lowConfidence = (heritageConfidence ?? 100) < 80;

  return (
    <div className={cn('space-y-1.5', enhanced && mode === 'training' && 'ring-1 ring-primary/20 rounded-md p-2', className)}>
      {/* Label row with guidance popover */}
      <div className="flex items-center gap-1.5">
        <Label htmlFor={htmlFor} className={cn(required && "after:ml-0.5 after:text-destructive after:content-['*']")}>
          {displayLabel}
        </Label>
        <GuidancePopover
          field={field}
          fieldName={name}
          mode={mode}
          authorities={authorities}
          actions={actions}
          authorityRegistry={authorityRegistry}
          telemetry={telemetry}
        />
        {/* Authority badges removed — all OCA fields reference the same spec
            (BS-SPEC-OCA-001) so per-field badges were pure visual noise.
            Authority info remains accessible via the GuidancePopover (? icon). */}
      </div>

      {/* Inline field description — Training mode only (from field.what) */}
      {mode === 'training' && field.what && (
        <p className="text-[11px] leading-relaxed text-muted-foreground">{field.what}</p>
      )}

      {/* Heritage banner */}
      {showHeritage && (
        <GuidanceHeritageBanner
          source={heritageSource!}
          confidence={heritageConfidence ?? 0}
          confirmed={heritageConfirmed ?? false}
          lowConfidence={lowConfidence}
          displayTemplate={field.heritage?.display_when_present}
          mode={mode}
          fieldName={name}
          telemetry={telemetry}
          onConfirm={onHeritageConfirm}
          onReject={onHeritageReject}
        />
      )}

      {/* The actual input */}
      {children}

      {/* Validation indicator */}
      {validationState && validationState !== 'valid' && (
        <GuidanceValidationIndicator
          state={validationState}
          message={validationMessage}
          severity={field.validation.severity}
        />
      )}

      {/* Warnings from schema (Section 3.3)
          Training/Live: all warnings shown
          Expert: only severity === 'caution' (info suppressed)
          Policy warnings / compliance gates are NEVER suppressed (§6.1) */}
      {guidance.warnings.length > 0 && (
        <div className="space-y-1">
          {guidance.warnings
            .filter((w) => mode !== 'expert' || w.severity === 'caution')
            .map((w) => (
              <div
                key={w.condition_ref}
                className={cn(
                  'rounded-md px-2.5 py-1.5 text-[11px] leading-relaxed',
                  w.severity === 'caution'
                    ? 'border border-yellow-200 bg-yellow-50 text-yellow-800 dark:border-yellow-800 dark:bg-yellow-950 dark:text-yellow-200'
                    : 'border border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-200',
                )}
              >
                {w.message}
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
