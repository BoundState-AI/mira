/**
 * Bridge components that provide the old OCAHelpLabel/OCAInlineHelp API
 * backed by the new Universal Guidance Schema infrastructure.
 *
 * This allows incremental migration of the OCA Workbench. Existing call sites
 * can switch imports from '@/components/oca/OCAInlineHelp' to this file
 * without changing any props.
 *
 * Once migration is complete, call sites should migrate to <GuidanceField>
 * for full spec compliance (authority badges, heritage banners, etc.).
 */

import React from 'react';

import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';
import type { GuidanceFieldDefinition, GuidanceModeName } from '@/lib/guidance/types';

import { GuidancePopover } from './GuidancePopover';
import { getOcaField, getOcaMechanismField, getOcaMprField, getOcaDispositionField, authorityRegistry } from '@/lib/guidance/oca-pack';

// ---------------------------------------------------------------------------
// Bridge: OCAInlineHelp → GuidancePopover
// ---------------------------------------------------------------------------

interface OCAInlineHelpBridgeProps {
  /** Old-style field_id (e.g., "workbench.material_name") */
  fieldId?: string;
  /** Or pass a field definition directly from one of the old lookup functions */
  field?: GuidanceFieldDefinition | null;
  mode?: GuidanceModeName;
  className?: string;
  iconClassName?: string;
  align?: 'start' | 'center' | 'end';
}

export function OCAInlineHelpBridge({
  fieldId,
  field: fieldProp,
  mode = 'live',
  className,
  iconClassName,
  align = 'start',
}: OCAInlineHelpBridgeProps) {
  const field = fieldProp ?? (fieldId ? getOcaField(fieldId) : null);
  if (!field) return null;

  const name = fieldId ?? field.label;

  return (
    <GuidancePopover
      field={field}
      fieldName={name}
      mode={mode}
      authorityRegistry={authorityRegistry}
      className={className}
      iconClassName={iconClassName}
      align={align}
    />
  );
}

// ---------------------------------------------------------------------------
// Bridge: OCAHelpLabel → Label + GuidancePopover
// ---------------------------------------------------------------------------

interface OCAHelpLabelBridgeProps {
  htmlFor?: string;
  children: React.ReactNode;
  fieldId?: string;
  field?: GuidanceFieldDefinition | null;
  mode?: GuidanceModeName;
  className?: string;
  labelClassName?: string;
}

export function OCAHelpLabelBridge({
  htmlFor,
  children,
  fieldId,
  field: fieldProp,
  mode = 'live',
  className,
  labelClassName,
}: OCAHelpLabelBridgeProps) {
  const field = fieldProp ?? (fieldId ? getOcaField(fieldId) : null);

  return (
    <div className={cn('flex items-center gap-1.5', className)}>
      <Label htmlFor={htmlFor} className={labelClassName}>
        {children}
      </Label>
      {field && (
        <GuidancePopover
          field={field}
          fieldName={fieldId ?? field.label}
          mode={mode}
          authorityRegistry={authorityRegistry}
        />
      )}
    </div>
  );
}
