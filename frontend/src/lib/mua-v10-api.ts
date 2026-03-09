const API_BASE = '/api/mua/v10';

function getApiBases(): string[] {
  // In local development, always use the Vite proxy path to avoid stale
  // cross-origin targets (for example, old 8010 overrides) and CORS drift.
  if (import.meta.env.DEV) {
    return [API_BASE];
  }

  const envBase = import.meta.env.VITE_MUA_V10_API_BASE as string | undefined;
  const configured = (envBase || '').trim().replace(/\/+$/, '');
  const candidates = configured ? [configured, API_BASE] : [API_BASE];

  return [...new Set(candidates)];
}

export type MaterialClass = 'metal' | 'nonmetallic';

export interface MuaV10ClassifyRowRequest {
  maptis_code?: string;
  material_designation?: string;
  material_class?: MaterialClass;
  media: string;
  environment?: 'habitable' | 'non-habitable';
  o2_percent?: number;
  batch_verified?: boolean;
  ratings: Record<string, string | null | undefined>;
  part_numbers?: string[];
  part_count?: number;
  project?: string;
  system?: string;
  material_specification?: string;
  pressure?: string;
  temperature?: string;
}

export interface MuaV10ClassifierResult {
  issue_key: string;
  rating: string;
  flag_type: string | null;
  mua_type: string;
  category: 'I' | 'II' | null;
  automatable: boolean;
  screening_applicable: boolean;
  hazard_applies: boolean | null;
  classification_reason: string;
  confidence: number;
  precedent?: {
    issue: string;
    media_category: string;
    material_class: string;
    alloy_family: string;
    total_count: number;
    approved_count: number;
    rejected_count: number;
    distinct_materials: number;
    most_common_category: string;
  } | null;
  precedent_ring?: string | null;
  evidence_bundle?: {
    issue: string;
    rating: string;
    mua_type: string;
    material_class: string;
    media: string;
    precedent_summary?: {
      issue: string;
      media_category: string;
      material_class: string;
      alloy_family: string;
      total_count: number;
      approved_count: number;
      rejected_count: number;
      distinct_materials: number;
      most_common_category: string;
    } | null;
    precedent_ring?: string | null;
    exemplars?: Array<{
      mua_number: string;
      material_name: string;
      alloy_family: string;
      media_category: string;
      determination: string;
      category: string;
      rationale_text: string;
      confidence: number;
      match_ring: string;
      match_score: number;
    }>;
    phrases?: Array<{
      phrase: string;
      mua_number: string;
      score: number;
    }>;
    evidence_hash?: string;
  } | null;
  synthesis?: {
    rationale: string;
    disposition: string;
    claims?: Array<{
      text: string;
      source_mua: string;
      source_type: string;
      confidence: number;
    }>;
    suggested_elements?: string[];
    model_id: string;
    prompt_version: string;
    template_fallback: boolean;
  } | null;
}

export interface MuaV10Form {
  issue: string;
  rating: string;
  category: string;
  rationale: string;
  disposition: string;
}

export interface MuaV10PipelineResult {
  maptis_code: string;
  material_designation: string;
  material_class: MaterialClass;
  total_flags: number;
  automatable_count: number;
  human_required_count: number;
  no_mua_needed_count: number;
  classifications: MuaV10ClassifierResult[];
  forms: MuaV10Form[];
  human_required_reasons: string[];
}

export interface ProcessSingleRequest {
  material_text?: string;
  maptis_code?: string;
  material_class?: MaterialClass;
  media: string;
  environment?: 'habitable' | 'non-habitable';
  o2_percent?: number;
  batch_verified?: boolean;
  ratings: Record<string, string | null | undefined>;
  part_numbers?: string[];
  part_count?: number;
  project?: string;
  system?: string;
  material_specification?: string;
  pressure?: string;
  temperature?: string;
}

export interface ProcessSingleResponse {
  status: 'ok' | 'needs_resolution';
  session_id?: string | null;
  candidates?: Array<Record<string, unknown>>;
  material_resolution?: {
    input_text: string;
    status: string;
    maptis_code?: string;
    resolved_name?: string;
    family?: string;
    material_class?: string;
    message?: string;
  };
  pipeline_result?: MuaV10PipelineResult;
}

export interface ProcessMiulRowResult {
  row_index: number;
  line_number: string;
  part_number: string;
  maptis_code: string;
  material_designation: string;
  media: string;
  environment: string;
  ratings: Record<string, string>;
  pipeline_result: MuaV10PipelineResult;
}

export interface ProcessMiulResponse {
  filename: string;
  total_rows: number;
  processed_rows: number;
  skipped_rows: number;
  skipped_reasons: Record<string, number>;
  results: ProcessMiulRowResult[];
}

export interface FinalizeAction {
  issue: string;
  action: 'approve' | 'edit' | 'reject';
  rationale?: string;
  disposition?: string;
  comment?: string;
}

export interface FinalizeRequest extends MuaV10ClassifyRowRequest {
  session_id?: string;
  actions: FinalizeAction[];
}

function parseJsonSafely(text: string): unknown {
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return {};
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const bases = getApiBases();
  let lastError: Error | null = null;

  for (let i = 0; i < bases.length; i += 1) {
    const base = bases[i];
    try {
      const response = await fetch(`${base}${path}`, init);
      const text = await response.text();
      const payload = parseJsonSafely(text) as Record<string, unknown>;

      if (!response.ok) {
        const message = String(payload?.detail || payload?.error || `Request failed with status ${response.status}`);
        // Retry on 404 with next base; otherwise fail fast.
        if (response.status === 404 && i < bases.length - 1) {
          lastError = new Error(message);
          continue;
        }
        throw new Error(message);
      }

      return payload as T;
    } catch (err) {
      lastError = err instanceof Error ? err : new Error('Network request failed');
      if (i === bases.length - 1) {
        throw lastError;
      }
    }
  }

  throw lastError || new Error('Request failed');
}

export function pingMuaV10(): Promise<{ status: string; domain: string }> {
  return request('/ping');
}

export function classifyMuaV10Row(payload: MuaV10ClassifyRowRequest): Promise<MuaV10PipelineResult> {
  return request('/classify-row', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function processSingleMaterial(payload: ProcessSingleRequest): Promise<ProcessSingleResponse> {
  try {
    return await request('/process-single', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const routeMiss = message.includes('404') || message.toLowerCase().includes('not found');
    if (!routeMiss) {
      throw err;
    }

    // Compatibility fallback for backend revisions that do not expose /process-single.
    const pipeline = await classifyMuaV10Row({
      maptis_code: payload.maptis_code,
      material_designation: payload.material_text,
      material_class: payload.material_class,
      media: payload.media,
      environment: payload.environment,
      o2_percent: payload.o2_percent,
      batch_verified: payload.batch_verified,
      ratings: payload.ratings,
      part_numbers: payload.part_numbers,
      part_count: payload.part_count,
      project: payload.project,
      system: payload.system,
      material_specification: payload.material_specification,
      pressure: payload.pressure,
      temperature: payload.temperature,
    });

    return {
      status: 'ok',
      session_id: null,
      material_resolution: {
        input_text: payload.material_text || '',
        status: 'resolved',
        maptis_code: pipeline.maptis_code,
        resolved_name: pipeline.material_designation,
        material_class: pipeline.material_class,
      },
      pipeline_result: pipeline,
    };
  }
}

export function finalizeMua(payload: FinalizeRequest): Promise<{ status: string; session_id?: string; finalized_count: number; forms: MuaV10Form[] }> {
  return request('/finalize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function processMuaV10MiulWorkbook(
  file: File,
  options?: {
    media_override?: string;
    environment_override?: string;
    project?: string;
    system?: string;
    max_rows?: number;
  },
): Promise<ProcessMiulResponse> {
  const bases = getApiBases();
  let lastError: Error | null = null;

  for (let i = 0; i < bases.length; i += 1) {
    const base = bases[i];
    try {
      const formData = new FormData();
      formData.append('file', file);
      if (options?.media_override) formData.append('media_override', options.media_override);
      if (options?.environment_override) formData.append('environment_override', options.environment_override);
      if (options?.project) formData.append('project', options.project);
      if (options?.system) formData.append('system', options.system);
      if (typeof options?.max_rows === 'number') formData.append('max_rows', String(options.max_rows));

      const response = await fetch(`${base}/process-miul`, {
        method: 'POST',
        body: formData,
      });

      const text = await response.text();
      const json = parseJsonSafely(text) as Record<string, unknown>;

      if (!response.ok) {
        const message = String(json?.detail || json?.error || `Request failed with status ${response.status}`);
        if (response.status === 404 && i < bases.length - 1) {
          lastError = new Error(message);
          continue;
        }
        throw new Error(message);
      }

      return json as ProcessMiulResponse;
    } catch (err) {
      lastError = err instanceof Error ? err : new Error('Failed to process MIUL workbook');
      if (i === bases.length - 1) {
        throw lastError;
      }
    }
  }

  throw lastError || new Error('Failed to process MIUL workbook');
}

export interface GenerateDocxRequest extends MuaV10ClassifyRowRequest {
  rationale_override?: string;
  disposition_override?: string;
  session_id?: string;
  issue?: string;
}

export async function generateMuaDocx(payload: GenerateDocxRequest): Promise<Blob> {
  const bases = getApiBases();
  let lastError: Error | null = null;

  for (let i = 0; i < bases.length; i += 1) {
    const base = bases[i];
    try {
      const response = await fetch(`${base}/generate-docx`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const text = await response.text();
        const json = parseJsonSafely(text) as Record<string, unknown>;
        const message = String(
          json?.detail || json?.error || `Failed to generate .docx (${response.status})`,
        );

        if (response.status === 404 && i < bases.length - 1) {
          lastError = new Error(message);
          continue;
        }
        throw new Error(message);
      }

      return response.blob();
    } catch (err) {
      lastError = err instanceof Error ? err : new Error('Failed to generate .docx');
      if (i === bases.length - 1) {
        throw lastError;
      }
    }
  }

  throw lastError || new Error('Failed to generate .docx');
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
