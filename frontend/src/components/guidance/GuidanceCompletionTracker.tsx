/**
 * BS-SPEC-GUIDANCE-001-REV2.1 Section 5.3 — GuidanceCompletionTracker
 *
 * Progress indicator: required fields complete, warnings outstanding, next step.
 */

import React from 'react';
import { AlertTriangle, CheckCircle2, Circle } from 'lucide-react';

import { Progress } from '@/components/ui/progress';
import { cn } from '@/lib/utils';

interface FieldStatus {
  name: string;
  label: string;
  required: boolean;
  valid: boolean;
  hasWarnings: boolean;
}

interface GuidanceCompletionTrackerProps {
  fields: FieldStatus[];
  nextStep?: string;
  className?: string;
}

export function GuidanceCompletionTracker({
  fields,
  nextStep,
  className,
}: GuidanceCompletionTrackerProps) {
  const requiredFields = fields.filter((f) => f.required);
  const completedRequired = requiredFields.filter((f) => f.valid);
  const warningCount = fields.filter((f) => f.hasWarnings).length;
  const progress = requiredFields.length > 0
    ? Math.round((completedRequired.length / requiredFields.length) * 100)
    : 100;

  return (
    <div className={cn('space-y-3 rounded-lg border border-border p-4', className)}>
      {/* Progress bar */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium text-foreground">
            Required fields: {completedRequired.length}/{requiredFields.length}
          </span>
          <span className="text-muted-foreground">{progress}%</span>
        </div>
        <Progress value={progress} className="h-1.5" />
      </div>

      {/* Warnings outstanding */}
      {warningCount > 0 && (
        <div className="flex items-center gap-1.5 text-xs text-yellow-600 dark:text-yellow-400">
          <AlertTriangle className="h-3.5 w-3.5" />
          <span>{warningCount} warning{warningCount !== 1 ? 's' : ''} outstanding</span>
        </div>
      )}

      {/* Field status list (collapsed by default, shows incomplete only) */}
      {requiredFields.length > 0 && completedRequired.length < requiredFields.length && (
        <div className="space-y-1">
          <span className="text-[11px] font-medium text-muted-foreground">Remaining:</span>
          {requiredFields
            .filter((f) => !f.valid)
            .map((f) => (
              <div key={f.name} className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <Circle className="h-2.5 w-2.5" />
                <span>{f.label}</span>
              </div>
            ))}
        </div>
      )}

      {/* All complete */}
      {requiredFields.length > 0 && completedRequired.length === requiredFields.length && (
        <div className="flex items-center gap-1.5 text-xs text-green-600 dark:text-green-400">
          <CheckCircle2 className="h-3.5 w-3.5" />
          <span>All required fields complete</span>
        </div>
      )}

      {/* Next step */}
      {nextStep && (
        <div className="border-t border-border pt-2 text-[11px] text-muted-foreground">
          <span className="font-medium">Next: </span>
          {nextStep}
        </div>
      )}
    </div>
  );
}
