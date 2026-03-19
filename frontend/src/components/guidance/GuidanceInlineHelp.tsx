import { GuidancePopover } from './GuidancePopover';
import { useFieldGuidance } from './GuidanceProvider';

interface GuidanceInlineHelpProps {
  name: string;
  className?: string;
  iconClassName?: string;
  align?: 'start' | 'center' | 'end';
}

export function GuidanceInlineHelp({
  name,
  className,
  iconClassName,
  align = 'start',
}: GuidanceInlineHelpProps) {
  const guidance = useFieldGuidance(name);

  if (!guidance) return null;

  return (
    <GuidancePopover
      field={guidance.field}
      fieldName={name}
      mode={guidance.mode}
      authorities={guidance.authorities}
      actions={guidance.actions}
      authorityRegistry={guidance.authorityRegistry}
      telemetry={guidance.telemetry}
      className={className}
      iconClassName={iconClassName}
      align={align}
    />
  );
}
