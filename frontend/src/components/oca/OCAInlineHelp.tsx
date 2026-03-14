import { CircleHelp } from 'lucide-react';

import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { OCA_ENGINE_STATUS_LABELS } from '@/lib/oca-guidance';
import { cn } from '@/lib/utils';
import type { OCAHelpEntry } from '@/lib/oca-guidance';

interface OCAInlineHelpProps {
  entry?: OCAHelpEntry | null;
  className?: string;
  iconClassName?: string;
  align?: 'start' | 'center' | 'end';
}

export function OCAInlineHelp({
  entry,
  className,
  iconClassName,
  align = 'start',
}: OCAInlineHelpProps) {
  if (!entry) return null;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            'inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
            className,
          )}
          aria-label={`Help for ${entry.label}`}
        >
          <CircleHelp className={cn('h-3.5 w-3.5', iconClassName)} />
        </button>
      </PopoverTrigger>
      <PopoverContent align={align} className="w-80 space-y-3">
        <div className="space-y-1">
          <div className="text-sm font-semibold text-foreground">{entry.label}</div>
          <p className="text-xs leading-relaxed text-muted-foreground">{entry.what}</p>
        </div>
        <div className="rounded-md border border-border bg-muted/40 px-2.5 py-2 text-[11px] leading-relaxed text-muted-foreground">
          <span className="font-semibold text-foreground">Engine status:</span>
          {' '}
          {OCA_ENGINE_STATUS_LABELS[entry.engine_status]}
        </div>
        <div className="space-y-2 text-xs leading-relaxed text-foreground">
          <p>
            <span className="font-semibold">Why it matters:</span>
            {' '}
            {entry.why}
          </p>
          <p>
            <span className="font-semibold">How to use it:</span>
            {' '}
            {entry.guidance}
          </p>
        </div>
        <div className="border-t border-border pt-2 text-[11px] leading-relaxed text-muted-foreground">
          {entry.source}
        </div>
      </PopoverContent>
    </Popover>
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
