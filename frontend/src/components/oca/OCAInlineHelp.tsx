import { Label } from '@/components/ui/label';
import { GuidancePopover } from '@/components/guidance/GuidancePopover';
import {
  authorityRegistry,
  getOcaDispositionField,
  getOcaField,
  getOcaMechanismField,
  getOcaMprField,
} from '@/lib/guidance/oca-pack';
import { cn } from '@/lib/utils';
import type { GuidanceFieldDefinition } from '@/lib/guidance/types';
import type { OCAHelpEntry } from '@/lib/oca-guidance';

interface OCAInlineHelpProps {
  entry?: OCAHelpEntry | null;
  className?: string;
  iconClassName?: string;
  align?: 'start' | 'center' | 'end';
}

function resolveGuidanceField(entry: OCAHelpEntry | null | undefined): GuidanceFieldDefinition | null {
  if (!entry) return null;

  if ('field_id' in entry) {
    return getOcaField(entry.field_id);
  }
  if ('mechanism_id' in entry) {
    return getOcaMechanismField(entry.mechanism_id);
  }
  if ('mpr_id' in entry) {
    return getOcaMprField(entry.mpr_id);
  }
  if ('disposition_id' in entry) {
    return getOcaDispositionField(entry.disposition_id);
  }

  return null;
}

export function OCAInlineHelp({
  entry,
  className,
  iconClassName,
  align = 'start',
}: OCAInlineHelpProps) {
  const field = resolveGuidanceField(entry);
  if (!field) return null;

  return (
    <GuidancePopover
      field={field}
      fieldName={field.label}
      mode="live"
      authorities={field.authorities ?? []}
      actions={field.actions ?? []}
      authorityRegistry={authorityRegistry}
      className={className}
      iconClassName={iconClassName}
      align={align}
    />
  );
}

interface OCAHelpLabelProps {
  htmlFor?: string;
  children: React.ReactNode;
  entry?: OCAHelpEntry | null;
  className?: string;
  labelClassName?: string;
}

export function OCAHelpLabel({
  htmlFor,
  children,
  entry,
  className,
  labelClassName,
}: OCAHelpLabelProps) {
  return (
    <div className={cn('flex items-center gap-1.5', className)}>
      <Label htmlFor={htmlFor} className={labelClassName}>
        {children}
      </Label>
      <OCAInlineHelp entry={entry} />
    </div>
  );
}
