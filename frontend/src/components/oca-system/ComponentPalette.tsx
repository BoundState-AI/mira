/**
 * ComponentPalette — Drag source palette for OCA system builder.
 * Engineers drag component archetypes from here onto the canvas.
 *
 * BS-SPEC-OCA-002-REV0 §5.1
 */

import { type DragEvent } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Gauge, Pipette, Filter, CircleDot, Box, Flame, Disc, Circle,
  Thermometer, Cable, Wrench,
} from 'lucide-react';

interface PaletteItem {
  archetype: string;
  label: string;
  icon: React.ReactNode;
  description: string;
}

const PALETTE_ITEMS: PaletteItem[] = [
  { archetype: 'valve', label: 'Valve', icon: <Gauge className="h-4 w-4" />, description: 'Flow control with moving parts' },
  { archetype: 'regulator', label: 'Regulator', icon: <Gauge className="h-4 w-4" />, description: 'Pressure regulation' },
  { archetype: 'line', label: 'Line / Tube', icon: <Pipette className="h-4 w-4" />, description: 'Fluid conduit' },
  { archetype: 'filter', label: 'Filter', icon: <Filter className="h-4 w-4" />, description: 'Particle filtration' },
  { archetype: 'fitting', label: 'Fitting', icon: <CircleDot className="h-4 w-4" />, description: 'Mechanical connection' },
  { archetype: 'pressure_vessel', label: 'Vessel', icon: <Box className="h-4 w-4" />, description: 'Pressurized storage' },
  { archetype: 'relief_valve', label: 'Relief Valve', icon: <Flame className="h-4 w-4" />, description: 'Overpressure protection' },
  { archetype: 'check_valve', label: 'Check Valve', icon: <Disc className="h-4 w-4" />, description: 'One-way flow' },
  { archetype: 'orifice', label: 'Orifice', icon: <Circle className="h-4 w-4" />, description: 'Flow restriction' },
  { archetype: 'heat_exchanger', label: 'Heat Exchanger', icon: <Thermometer className="h-4 w-4" />, description: 'Thermal management' },
  { archetype: 'flex_hose', label: 'Flex Hose', icon: <Cable className="h-4 w-4" />, description: 'Flexible conduit' },
  { archetype: 'gasket', label: 'Gasket / O-Ring', icon: <CircleDot className="h-4 w-4" />, description: 'Sealing element' },
];

export default function ComponentPalette() {
  const onDragStart = (event: DragEvent, archetype: string, label: string) => {
    event.dataTransfer.setData('application/oca-archetype', archetype);
    event.dataTransfer.setData('application/oca-label', label);
    event.dataTransfer.effectAllowed = 'move';
  };

  return (
    <Card className="w-52 flex-shrink-0">
      <CardHeader className="py-2 px-3">
        <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Components
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <ScrollArea className="h-[calc(100vh-320px)]">
          <div className="space-y-0.5 p-2">
            {PALETTE_ITEMS.map((item) => (
              <div
                key={item.archetype}
                data-testid={`palette-${item.archetype}`}
                className="flex items-center gap-2 px-2 py-1.5 rounded cursor-grab hover:bg-accent/50 active:cursor-grabbing transition-colors"
                draggable
                onDragStart={(e) => onDragStart(e, item.archetype, item.label)}
              >
                {item.icon}
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium">{item.label}</div>
                  <div className="text-[9px] text-muted-foreground truncate">{item.description}</div>
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
