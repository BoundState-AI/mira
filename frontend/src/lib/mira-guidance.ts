import galvanicRaw from '@/data/mira-guidance/galvanic-guidance.json';
import fractureRaw from '@/data/mira-guidance/fracture-guidance.json';
import h2Raw from '@/data/mira-guidance/h2-guidance.json';
import miulRaw from '@/data/mira-guidance/miul-guidance.json';
import muaRaw from '@/data/mira-guidance/mua-guidance.json';
import mpPlanRaw from '@/data/mira-guidance/mp-plan-guidance.json';

export type MiraModuleId = 'galvanic' | 'fracture' | 'h2' | 'miul' | 'mua' | 'mp_plan';

export interface MiraGuidanceEntry {
  id: string;
  label: string;
  what: string;
  why: string;
  guidance: string;
  source: string;
  module: MiraModuleId;
  section: string;
}

type RawGuidanceEntry = Record<string, unknown>;
type RawGuidanceDocument = Record<string, unknown> & { version?: number };

const rawGuidance = {
  galvanic: galvanicRaw as RawGuidanceDocument,
  fracture: fractureRaw as RawGuidanceDocument,
  h2: h2Raw as RawGuidanceDocument,
  miul: miulRaw as RawGuidanceDocument,
  mua: muaRaw as RawGuidanceDocument,
  mp_plan: mpPlanRaw as RawGuidanceDocument,
} as const;

const ENTRY_ID_KEYS = [
  'field_id',
  'id',
  'verdict_id',
  'classification_id',
  'finding_id',
  'mitigation_id',
  'concept_id',
  'flag_id',
  'type_id',
  'engine_id',
  'gap_type_id',
  'path_id',
  'step_id',
] as const;

function normalizeLookupKey(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

function getEntryId(entry: RawGuidanceEntry): string | null {
  for (const key of ENTRY_ID_KEYS) {
    const value = entry[key];
    if (typeof value === 'string' && value.trim()) {
      return value.trim();
    }
  }
  return null;
}

function toGuidanceEntry(
  module: MiraModuleId,
  section: string,
  entry: RawGuidanceEntry,
): MiraGuidanceEntry | null {
  const id = getEntryId(entry);
  if (!id) return null;

  const label = typeof entry.label === 'string' && entry.label.trim() ? entry.label.trim() : id;
  const what = typeof entry.what === 'string' ? entry.what.trim() : '';
  const why = typeof entry.why === 'string' ? entry.why.trim() : '';
  const guidance = typeof entry.guidance === 'string' ? entry.guidance.trim() : '';
  const source = typeof entry.source === 'string' ? entry.source.trim() : '';

  return {
    id,
    label,
    what,
    why,
    guidance,
    source,
    module,
    section,
  };
}

interface ModuleIndex {
  sections: Map<string, Map<string, MiraGuidanceEntry>>;
}

const moduleIndexes = new Map<MiraModuleId, ModuleIndex>();

for (const [module, document] of Object.entries(rawGuidance) as Array<[MiraModuleId, RawGuidanceDocument]>) {
  const sections = new Map<string, Map<string, MiraGuidanceEntry>>();

  for (const [section, rawEntries] of Object.entries(document)) {
    if (!Array.isArray(rawEntries)) continue;

    const sectionIndex = new Map<string, MiraGuidanceEntry>();
    for (const rawEntry of rawEntries) {
      if (!rawEntry || typeof rawEntry !== 'object') continue;
      const entry = toGuidanceEntry(module, section, rawEntry as RawGuidanceEntry);
      if (!entry) continue;

      sectionIndex.set(normalizeLookupKey(entry.id), entry);
      sectionIndex.set(normalizeLookupKey(entry.label), entry);
    }

    sections.set(section, sectionIndex);
  }

  moduleIndexes.set(module, { sections });
}

export function getMiraGuidanceEntry(
  module: MiraModuleId,
  section: string,
  idOrLabel: string | null | undefined,
): MiraGuidanceEntry | null {
  if (!idOrLabel) return null;
  return moduleIndexes.get(module)?.sections.get(section)?.get(normalizeLookupKey(idOrLabel)) ?? null;
}

export function getMiraInputGuidance(
  module: MiraModuleId,
  fieldId: string | null | undefined,
): MiraGuidanceEntry | null {
  return getMiraGuidanceEntry(module, 'inputs', fieldId);
}

export function getMiraModuleGuidance(module: MiraModuleId): RawGuidanceDocument {
  return rawGuidance[module];
}
