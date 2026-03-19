import { useEffect, useMemo, useState } from 'react';
import { OCAHelpLabelBridge as OCAHelpLabel, OCAInlineHelpBridge as OCAInlineHelp } from '@/components/guidance';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import {
  Search, Save, Settings2, ShieldCheck,
} from 'lucide-react';
import type {
  ComponentArchetype,
  ComponentConfig,
  ComponentUpdateRequest,
  MaterialSlotValue,
  SystemComponent,
} from '@/lib/oca-system-api';
import { ZONE_LABELS } from '@/lib/oca-system-api';

type EditableConfigKey =
  | 'seal_type'
  | 'inner_diameter_mm'
  | 'length_m'
  | 'wall_thickness_mm'
  | 'micron_rating'
  | 'volume_liters'
  | 'bore_diameter_mm'
  | 'mawp_psia'
  | 'set_pressure_psia';

interface ConfigFieldDefinition {
  key: EditableConfigKey;
  label: string;
  kind: 'number' | 'text';
  placeholder?: string;
  step?: number;
  archetypes: ComponentArchetype[];
}

const CONFIG_FIELDS: ConfigFieldDefinition[] = [
  {
    key: 'seal_type',
    label: 'Seal Type',
    kind: 'text',
    placeholder: 'metal, PTFE, elastomer',
    archetypes: ['valve', 'regulator', 'relief_valve', 'check_valve', 'gasket', 'flex_hose'],
  },
  {
    key: 'inner_diameter_mm',
    label: 'Inner Diameter (mm)',
    kind: 'number',
    step: 0.1,
    placeholder: '12.7',
    archetypes: ['line', 'filter', 'flex_hose', 'heat_exchanger'],
  },
  {
    key: 'length_m',
    label: 'Length (m)',
    kind: 'number',
    step: 0.01,
    placeholder: '1.5',
    archetypes: ['line', 'flex_hose', 'heat_exchanger'],
  },
  {
    key: 'wall_thickness_mm',
    label: 'Wall Thickness (mm)',
    kind: 'number',
    step: 0.1,
    placeholder: '1.2',
    archetypes: ['line', 'pressure_vessel', 'flex_hose'],
  },
  {
    key: 'micron_rating',
    label: 'Micron Rating',
    kind: 'number',
    step: 1,
    placeholder: '10',
    archetypes: ['filter'],
  },
  {
    key: 'volume_liters',
    label: 'Volume (L)',
    kind: 'number',
    step: 0.01,
    placeholder: '0.5',
    archetypes: ['pressure_vessel', 'regulator'],
  },
  {
    key: 'bore_diameter_mm',
    label: 'Bore Diameter (mm)',
    kind: 'number',
    step: 0.01,
    placeholder: '1.6',
    archetypes: ['orifice'],
  },
  {
    key: 'mawp_psia',
    label: 'MAWP (psia)',
    kind: 'number',
    step: 1,
    placeholder: '3000',
    archetypes: ['pressure_vessel', 'regulator', 'valve', 'relief_valve'],
  },
  {
    key: 'set_pressure_psia',
    label: 'Set Pressure (psia)',
    kind: 'number',
    step: 1,
    placeholder: '2500',
    archetypes: ['relief_valve'],
  },
];

interface ComponentEditorSheetProps {
  component: SystemComponent | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (componentId: string, updates: ComponentUpdateRequest) => Promise<void>;
  onInspect?: (componentId: string) => void;
}

function formatMaterials(materials: MaterialSlotValue[]): string {
  return materials
    .map((item) => `${item.slot_name}: ${item.material.material_name}`)
    .join('\n');
}

function parseMaterials(input: string): MaterialSlotValue[] {
  return input
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const parts = line.split(/[:=]/, 2);
      const hasSlot = parts.length === 2;
      const slotName = hasSlot ? parts[0].trim() : index === 0 ? 'body' : `slot_${index + 1}`;
      const materialName = hasSlot ? parts[1].trim() : line.trim();
      if (!materialName) {
        throw new Error(`Missing material name on line ${index + 1}`);
      }
      return {
        slot_name: slotName || `slot_${index + 1}`,
        material: {
          material_name: materialName,
        },
      };
    });
}

function componentHelp(fieldId: string) {
  return `component_editor.${fieldId}`;
}

export default function ComponentEditorSheet({
  component,
  open,
  onOpenChange,
  onSave,
  onInspect,
}: ComponentEditorSheetProps) {
  const [label, setLabel] = useState('');
  const [materialsText, setMaterialsText] = useState('');
  const [configValues, setConfigValues] = useState<Partial<Record<EditableConfigKey, string>>>({});
  const [isRigidTubing, setIsRigidTubing] = useState(false);
  const [isMetallicFlexHose, setIsMetallicFlexHose] = useState(false);
  const [isAllMetalSeal, setIsAllMetalSeal] = useState(false);
  const [isMetallicPressureVessel, setIsMetallicPressureVessel] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const visibleFields = useMemo(
    () => CONFIG_FIELDS.filter((field) => component && field.archetypes.includes(component.archetype)),
    [component],
  );

  useEffect(() => {
    if (!component) {
      setLabel('');
      setMaterialsText('');
      setConfigValues({});
      setIsRigidTubing(false);
      setIsMetallicFlexHose(false);
      setIsAllMetalSeal(false);
      setIsMetallicPressureVessel(false);
      setSaveError(null);
      return;
    }

    setLabel(component.label);
    setMaterialsText(formatMaterials(component.materials));
    setConfigValues({
      seal_type: component.config.seal_type ?? '',
      inner_diameter_mm: component.config.inner_diameter_mm?.toString() ?? '',
      length_m: component.config.length_m?.toString() ?? '',
      wall_thickness_mm: component.config.wall_thickness_mm?.toString() ?? '',
      micron_rating: component.config.micron_rating?.toString() ?? '',
      volume_liters: component.config.volume_liters?.toString() ?? '',
      bore_diameter_mm: component.config.bore_diameter_mm?.toString() ?? '',
      mawp_psia: component.config.mawp_psia?.toString() ?? '',
      set_pressure_psia: component.config.set_pressure_psia?.toString() ?? '',
    });
    setIsRigidTubing(Boolean(component.is_rigid_metallic_tubing));
    setIsMetallicFlexHose(Boolean(component.is_metallic_flex_hose));
    setIsAllMetalSeal(Boolean(component.is_all_metal_seal));
    setIsMetallicPressureVessel(Boolean(component.is_metallic_pressure_vessel));
    setSaveError(null);
  }, [component]);

  const handleSave = async () => {
    if (!component) return;
    setSaveError(null);
    setSaving(true);

    try {
      const nextConfig: Partial<ComponentConfig> = {};
      for (const field of visibleFields) {
        const rawValue = configValues[field.key]?.trim() ?? '';
        nextConfig[field.key] = rawValue ? (field.kind === 'number' ? Number(rawValue) : rawValue) : null;
      }

      await onSave(component.component_id, {
        label: label.trim() || component.label,
        materials: parseMaterials(materialsText),
        config: nextConfig,
        is_rigid_metallic_tubing: isRigidTubing,
        is_metallic_flex_hose: isMetallicFlexHose,
        is_all_metal_seal: isAllMetalSeal,
        is_metallic_pressure_vessel: isMetallicPressureVessel,
      });
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : 'Unable to save component changes.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="sm:max-w-xl px-0">
        <SheetHeader className="px-6 pb-2">
          <SheetTitle className="flex items-center gap-2 text-left">
            <Settings2 className="h-4 w-4" />
            Component Details
          </SheetTitle>
        </SheetHeader>

        {component && (
          <ScrollArea className="h-[calc(100vh-96px)]">
            <div className="space-y-5 px-6 pb-6">
              <div className="rounded-xl border border-border/70 bg-muted/30 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-xs uppercase tracking-[0.22em] text-muted-foreground">
                      {component.archetype.replace(/_/g, ' ')}
                    </div>
                    <div className="mt-1 text-lg font-semibold text-foreground">
                      {component.label}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      Component ID: {component.component_id.slice(0, 8)}
                    </div>
                  </div>
                  <Badge variant="outline" className="capitalize">
                    {component.overall_status}
                  </Badge>
                </div>

                {component.zones.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1">
                    {component.zones.map((zone) => (
                      <Badge key={zone} variant="outline" className="text-[10px]">
                        {ZONE_LABELS[zone]}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>

              <div className="space-y-2">
                <OCAHelpLabel htmlFor="component-label" fieldId={componentHelp('label')}>
                  Label
                </OCAHelpLabel>
                <Input
                  id="component-label"
                  value={label}
                  onChange={(event) => setLabel(event.target.value)}
                  placeholder="Component label"
                />
              </div>

              <div className="space-y-2">
                <OCAHelpLabel htmlFor="component-materials" fieldId={componentHelp('materials')}>
                  Materials
                </OCAHelpLabel>
                <Textarea
                  id="component-materials"
                  value={materialsText}
                  onChange={(event) => setMaterialsText(event.target.value)}
                  className="min-h-28 font-mono text-xs"
                  placeholder={'body: 316L\nseat: PTFE'}
                />
                <p className="text-xs text-muted-foreground">
                  One slot per line. Use `slot: material`, for example `body: 316L`.
                </p>
              </div>

              {visibleFields.length > 0 && (
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="h-4 w-4 text-sky-500" />
                    <div className="text-sm font-medium">Configuration</div>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    {visibleFields.map((field) => (
                      <div key={field.key} className="space-y-2">
                        <OCAHelpLabel htmlFor={field.key} fieldId={componentHelp(field.key)}>
                          {field.label}
                        </OCAHelpLabel>
                        <Input
                          id={field.key}
                          type={field.kind}
                          step={field.step}
                          value={configValues[field.key] ?? ''}
                          placeholder={field.placeholder}
                          onChange={(event) => {
                            const value = event.target.value;
                            setConfigValues((current) => ({
                              ...current,
                              [field.key]: value,
                            }));
                          }}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="space-y-3">
                <div className="text-sm font-medium">MPR 53 Exemption Flags</div>
                <div className="space-y-2 rounded-xl border border-border/70 bg-muted/20 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex items-center gap-1.5">
                      <Label htmlFor="rigid-tubing" className="text-sm">Rigid metallic tubing</Label>
                      <OCAInlineHelp fieldId={componentHelp('is_rigid_metallic_tubing')} />
                    </span>
                    <Switch id="rigid-tubing" checked={isRigidTubing} onCheckedChange={setIsRigidTubing} />
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex items-center gap-1.5">
                      <Label htmlFor="metallic-flex" className="text-sm">Metallic flex hose</Label>
                      <OCAInlineHelp fieldId={componentHelp('is_metallic_flex_hose')} />
                    </span>
                    <Switch id="metallic-flex" checked={isMetallicFlexHose} onCheckedChange={setIsMetallicFlexHose} />
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex items-center gap-1.5">
                      <Label htmlFor="all-metal-seal" className="text-sm">All-metal seal</Label>
                      <OCAInlineHelp fieldId={componentHelp('is_all_metal_seal')} />
                    </span>
                    <Switch id="all-metal-seal" checked={isAllMetalSeal} onCheckedChange={setIsAllMetalSeal} />
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex items-center gap-1.5">
                      <Label htmlFor="metallic-vessel" className="text-sm">Metallic pressure vessel</Label>
                      <OCAInlineHelp fieldId={componentHelp('is_metallic_pressure_vessel')} />
                    </span>
                    <Switch
                      id="metallic-vessel"
                      checked={isMetallicPressureVessel}
                      onCheckedChange={setIsMetallicPressureVessel}
                    />
                  </div>
                </div>
              </div>

              {saveError && (
                <div className="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700">
                  {saveError}
                </div>
              )}

              <div className="flex items-center justify-between gap-2 pt-2">
                <Button
                  variant="outline"
                  className="gap-2"
                  onClick={() => component && onInspect?.(component.component_id)}
                  disabled={component.overall_status === 'pending'}
                >
                  <Search className="h-4 w-4" />
                  Inspect Path
                </Button>
                <Button className="gap-2" onClick={handleSave} disabled={saving}>
                  <Save className="h-4 w-4" />
                  {saving ? 'Saving...' : 'Save Changes'}
                </Button>
              </div>
            </div>
          </ScrollArea>
        )}
      </SheetContent>
    </Sheet>
  );
}
