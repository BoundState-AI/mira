/**
 * SystemInputBar — Top bar for system-level inputs.
 * These propagate to every component on the canvas.
 *
 * BS-SPEC-OCA-002-REV0 §3
 */

import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Slider } from '@/components/ui/slider';
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
        <Label className="text-[10px] text-muted-foreground">O2 ({(inputs.o2_fraction * 100).toFixed(0)}%)</Label>
        <Slider
          min={21} max={100} step={1}
          value={[inputs.o2_fraction * 100]}
          onValueChange={([v]) => onChange({ o2_fraction: v / 100 })}
        />
      </div>

      {/* Max Pressure */}
      <div className="space-y-1 w-24">
        <Label className="text-[10px] text-muted-foreground">Max psia</Label>
        <Input
          type="number" min={0}
          value={inputs.system_pressure_max_psia}
          onChange={(e) => onChange({ system_pressure_max_psia: Number(e.target.value) })}
          className="h-7 text-xs"
        />
      </div>

      {/* Phase */}
      <div className="space-y-1 w-28">
        <Label className="text-[10px] text-muted-foreground">Phase</Label>
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
        <Label className="text-[10px] text-muted-foreground">State</Label>
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
        <Label className="text-[10px] text-muted-foreground">Flow (m3/s)</Label>
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
        <Label className="text-[10px] text-muted-foreground">Mission</Label>
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
        <Label className="text-[10px] text-muted-foreground">Cleaning Spec</Label>
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
        <Label className="text-[10px] text-muted-foreground">Bi-Dir Flow</Label>
      </div>
    </div>
  );
}
