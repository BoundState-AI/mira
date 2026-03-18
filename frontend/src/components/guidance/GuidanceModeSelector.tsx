/**
 * BS-SPEC-GUIDANCE-001-REV2.1 Section 6 — GuidanceModeSelector
 *
 * Training / Live / Expert mode selection with adaptive promotion
 * recommendations. Mode floors enforced by context/hazard class.
 *
 * Non-negotiable (Section 6.1):
 * - Policy warnings and compliance gates are NEVER suppressed in any mode.
 * - Mode floors are context-driven and admin-overridable only.
 */

import React, { useState } from 'react';
import { GraduationCap, Monitor, Rocket } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { GuidanceModeName, ModeRules, ModuleModeOverride, GuidanceContext } from '@/lib/guidance/types';
import { evaluateCondition } from '@/lib/guidance/context';

interface GuidanceModeOption {
  id: GuidanceModeName;
  label: string;
  description: string;
  icon: React.ElementType;
}

const MODE_OPTIONS: GuidanceModeOption[] = [
  {
    id: 'training',
    label: 'Training',
    description: 'Full guidance, walkthroughs, all warnings visible',
    icon: GraduationCap,
  },
  {
    id: 'live',
    label: 'Live',
    description: 'On-demand guidance, badges visible, no walkthroughs',
    icon: Monitor,
  },
  {
    id: 'expert',
    label: 'Expert',
    description: 'Minimal chrome, errors + critical cautions only',
    icon: Rocket,
  },
];

interface GuidanceModeSelectorProps {
  currentMode: GuidanceModeName;
  context: GuidanceContext;
  modeRules?: ModeRules;
  moduleOverride?: ModuleModeOverride;
  onModeChange: (mode: GuidanceModeName, trigger: string) => void;
  className?: string;
}

const MODE_ORDER: Record<GuidanceModeName, number> = {
  training: 0,
  live: 1,
  expert: 2,
};

/**
 * Check if a mode is allowed given the mode floor from context.
 */
function isModeAllowed(
  mode: GuidanceModeName,
  modeRules: ModeRules | undefined,
  context: GuidanceContext,
): boolean {
  if (!modeRules) return true;

  // Check demotion mode floors
  const demotion = modeRules.recommend_demotion;
  if (demotion?.to_live?.mode_floor) {
    const floor = demotion.to_live.mode_floor;
    if (evaluateCondition(floor.applies_when, context)) {
      const minOrder = MODE_ORDER[floor.minimum_mode];
      if (MODE_ORDER[mode] < minOrder) return false;
    }
  }

  return true;
}

export function GuidanceModeSelector({
  currentMode,
  context,
  modeRules,
  moduleOverride,
  onModeChange,
  className,
}: GuidanceModeSelectorProps) {
  const [promotionDismissed, setPromotionDismissed] = useState(false);

  return (
    <div className={cn('flex items-center gap-1', className)}>
      {MODE_OPTIONS.map((option) => {
        const allowed = isModeAllowed(option.id, modeRules, context);
        const isActive = currentMode === option.id;
        const Icon = option.icon;

        return (
          <button
            key={option.id}
            type="button"
            disabled={!allowed}
            onClick={() => {
              if (!isActive && allowed) {
                onModeChange(option.id, 'user_selection');
              }
            }}
            className={cn(
              'inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium transition-colors',
              isActive
                ? 'bg-primary text-primary-foreground'
                : allowed
                  ? 'text-muted-foreground hover:bg-muted hover:text-foreground'
                  : 'cursor-not-allowed text-muted-foreground/40',
            )}
            title={
              !allowed
                ? `${option.label} mode is below the minimum for this context`
                : option.description
            }
          >
            <Icon className="h-3 w-3" />
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
