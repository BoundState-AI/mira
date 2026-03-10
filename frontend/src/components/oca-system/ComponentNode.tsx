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
import {
  Collapsible, CollapsibleContent, CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  ChevronDown, AlertTriangle, CircleDot, Flame, Filter, Gauge,
  Pipette, Box, Disc, Wrench, Thermometer, Circle, Cable,
} from 'lucide-react';
import type { SystemComponent, SystemZoneType } from '@/lib/oca-system-api';
import { ZONE_COLORS, ZONE_LABELS, MECHANISM_ABBREV } from '@/lib/oca-system-api';

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

const STATUS_COLORS: Record<string, string> = {
  green: 'border-emerald-500 bg-emerald-950/50',
  yellow: 'border-amber-500 bg-amber-950/50',
  red: 'border-red-500 bg-red-950/50',
  pending: 'border-gray-600 bg-gray-900/50',
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
}

function ComponentNode({ data }: NodeProps & { data: ComponentNodeData }) {
  const { component, onInspect } = data;
  const [drawerOpen, setDrawerOpen] = useState(false);

  const statusClass = STATUS_COLORS[component.overall_status] || STATUS_COLORS.pending;
  const badgeClass = STATUS_BADGE_COLORS[component.overall_status] || STATUS_BADGE_COLORS.pending;

  const hasInputPort = component.archetype !== 'gasket';
  const hasOutputPort = component.archetype !== 'gasket';

  return (
    <div className={`rounded-lg border-2 ${statusClass} min-w-[180px] max-w-[220px] shadow-lg`}>
      {/* Input port */}
      {hasInputPort && (
        <Handle
          type="target"
          position={Position.Left}
          className="!w-3 !h-3 !bg-blue-500 !border-2 !border-blue-300"
        />
      )}

      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border/50">
        {ARCHETYPE_ICONS[component.archetype] || <Wrench className="h-4 w-4" />}
        <span className="text-xs font-medium truncate flex-1">
          {component.label || component.archetype}
        </span>
        <Badge className={`${badgeClass} text-[9px] px-1 py-0`}>
          {component.overall_status === 'pending' ? '—' : component.highest_rating}
        </Badge>
      </div>

      {/* Mechanism badges */}
      {component.credible_mechanisms.length > 0 && (
        <div className="flex flex-wrap gap-0.5 px-2 py-1">
          {component.credible_mechanisms.map((abbr) => (
            <Badge
              key={abbr}
              variant="outline"
              className="text-[8px] px-1 py-0 font-mono"
            >
              {abbr}
            </Badge>
          ))}
        </div>
      )}

      {/* Zone indicators */}
      {component.zones.length > 0 && (
        <div className="flex gap-0.5 px-2 pb-1">
          {component.zones.map((zone) => (
            <div
              key={zone}
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: ZONE_COLORS[zone] }}
              title={ZONE_LABELS[zone]}
            />
          ))}
        </div>
      )}

      {/* Unconnected warning */}
      {!component.connected && component.archetype !== 'gasket' && (
        <div className="flex items-center gap-1 px-2 py-1 text-amber-400">
          <AlertTriangle className="h-3 w-3" />
          <span className="text-[9px]">Unconnected</span>
        </div>
      )}

      {/* Materials summary */}
      {component.materials.length > 0 && (
        <div className="px-2 pb-1">
          {component.materials.slice(0, 2).map((ms, i) => (
            <div key={i} className="text-[9px] text-muted-foreground truncate">
              {ms.slot_name}: {ms.material.material_name}
            </div>
          ))}
          {component.materials.length > 2 && (
            <div className="text-[9px] text-muted-foreground">
              +{component.materials.length - 2} more
            </div>
          )}
        </div>
      )}

      {/* Assumption drawer toggle */}
      {component.inferred_facts.length > 0 && (
        <Collapsible open={drawerOpen} onOpenChange={setDrawerOpen}>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="w-full h-5 text-[9px] rounded-none">
              <ChevronDown className={`h-3 w-3 transition-transform ${drawerOpen ? 'rotate-180' : ''}`} />
              Assumptions ({component.inferred_facts.length})
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="px-2 py-1 space-y-1 max-h-32 overflow-y-auto">
              {component.inferred_facts.map((fact) => (
                <div key={fact.fact_id} className="text-[8px] border-l-2 border-blue-500/50 pl-1">
                  <div className="flex items-center gap-1">
                    <span className="font-medium">{fact.fact_name}</span>
                    <Badge variant="outline" className="text-[7px] px-0.5 py-0">
                      {fact.source}
                    </Badge>
                    <Badge variant="outline" className="text-[7px] px-0.5 py-0">
                      {fact.confidence}
                    </Badge>
                  </div>
                  <div className="text-muted-foreground">{fact.explanation}</div>
                  {fact.missing_assumptions.length > 0 && (
                    <div className="text-amber-400 text-[7px]">
                      Missing: {fact.missing_assumptions.join(', ')}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </CollapsibleContent>
        </Collapsible>
      )}

      {/* Inspect button */}
      {onInspect && component.overall_status !== 'pending' && (
        <Button
          variant="ghost"
          size="sm"
          className="w-full h-5 text-[9px] rounded-none rounded-b-lg"
          onClick={() => onInspect(component.component_id)}
        >
          Inspect Path
        </Button>
      )}

      {/* Output port */}
      {hasOutputPort && (
        <Handle
          type="source"
          position={Position.Right}
          className="!w-3 !h-3 !bg-emerald-500 !border-2 !border-emerald-300"
        />
      )}
    </div>
  );
}

export default memo(ComponentNode);
