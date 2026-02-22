import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import type { MatchmakerSession } from '@/lib/matchmaker-api';

interface MaterialInputProps {
  session: MatchmakerSession | null;
  creating: boolean;
  importing: boolean;
  onCreate: (payload: {
    material: string;
    application_description: string;
    deviation_type: 'material_selection' | 'manufacturing_nonconformance';
    environment: {
      o2_percent: number;
      pressure_psia: number;
      temp_min_f: number;
      temp_max_f: number;
      medium: string;
      location: string;
      application: string;
    };
  }) => Promise<void>;
  onImportMiul: (file: File) => Promise<void>;
}

export default function MaterialInput({ session, creating, importing, onCreate, onImportMiul }: MaterialInputProps) {
  const [material, setMaterial] = useState('');
  const [application, setApplication] = useState('');
  const [medium, setMedium] = useState('AIR');
  const [location, setLocation] = useState('habitable');
  const [o2Percent, setO2Percent] = useState('21');
  const [pressure, setPressure] = useState('14.7');
  const [tempMin, setTempMin] = useState('60');
  const [tempMax, setTempMax] = useState('85');
  const [deviationType, setDeviationType] = useState<'material_selection' | 'manufacturing_nonconformance'>('material_selection');

  const loadedSessionId = session?.session_id || '';
  const loadedMaterial = String(session?.material_input || session?.material_resolution?.resolved_name || '').trim();
  const loadedApplication = String(session?.application_description || session?.environment?.application || '').trim();
  const loadedMedium = String(session?.environment?.medium || 'AIR').trim() || 'AIR';
  const loadedLocation = String(session?.environment?.location || 'habitable').trim() || 'habitable';
  const loadedO2 = String(session?.environment?.o2_percent ?? 21);
  const loadedPressure = String(session?.environment?.pressure_psia ?? 14.7);
  const loadedTempMin = String(session?.environment?.temp_min_f ?? 60);
  const loadedTempMax = String(session?.environment?.temp_max_f ?? 85);
  const loadedDeviationType: 'material_selection' | 'manufacturing_nonconformance' = session?.nonconformance_redirected
    ? 'manufacturing_nonconformance'
    : 'material_selection';

  useEffect(() => {
    if (!loadedSessionId) return;
    setMaterial(loadedMaterial);
    setApplication(loadedApplication);
    setMedium(loadedMedium);
    setLocation(loadedLocation);
    setO2Percent(loadedO2);
    setPressure(loadedPressure);
    setTempMin(loadedTempMin);
    setTempMax(loadedTempMax);
    setDeviationType(loadedDeviationType);
  }, [
    loadedSessionId,
    loadedMaterial,
    loadedApplication,
    loadedMedium,
    loadedLocation,
    loadedO2,
    loadedPressure,
    loadedTempMin,
    loadedTempMax,
    loadedDeviationType,
  ]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!material.trim()) return;

    await onCreate({
      material: material.trim(),
      application_description: application.trim(),
      deviation_type: deviationType,
      environment: {
        o2_percent: Number(o2Percent),
        pressure_psia: Number(pressure),
        temp_min_f: Number(tempMin),
        temp_max_f: Number(tempMax),
        medium: medium.trim() || 'AIR',
        location: location.trim() || 'habitable',
        application: application.trim(),
      },
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>MUA V8 Session</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="space-y-1">
            <Label>Material</Label>
            <Input
              placeholder="AL 6061-T6"
              value={material}
              onChange={(e) => setMaterial(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label>Application</Label>
            <Textarea
              placeholder="Describe where and how this material is used"
              value={application}
              onChange={(e) => setApplication(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Medium</Label>
              <Input value={medium} onChange={(e) => setMedium(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>Location</Label>
              <Input value={location} onChange={(e) => setLocation(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>O2 %</Label>
              <Input type="number" step="0.1" value={o2Percent} onChange={(e) => setO2Percent(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>Pressure (psia)</Label>
              <Input type="number" step="0.1" value={pressure} onChange={(e) => setPressure(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>Temp Min F</Label>
              <Input type="number" value={tempMin} onChange={(e) => setTempMin(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>Temp Max F</Label>
              <Input type="number" value={tempMax} onChange={(e) => setTempMax(e.target.value)} />
            </div>
          </div>
          <div className="space-y-1">
            <Label>Deviation Type</Label>
            <select
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              value={deviationType}
              onChange={(e) => setDeviationType(e.target.value as 'material_selection' | 'manufacturing_nonconformance')}
            >
              <option value="material_selection">Material selection deviation</option>
              <option value="manufacturing_nonconformance">Manufacturing nonconformance (MRB/DR)</option>
            </select>
          </div>
          <div className="flex gap-2">
            <Button type="submit" disabled={creating || !material.trim()}>
              {creating ? 'Creating...' : 'Create Session'}
            </Button>
            <label className="inline-flex items-center">
              <input
                type="file"
                className="hidden"
                accept=".xlsx,.xls"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) onImportMiul(file);
                  e.currentTarget.value = '';
                }}
              />
              <span className="inline-flex h-10 cursor-pointer items-center rounded-md border px-4 text-sm">
                {importing ? 'Importing...' : 'Import MIUL'}
              </span>
            </label>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
