/**
 * BS-SPEC-GUIDANCE-001-REV2.1 Section 5.3 — GuidancePopover
 *
 * Progressive disclosure. Tabs: What / Why / How / Do.
 * Hover opens What; click opens full popover.
 *
 * Accessibility (Section 5.4):
 * - role="dialog" for click popover
 * - Keyboard navigable (Tab, Escape, Enter)
 * - Focus trapping on open, focus return on close
 * - Screen reader structured text
 */

import React, { useState } from 'react';
import { CircleHelp, ExternalLink } from 'lucide-react';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import type {
  AuthorityRef,
  AuthorityRegistryEntry,
  GuidanceAction,
  GuidanceFieldDefinition,
  GuidanceModeName,
} from '@/lib/guidance/types';
import type { TelemetryEmitter } from '@/lib/guidance/telemetry';

// ---------------------------------------------------------------------------
// Tab definitions
// ---------------------------------------------------------------------------

type TabId = 'what' | 'why' | 'how' | 'do';

interface TabDef {
  id: TabId;
  label: string;
}

const TABS: TabDef[] = [
  { id: 'what', label: 'What' },
  { id: 'why', label: 'Why' },
  { id: 'how', label: 'How' },
  { id: 'do', label: 'Do' },
];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface GuidancePopoverProps {
  field: GuidanceFieldDefinition;
  fieldName: string;
  mode: GuidanceModeName;
  authorities?: AuthorityRef[];
  actions?: GuidanceAction[];
  authorityRegistry?: Map<string, AuthorityRegistryEntry>;
  telemetry?: TelemetryEmitter;
  className?: string;
  iconClassName?: string;
  align?: 'start' | 'center' | 'end';
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function GuidancePopover({
  field,
  fieldName,
  mode,
  authorities = [],
  actions = [],
  authorityRegistry = new Map(),
  telemetry,
  className,
  iconClassName,
  align = 'start',
}: GuidancePopoverProps) {
  const [activeTab, setActiveTab] = useState<TabId>('what');
  const [isOpen, setIsOpen] = useState(false);

  // Determine which tabs have content and are allowed in current mode
  // Expert: What + Why only (hide How and Do)
  // Training/Live: all tabs that have content
  const hasHow = !!field.how;
  const hasDo = actions.length > 0;
  const visibleTabs = TABS.filter((t) => {
    if (t.id === 'how' && (!hasHow || mode === 'expert')) return false;
    if (t.id === 'do' && (!hasDo || mode === 'expert')) return false;
    return true;
  });

  function handleTabChange(tab: TabId) {
    setActiveTab(tab);
    telemetry?.viewed(fieldName, tab);
  }

  function handleOpen(open: boolean) {
    setIsOpen(open);
    if (open) {
      telemetry?.viewed(fieldName, 'what');
      setActiveTab('what');
    }
  }

  // Expert mode: minimal trigger
  if (mode === 'expert') {
    return (
      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>
            <Popover open={isOpen} onOpenChange={handleOpen}>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  className={cn(
                    'inline-flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full text-muted-foreground/50 transition-colors hover:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    className,
                  )}
                  aria-label={`Help for ${field.label}`}
                >
                  <CircleHelp className={cn('h-3 w-3', iconClassName)} />
                </button>
              </PopoverTrigger>
              <PopoverContent
                align={align}
                className="w-80"
                role="dialog"
                aria-label={`Guidance for ${field.label}`}
              >
                <PopoverBody
                  field={field}
                  fieldName={fieldName}
                  mode={mode}
                  activeTab={activeTab}
                  visibleTabs={visibleTabs}
                  authorities={authorities}
                  actions={actions}
                  authorityRegistry={authorityRegistry}
                  telemetry={telemetry}
                  onTabChange={handleTabChange}
                />
              </PopoverContent>
            </Popover>
          </TooltipTrigger>
          <TooltipContent side="top" className="max-w-64 text-xs">
            {field.what}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  // Training/Live: full popover with hover tooltip
  return (
    <TooltipProvider delayDuration={300}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Popover open={isOpen} onOpenChange={handleOpen}>
            <PopoverTrigger asChild>
              <button
                type="button"
                className={cn(
                  'inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
                  className,
                )}
                aria-label={`Help for ${field.label}`}
              >
                <CircleHelp className={cn('h-3.5 w-3.5', iconClassName)} />
              </button>
            </PopoverTrigger>
            <PopoverContent
              align={align}
              className="w-96"
              role="dialog"
              aria-label={`Guidance for ${field.label}`}
            >
              <PopoverBody
                field={field}
                fieldName={fieldName}
                mode={mode}
                activeTab={activeTab}
                visibleTabs={visibleTabs}
                authorities={authorities}
                actions={actions}
                authorityRegistry={authorityRegistry}
                telemetry={telemetry}
                onTabChange={handleTabChange}
              />
            </PopoverContent>
          </Popover>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-64 text-xs">
          {field.what}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

// ---------------------------------------------------------------------------
// Popover Body
// ---------------------------------------------------------------------------

interface PopoverBodyProps {
  field: GuidanceFieldDefinition;
  fieldName: string;
  mode: GuidanceModeName;
  activeTab: TabId;
  visibleTabs: TabDef[];
  authorities: AuthorityRef[];
  actions: GuidanceAction[];
  authorityRegistry: Map<string, AuthorityRegistryEntry>;
  telemetry?: TelemetryEmitter;
  onTabChange: (tab: TabId) => void;
}

function PopoverBody({
  field,
  fieldName,
  mode,
  activeTab,
  visibleTabs,
  authorities,
  actions,
  authorityRegistry,
  telemetry,
  onTabChange,
}: PopoverBodyProps) {
  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="text-sm font-semibold text-foreground">{field.label}</div>

      {/* Tab bar */}
      {visibleTabs.length > 1 && (
        <div className="flex gap-1 border-b border-border" role="tablist">
          {visibleTabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.id}
              className={cn(
                'px-3 py-1.5 text-xs font-medium transition-colors',
                activeTab === tab.id
                  ? 'border-b-2 border-primary text-foreground'
                  : 'text-muted-foreground hover:text-foreground',
              )}
              onClick={() => onTabChange(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      )}

      {/* Tab content */}
      <div role="tabpanel" className="text-xs leading-relaxed">
        {activeTab === 'what' && <WhatPanel field={field} mode={mode} />}
        {activeTab === 'why' && (
          <WhyPanel
            field={field}
            fieldName={fieldName}
            mode={mode}
            authorities={authorities}
            authorityRegistry={authorityRegistry}
            telemetry={telemetry}
          />
        )}
        {activeTab === 'how' && <HowPanel field={field} />}
        {activeTab === 'do' && (
          <DoPanel
            fieldName={fieldName}
            actions={actions}
            telemetry={telemetry}
          />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab Panels
// ---------------------------------------------------------------------------

function WhatPanel({ field, mode }: { field: GuidanceFieldDefinition; mode: GuidanceModeName }) {
  // Training: examples + common_errors
  // Live: examples only (common_errors hidden)
  // Expert: neither examples nor common_errors
  const showExamples = mode !== 'expert';
  const showCommonErrors = mode === 'training';

  return (
    <div className="space-y-2">
      <p className="text-muted-foreground">{field.what}</p>
      {showExamples && field.examples && field.examples.length > 0 && (
        <div>
          <span className="font-semibold text-foreground">Examples: </span>
          <span className="text-muted-foreground">{field.examples.join(', ')}</span>
        </div>
      )}
      {showCommonErrors && field.common_errors && field.common_errors.length > 0 && (
        <div className="space-y-1">
          <span className="font-semibold text-foreground">Common errors:</span>
          <ul className="ml-4 list-disc text-muted-foreground">
            {field.common_errors.map((err, i) => (
              <li key={i}>{err}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function WhyPanel({
  field,
  fieldName,
  mode,
  authorities,
  authorityRegistry,
  telemetry,
}: {
  field: GuidanceFieldDefinition;
  fieldName: string;
  mode: GuidanceModeName;
  authorities: AuthorityRef[];
  authorityRegistry: Map<string, AuthorityRegistryEntry>;
  telemetry?: TelemetryEmitter;
}) {
  // Training: citations expanded by default
  // Live/Expert: citations collapsed (click to expand)
  const defaultExpanded = mode === 'training';

  // Filter out internal BoundState specs — only show real external standards
  const externalAuthorities = authorities.filter((auth) => {
    const entry = authorityRegistry.get(auth.authority_ref);
    if (!entry) return true; // unknown → show (safe default)
    return entry.source_type !== 'internal_controlled_copy' && entry.source_type !== 'derived_summary';
  });

  return (
    <div className="space-y-2">
      <p className="text-foreground">{field.why}</p>
      {externalAuthorities.length > 0 && (
        <div className="space-y-1.5">
          <span className="font-semibold text-foreground">Governing standards:</span>
          {externalAuthorities.map((auth) => {
            const entry = authorityRegistry.get(auth.authority_ref);
            return (
              <AuthorityInline
                key={auth.authority_ref}
                authRef={auth}
                entry={entry}
                fieldName={fieldName}
                telemetry={telemetry}
                defaultExpanded={defaultExpanded}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

function HowPanel({ field }: { field: GuidanceFieldDefinition }) {
  return <p className="text-foreground">{field.how}</p>;
}

function DoPanel({
  fieldName,
  actions,
  telemetry,
}: {
  fieldName: string;
  actions: GuidanceAction[];
  telemetry?: TelemetryEmitter;
}) {
  return (
    <div className="space-y-1.5">
      {actions.map((action, i) => (
        <button
          key={i}
          type="button"
          className="flex w-full items-center gap-2 rounded-md border border-border px-3 py-2 text-left text-xs transition-colors hover:bg-muted"
          onClick={() => {
            telemetry?.actionClicked(fieldName, action.action, action.target);
          }}
        >
          <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground" />
          <span>{action.prompt}</span>
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Authority inline display (Section 3.5.5)
// ---------------------------------------------------------------------------

function AuthorityInline({
  authRef,
  entry,
  fieldName,
  telemetry,
  defaultExpanded = false,
}: {
  authRef: AuthorityRef;
  entry: AuthorityRegistryEntry | undefined;
  fieldName: string;
  telemetry?: TelemetryEmitter;
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  function handleExpand() {
    setExpanded(!expanded);
    if (!expanded) {
      telemetry?.authorityExpanded(fieldName, authRef.authority_ref);
    }
  }

  // Style by authority type (Section 3.5.4)
  const badgeStyle = {
    requirement: 'font-bold',
    guidance: 'font-normal',
    best_practice: 'italic',
    local_policy: 'font-normal',
  }[authRef.type];

  const isOverlay = authRef.relationship === 'overlay';

  return (
    <div className={cn('rounded border border-border p-2', isOverlay && 'ml-3')}>
      <button
        type="button"
        className="w-full text-left"
        onClick={handleExpand}
        aria-expanded={expanded}
      >
        <span className={cn('text-xs text-foreground', badgeStyle)}>
          {entry ? `${entry.document_id} ${entry.section}` : authRef.authority_ref}
          {entry?.requirement_id && ` — ${entry.requirement_id}`}
        </span>
        {isOverlay && authRef.overlay_note && (
          <span className="ml-1 text-[10px] text-muted-foreground">
            (Center/Program Overlay)
          </span>
        )}
      </button>

      {expanded && entry && (
        <div className="mt-2 space-y-1.5 border-t border-border pt-2 text-[11px]">
          {/* Verbatim excerpt — visually distinct (Section 3.5.5 Rule 1) */}
          {entry.verbatim_excerpt && (
            <div>
              <span className="font-semibold text-foreground">Standard text: </span>
              <span className="font-medium text-foreground">
                &ldquo;{entry.verbatim_excerpt}&rdquo;
              </span>
            </div>
          )}

          {/* BoundState summary — visually subordinate (Section 3.5.5 Rule 2) */}
          <div>
            <span className="font-semibold text-muted-foreground">BoundState summary: </span>
            <span className="text-muted-foreground">{entry.boundstate_summary}</span>
          </div>

          {/* Interpretation — labeled, subordinate (Section 3.5.5 Rule 3) */}
          {entry.interpretation && (
            <div>
              <span className="font-semibold text-muted-foreground">BoundState interpretation: </span>
              <span className="text-muted-foreground/80">{entry.interpretation}</span>
            </div>
          )}

          {/* Legal disclaimer for derived summaries (Section 3.5.5 Rule 6) */}
          {entry.source_type === 'derived_summary' && (
            <div className="rounded bg-muted/60 px-2 py-1 text-[10px] text-muted-foreground">
              {entry.legal_disclaimer}
            </div>
          )}

          {/* Last verified date (Section 3.5.5 Rule 5) */}
          <div className="text-[10px] text-muted-foreground">
            Last verified: {entry.last_verified}
            {entry.page_ref && ` | ${entry.page_ref}`}
          </div>
        </div>
      )}
    </div>
  );
}
