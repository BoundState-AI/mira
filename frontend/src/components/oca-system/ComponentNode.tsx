/**
 * ComponentNode — Custom React Flow node for OCA system components.
 * Shows archetype icon, label, status badge, mechanism abbreviations,
 * zone indicators, and ports.
 *
 * BS-SPEC-OCA-002-REV0 §7.1
 */

import { memo, useState } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  Collapsible, CollapsibleContent, CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  ChevronDown, AlertTriangle, CircleDot, Flame, Filter, Gauge,
  Pipette, Box, Disc, Wrench, Thermometer, Circle, Cable, Pencil,
} from 'lucide-react';
import { getOcaMechanismField } from '@/lib/guidance/oca-pack';
import type { SystemComponent } from '@/lib/oca-system-api';
import { ZONE_COLORS, ZONE_LABELS } from '@/lib/oca-system-api';

// Icon map for archetypes
const ARCHETYPE_ICONS: Record<string, React.ReactNode> = {
  valve: <Gauge className="h-4 w-4" />,
  regulator: <Gauge className="h-4 w-4" />,
  line: <Pipette className="h-4 w-4" />,
  filter: <Filter className="h-4 w-4" />,
  fitting: <CircleDot className="h-4 w-4" />,
  pressure_vessel: <Box className="h-4 w-4" />,
  relief_valve: <Flame className="h-4 w-4" />,
  check_valve: <Disc className="h-4 w-4" />,
  orifice: <Circle className="h-4 w-4" />,
  heat_exchanger: <Thermometer className="h-4 w-4" />,
  gasket: <CircleDot className="h-4 w-4" />,
  flex_hose: <Cable className="h-4 w-4" />,
};

const STATUS_SURFACES: Record<string, string> = {
  green: 'border-emerald-400/70 bg-[radial-gradient(circle_at_top_left,_rgba(16,185,129,0.18),_transparent_34%),linear-gradient(160deg,_rgba(10,20,34,0.98),_rgba(8,16,28,0.98))]',
  yellow: 'border-amber-400/80 bg-[radial-gradient(circle_at_top_left,_rgba(245,158,11,0.18),_transparent_34%),linear-gradient(160deg,_rgba(16,18,28,0.98),_rgba(10,12,22,0.98))]',
  red: 'border-red-400/80 bg-[radial-gradient(circle_at_top_left,_rgba(239,68,68,0.22),_transparent_34%),linear-gradient(160deg,_rgba(22,10,16,0.98),_rgba(14,10,18,0.98))]',
  pending: 'border-slate-500/80 bg-[radial-gradient(circle_at_top_left,_rgba(148,163,184,0.16),_transparent_34%),linear-gradient(160deg,_rgba(23,31,47,0.98),_rgba(15,23,38,0.98))]',
};

const STATUS_RAILS: Record<string, string> = {
  green: 'bg-emerald-400',
  yellow: 'bg-amber-400',
  red: 'bg-red-400',
  pending: 'bg-slate-400',
};

const STATUS_BADGE_COLORS: Record<string, string> = {
  green: 'bg-emerald-600 text-white',
  yellow: 'bg-amber-500 text-black',
  red: 'bg-red-600 text-white',
  pending: 'bg-gray-600 text-white',
};

export interface ComponentNodeData {
  component: SystemComponent;
  onInspect?: (componentId: string) => void;
  onEdit?: (componentId: string) => void;
}

function ComponentNode({ data, selected }: NodeProps & { data: ComponentNodeData }) {
  const { component, onInspect, onEdit } = data;
  const [drawerOpen, setDrawerOpen] = useState(false);

  const statusClass = STATUS_SURFACES[component.overall_status] || STATUS_SURFACES.pending;
  const railClass = STATUS_RAILS[component.overall_status] || STATUS_RAILS.pending;
  const badgeClass = STATUS_BADGE_COLORS[component.overall_status] || STATUS_BADGE_COLORS.pending;

  const hasInputPort = component.archetype !== 'gasket';
  const hasOutputPort = component.archetype !== 'gasket';
  const showFooter = Boolean(onEdit) || (Boolean(onInspect) && component.overall_status !== 'pending');

  return (
    <div
      data-testid={`component-node-${component.component_id}`}
      className={[
        'relative overflow-hidden rounded-2xl border-2 text-slate-50 shadow-[0_18px_40px_-28px_rgba(15,23,42,0.92)]',
        'min-w-[250px] max-w-[290px] transition-all duration-150',
        statusClass,
        selected ? 'ring-2 ring-sky-300/90 ring-offset-2 ring-offset-background' : '',
      ].join(' ')}
    >
      <div className={`h-1.5 w-full ${railClass}`} />

      {/* Input port */}
      {hasInputPort && (
        <Handle
          type="target"
          position={Position.Left}
          data-testid={`component-input-${component.component_id}`}
          className="!h-5 !w-5 !border-[3px] !border-slate-950 !bg-sky-400 !shadow-[0_0_0_4px_rgba(125,211,252,0.18)]"
        />
      )}

      {/* Header */}
      <div className="border-b border-white/10 px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="rounded-full bg-white/8 p-2 text-slate-100">
            {ARCHETYPE_ICONS[component.archetype] || <Wrench className="h-4 w-4" />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-lg font-semibold leading-none">
              {component.label || component.archetype}
            </div>
            <div className="mt-1 text-[10px] uppercase tracking-[0.22em] text-slate-300/80">
              {component.archetype.replace(/_/g, ' ')}
            </div>
          </div>
          <Badge className={`${badgeClass} px-1.5 py-0.5 text-[10px] shadow-sm`}>
            {component.overall_status === 'pending' ? '—' : `${component.highest_rating}/4`}
          </Badge>
        </div>
      </div>

      <div className="space-y-3 px-4 py-3">
        <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.2em] text-slate-300/70">
          <span>Status</span>
          <span className="capitalize">{component.overall_status}</span>
        </div>

        {/* Mechanism badges */}
        {component.credible_mechanisms.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {component.credible_mechanisms.map((abbr) => {
              const guidance = getOcaMechanismField(abbr);
              const badge = (
                <Badge
                  key={abbr}
                  variant="outline"
                  className="border-white/15 bg-white/6 px-1.5 py-0 text-[9px] font-mono text-slate-100"
                >
                  {abbr}
                </Badge>
              );

              if (!guidance) {
                return badge;
              }

              return (
                <Tooltip key={abbr}>
                  <TooltipTrigger asChild>
                    {badge}
                  </TooltipTrigger>
                  <TooltipContent className="max-w-64">
                    <div className="space-y-1">
                      <div className="text-xs font-semibold">{guidance.label}</div>
                      <div className="text-[11px] leading-relaxed text-muted-foreground">
                        {guidance.what}
                      </div>
                    </div>
                  </TooltipContent>
                </Tooltip>
              );
            })}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-white/12 bg-black/10 px-3 py-2 text-[10px] text-slate-300/70">
            No credible mechanisms yet. Run assessment after defining materials and topology.
          </div>
        )}

        {/* Zone indicators */}
        {component.zones.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {component.zones.map((zone) => (
              <Badge
                key={zone}
                variant="outline"
                className="gap-1 border-white/15 bg-white/6 px-1.5 py-0 text-[9px] text-slate-100"
              >
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ backgroundColor: ZONE_COLORS[zone] }}
                />
                {ZONE_LABELS[zone].replace(' Zone', '')}
              </Badge>
            ))}
          </div>
        )}

        {/* Unconnected warning */}
        {!component.connected && component.archetype !== 'gasket' && (
          <div className="flex items-center gap-2 rounded-xl border border-amber-300/25 bg-amber-400/10 px-3 py-2 text-amber-200">
            <AlertTriangle className="h-4 w-4" />
            <span className="text-xs">Unconnected</span>
          </div>
        )}

        {/* Materials summary */}
        {component.materials.length > 0 && (
          <div className="space-y-1">
            <div className="text-[10px] uppercase tracking-[0.2em] text-slate-300/70">
              Wetted Materials
            </div>
            {component.materials.slice(0, 2).map((ms, index) => (
              <div key={index} className="truncate text-[11px] text-slate-200/88">
                <span className="text-slate-400">{ms.slot_name}:</span> {ms.material.material_name}
              </div>
            ))}
            {component.materials.length > 2 && (
              <div className="text-[10px] text-slate-300/70">
                +{component.materials.length - 2} more materials
              </div>
            )}
          </div>
        )}
      </div>

      {/* Assumption drawer toggle */}
      {component.inferred_facts.length > 0 && (
        <Collapsible open={drawerOpen} onOpenChange={setDrawerOpen}>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="h-7 w-full rounded-none border-t border-white/10 text-[10px] text-slate-200 hover:bg-white/6 hover:text-white">
              <ChevronDown className={`h-3 w-3 transition-transform ${drawerOpen ? 'rotate-180' : ''}`} />
              Assumptions ({component.inferred_facts.length})
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="max-h-32 space-y-1 overflow-y-auto border-t border-white/10 bg-black/10 px-3 py-2">
              {component.inferred_facts.map((fact) => (
                <div key={fact.fact_id} className="border-l-2 border-sky-400/50 pl-2 text-[9px]">
                  <div className="flex items-center gap-1">
                    <span className="font-medium text-slate-100">{fact.fact_name}</span>
                    <Badge variant="outline" className="border-white/15 bg-white/5 px-0.5 py-0 text-[7px] text-slate-200">
                      {fact.source}
                    </Badge>
                    <Badge variant="outline" className="border-white/15 bg-white/5 px-0.5 py-0 text-[7px] text-slate-200">
                      {fact.confidence}
                    </Badge>
                  </div>
                  <div className="text-slate-300/75">{fact.explanation}</div>
                  {fact.missing_assumptions.length > 0 && (
                    <div className="text-[8px] text-amber-300">
                      Missing: {fact.missing_assumptions.join(', ')}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </CollapsibleContent>
        </Collapsible>
      )}

      {showFooter && (
        <div className="grid grid-cols-2 border-t border-white/10">
          <Button
            variant="ghost"
            size="sm"
            data-testid={`component-edit-${component.component_id}`}
            className="h-8 rounded-none text-[10px] text-slate-200 hover:bg-white/6 hover:text-white"
            onClick={() => onEdit?.(component.component_id)}
          >
            <Pencil className="mr-1.5 h-3 w-3" />
            Edit
          </Button>
          <Button
            variant="ghost"
            size="sm"
            data-testid={`component-inspect-${component.component_id}`}
            className="h-8 rounded-none border-l border-white/10 text-[10px] text-slate-200 hover:bg-white/6 hover:text-white"
            onClick={() => onInspect?.(component.component_id)}
            disabled={component.overall_status === 'pending'}
          >
            Inspect Path
          </Button>
        </div>
      )}

      {/* Output port */}
      {hasOutputPort && (
        <Handle
          type="source"
          position={Position.Right}
          data-testid={`component-output-${component.component_id}`}
          className="!h-5 !w-5 !border-[3px] !border-slate-950 !bg-emerald-400 !shadow-[0_0_0_4px_rgba(74,222,128,0.18)]"
        />
      )}
    </div>
  );
}

export default memo(ComponentNode);
