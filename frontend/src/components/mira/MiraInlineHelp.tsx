import { CircleHelp } from 'lucide-react';

import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import type { MiraGuidanceEntry } from '@/lib/mira-guidance';

interface MiraInlineHelpProps {
  entry?: MiraGuidanceEntry | null;
  className?: string;
  iconClassName?: string;
  align?: 'start' | 'center' | 'end';
  title?: string;
}

export function MiraInlineHelp({
  entry,
  className,
  iconClassName,
  align = 'start',
  title,
}: MiraInlineHelpProps) {
  if (!entry) return null;

  const heading = title ?? entry.label;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            'inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
            className,
          )}
          aria-label={`Help for ${heading}`}
        >
          <CircleHelp className={cn('h-3.5 w-3.5', iconClassName)} />
        </button>
      </PopoverTrigger>
      <PopoverContent align={align} className="w-80 space-y-3">
        <div className="space-y-1">
          <div className="text-sm font-semibold text-foreground">{heading}</div>
          <p className="text-xs leading-relaxed text-muted-foreground">{entry.what}</p>
        </div>
        <div className="space-y-2 text-xs leading-relaxed text-foreground">
          <p>
            <span className="font-semibold">Why it matters:</span>{' '}
            {entry.why}
          </p>
          <p>
            <span className="font-semibold">How to use it:</span>{' '}
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

interface MiraHelpLabelProps {
  htmlFor?: string;
  children: React.ReactNode;
  entry?: MiraGuidanceEntry | null;
  className?: string;
  labelClassName?: string;
  title?: string;
}

export function MiraHelpLabel({
  htmlFor,
  children,
  entry,
  className,
  labelClassName,
  title,
}: MiraHelpLabelProps) {
  return (
    <div className={cn('flex items-center gap-1.5', className)}>
      <Label htmlFor={htmlFor} className={labelClassName}>
        {children}
      </Label>
      <MiraInlineHelp entry={entry} title={title} />
    </div>
  );
}
