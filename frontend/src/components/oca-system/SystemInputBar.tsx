/**
 * SystemInputBar — Top bar for system-level inputs.
 * These propagate to every component on the canvas.
 *
 * BS-SPEC-OCA-002-REV0 §3
 */

import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Slider } from '@/components/ui/slider';
import { OCAHelpLabelBridge as OCAHelpLabel, OCAInlineHelpBridge as OCAInlineHelp } from '@/components/guidance';
import type { SystemInputs } from '@/lib/oca-system-api';

interface SystemInputBarProps {
  inputs: SystemInputs;
  onChange: (updates: Partial<SystemInputs>) => void;
}

export default function SystemInputBar({ inputs, onChange }: SystemInputBarProps) {
  return (
    <div className="flex flex-wrap items-end gap-3 p-3 bg-card rounded-lg border">
      {/* O2 Fraction */}
      <div className="space-y-1 w-28">
        <OCAHelpLabel
          fieldId="system_builder.o2_fraction"
          className="gap-1"
          labelClassName="text-[10px] text-muted-foreground"
        >
          O2 ({(inputs.o2_fraction * 100).toFixed(0)}%)
        </OCAHelpLabel>
        <Slider
          min={21} max={100} step={1}
          value={[inputs.o2_fraction * 100]}
          onValueChange={([v]) => onChange({ o2_fraction: v / 100 })}
        />
      </div>

      {/* Max Pressure */}
      <div className="space-y-1 w-24">
        <OCAHelpLabel
          fieldId="system_builder.system_pressure_max_psia"
          className="gap-1"
          labelClassName="text-[10px] text-muted-foreground"
        >
          Max psia
        </OCAHelpLabel>
        <Input
          type="number" min={0}
          value={inputs.system_pressure_max_psia}
          onChange={(e) => onChange({ system_pressure_max_psia: Number(e.target.value) })}
          className="h-7 text-xs"
        />
      </div>

      {/* Phase */}
      <div className="space-y-1 w-28">
        <OCAHelpLabel
          fieldId="system_builder.phase"
          className="gap-1"
          labelClassName="text-[10px] text-muted-foreground"
        >
          Phase
        </OCAHelpLabel>
        <Select value={inputs.phase} onValueChange={(v) => onChange({ phase: v })}>
          <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="gox">GOX</SelectItem>
            <SelectItem value="lox">LOX</SelectItem>
            <SelectItem value="enriched_air">Enriched Air</SelectItem>
            <SelectItem value="compressed_air">Compressed Air</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Oxygen Phase */}
      <div className="space-y-1 w-20">
        <OCAHelpLabel
          fieldId="system_builder.oxygen_phase"
          className="gap-1"
          labelClassName="text-[10px] text-muted-foreground"
        >
          State
        </OCAHelpLabel>
        <Select value={inputs.oxygen_phase} onValueChange={(v) => onChange({ oxygen_phase: v })}>
          <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="gas">Gas</SelectItem>
            <SelectItem value="liquid">Liquid</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Flow Rate */}
      <div className="space-y-1 w-24">
        <OCAHelpLabel
          fieldId="system_builder.design_flow_rate_m3_s"
          className="gap-1"
          labelClassName="text-[10px] text-muted-foreground"
        >
          Flow (m3/s)
        </OCAHelpLabel>
        <Input
          type="number" min={0} step={0.001}
          placeholder="—"
          value={inputs.design_flow_rate_m3_s ?? ''}
          onChange={(e) => onChange({ design_flow_rate_m3_s: e.target.value ? Number(e.target.value) : null })}
          className="h-7 text-xs"
        />
      </div>

      {/* Mission Phase */}
      <div className="space-y-1 w-28">
        <OCAHelpLabel
          fieldId="system_builder.mission_phase"
          className="gap-1"
          labelClassName="text-[10px] text-muted-foreground"
        >
          Mission
        </OCAHelpLabel>
        <Select value={inputs.mission_phase} onValueChange={(v) => onChange({ mission_phase: v })}>
          <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="ground_test">Ground Test</SelectItem>
            <SelectItem value="ascent">Ascent</SelectItem>
            <SelectItem value="on_orbit">On-Orbit</SelectItem>
            <SelectItem value="servicing">Servicing</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Cleanliness */}
      <div className="space-y-1 w-28">
        <OCAHelpLabel
          fieldId="system_builder.cleanliness_spec"
          className="gap-1"
          labelClassName="text-[10px] text-muted-foreground"
        >
          Cleaning Spec
        </OCAHelpLabel>
        <Input
          placeholder="e.g., Level 100"
          value={inputs.cleanliness_spec ?? ''}
          onChange={(e) => onChange({ cleanliness_spec: e.target.value || null })}
          className="h-7 text-xs"
        />
      </div>

      {/* Bi-directional flow */}
      <div className="flex items-center gap-1.5">
        <Switch
          checked={inputs.bi_directional_flow_risk}
          onCheckedChange={(v) => onChange({ bi_directional_flow_risk: v })}
          className="scale-75"
        />
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-muted-foreground">Bi-Dir Flow</span>
          <OCAInlineHelp
            fieldId="system_builder.bi_directional_flow_risk"
            className="h-3.5 w-3.5"
            iconClassName="h-3 w-3"
          />
        </div>
      </div>
    </div>
  );
}
