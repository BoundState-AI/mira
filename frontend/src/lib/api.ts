// API client for BoundState MIRA backend

const API_BASE = '/api';

export interface CompatibilityRequest {
  material_key: string;
  pressure: number;
  temperature: number;
  environment?: string;
  condition?: string;
}

export interface Evidence {
  source_id: string;
  location?: string | null;
  summary: string;
}

export interface CompatibilityResponse {
  classification: 'ok' | 'caution' | 'prohibited' | 'unknown';
  rationale: string;
  evidence: Evidence[];
  notes?: string;
  needs_clarification?: boolean;
  clarification_prompt?: string | null;
  available_conditions?: H2ConditionOption[];
  band_distribution?: Record<string, number> | null;
}

export interface H2ConditionOption {
  condition_name: string;
  hee_band: string;
  verdict_if_selected: string;
  evidence_count: number;
  source: string;
}

export interface H2ConditionLookupResponse {
  material_key: string;
  canonical_material?: string | null;
  has_matches: boolean;
  requires_clarification: boolean;
  match_type: string;
  available_conditions: H2ConditionOption[];
  band_distribution?: Record<string, number> | null;
  unresolved_condition_count?: number;
  notes?: string | null;
}

export interface H2ConditionAliasRecord {
  raw_key: string;
  raw_text: string;
  canonical_condition: string;
  display_label: string;
  is_condition: boolean;
  confidence?: number | null;
  resolver_provider?: string | null;
  resolver_model?: string | null;
  source_document?: string | null;
  material_name?: string | null;
  needs_review: boolean;
  human_verified: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface H2ConditionAliasListResponse {
  material_key?: string | null;
  unresolved_only: boolean;
  count: number;
  aliases: H2ConditionAliasRecord[];
}

export interface H2ConditionAliasVerifyRequest {
  raw_key: string;
  display_label: string;
  canonical_condition?: string | null;
  is_condition?: boolean;
  raw_text?: string | null;
  source_document?: string | null;
  material_name?: string | null;
}

export interface H2ConditionAliasVerifyResponse {
  status: string;
  cache_entries_cleared: number;
  alias: H2ConditionAliasRecord;
}

export interface SearchRequest {
  query: string;
  material_key?: string;
  test_class?: string;
}

export interface SearchHit {
  id: string;
  title: string;
  snippet: string;
  score: number;
  metadata?: Record<string, unknown>;
}

export interface SearchResponse {
  hits: SearchHit[];
  total: number;
}

export interface MIULRequest {
  program_id: string;
  material_keys: string[];
}

export interface MIULEntry {
  material: string;
  spec: string;
  status: string;
  notes: string;
}

export interface MIULResponse {
  success: boolean;
  message: string;
  entries: MIULEntry[];
}

export interface MUARequest {
  material_key: string;
  pressure: number;
  temperature: number;
  environment?: string;
  rationale_notes?: string;
}

export interface MUAResponse {
  id: string;
  material_key: string;
  classification: string;
  conditions: {
    pressure: number;
    temperature: number;
    environment?: string;
  };
  rationale: string;
  approval_text: string;
  generated_at: string;
}

export interface ForgeCompileRequest {
  database_url: string;
  app_name?: string;
  sample_rows_per_table?: number;
  persist_artifacts?: boolean;
  output_dir?: string;
  generate_bundle?: boolean;
  require_llm_refinement?: boolean;
  max_generated_questions?: number;
}

export interface ForgeCompilationSummary {
  app_name: string;
  database_url_redacted: string;
  dialect: string;
  schemas: string[];
  table_count: number;
  column_count: number;
  relationship_count: number;
  latent_relationship_count: number;
  generated_question_count: number;
}

export interface ForgeGeneratedBundle {
  root_dir: string;
  artifacts_dir: string;
  app_dir: string;
  backend_dir: string;
  frontend_dir: string;
  authority_pack_dir: string;
  bsms_pipeline_dir: string;
  lineage_dir: string;
  files: string[];
}

export interface ForgeCompileResponse {
  status: 'ok';
  summary: ForgeCompilationSummary;
  schema_manifest: Record<string, unknown>;
  semantic_map: Record<string, unknown>;
  relationship_graph: Record<string, unknown>;
  latent_relationships: Record<string, unknown>;
  data_quality_report: Record<string, unknown>;
  capabilities: Record<string, unknown>;
  question_map: Record<string, unknown>;
  scaffold_plan: Record<string, unknown>;
  bsms_pipeline: Record<string, unknown>;
  authority_pack: Record<string, unknown>;
  lineage_schema: Record<string, unknown>;
  warnings: string[];
  output_dir?: string | null;
  generated_bundle?: ForgeGeneratedBundle | null;
}

export interface ForgeCompileAcceptedResponse {
  status: 'accepted';
  job_id: string;
  status_url: string;
  poll_after_ms: number;
}

export interface ForgeCompileJobEvent {
  timestamp: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  stage: string;
  message: string;
  progress: number;
}

export interface ForgeCompileJobResponse {
  job_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  stage: string;
  message: string;
  progress: number;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
  result?: ForgeCompileResponse | null;
  events: ForgeCompileJobEvent[];
}

// Convert Fahrenheit to Kelvin
function fToK(f: number): number {
  return (f - 32) * 5/9 + 273.15;
}

export async function checkO2Compatibility(req: CompatibilityRequest): Promise<CompatibilityResponse> {
  const response = await fetch(`${API_BASE}/mira/o2/compatibility`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question: `Is ${req.material_key} compatible with oxygen?`,
      material_key: req.material_key,
      pressure_psia: req.pressure,
      temperature_k: fToK(req.temperature),
      phase: 'gox', // Default to gaseous oxygen
    }),
  });

  if (!response.ok) {
    throw new Error(`O2 compatibility check failed: ${response.statusText}`);
  }

  return response.json();
}

export async function checkH2Compatibility(req: CompatibilityRequest): Promise<CompatibilityResponse> {
  const conditionSuffix = req.condition?.trim()
    ? ` under ${req.condition.trim()} condition`
    : '';

  const response = await fetch(`${API_BASE}/mira/h2/compatibility`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question: `Is ${req.material_key} compatible with hydrogen${conditionSuffix}?`,
      material_key: req.material_key,
      pressure_psia: req.pressure,
      temperature_k: fToK(req.temperature),
      phase: 'gh2', // Default to gaseous hydrogen
      condition: req.condition?.trim() || undefined,
    }),
  });

  if (!response.ok) {
    throw new Error(`H2 compatibility check failed: ${response.statusText}`);
  }

  return response.json();
}

export async function getH2Conditions(materialKey: string): Promise<H2ConditionLookupResponse> {
  const response = await fetch(
    `${API_BASE}/mira/h2/conditions?material_key=${encodeURIComponent(materialKey)}`,
  );

  if (!response.ok) {
    throw new Error(`H2 condition lookup failed: ${response.statusText}`);
  }

  return response.json();
}

export async function getH2ConditionAliases(
  materialKey: string,
  unresolvedOnly: boolean = true,
  limit: number = 100,
): Promise<H2ConditionAliasListResponse> {
  const params = new URLSearchParams({
    material_key: materialKey,
    unresolved_only: String(unresolvedOnly),
    limit: String(limit),
  });
  const response = await fetch(`${API_BASE}/mira/h2/condition-aliases?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`H2 condition alias listing failed: ${response.statusText}`);
  }
  return response.json();
}

export async function verifyH2ConditionAlias(
  req: H2ConditionAliasVerifyRequest,
): Promise<H2ConditionAliasVerifyResponse> {
  const response = await fetch(`${API_BASE}/mira/h2/condition-aliases/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!response.ok) {
    throw new Error(`H2 condition alias verify failed: ${response.statusText}`);
  }
  return response.json();
}

export async function searchTestData(req: SearchRequest): Promise<SearchResponse> {
  const response = await fetch(`${API_BASE}/search/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question: req.query,
      material_key: req.material_key,
      environment: req.test_class,
    }),
  });

  if (!response.ok) {
    throw new Error(`Search failed: ${response.statusText}`);
  }

  const data = await response.json();

  // Transform backend response to frontend format
  const answer = data.answer || data;
  const evidence = answer.evidence || [];

  return {
    hits: evidence.map((e: Evidence, idx: number) => ({
      id: e.source_id || `hit-${idx}`,
      title: e.summary?.split(' | ')[0] || 'Material Record',
      snippet: e.summary || '',
      score: 0.9 - (idx * 0.05), // Approximate score based on position
      metadata: { location: e.location },
    })),
    total: evidence.length,
  };
}

export async function buildMIUL(req: MIULRequest): Promise<MIULResponse> {
  // TODO: Wire to actual MIUL endpoint when available
  await new Promise(r => setTimeout(r, 1000));

  return {
    success: true,
    message: `MIUL generated for program ${req.program_id}`,
    entries: req.material_keys.map((key, i) => ({
      material: key,
      spec: `SPEC-${1000 + i}`,
      status: ['Approved', 'Pending Review', 'Conditional'][i % 3],
      notes: 'Generated from material database',
    })),
  };
}

export async function generateMUA(req: MUARequest): Promise<MUAResponse> {
  // TODO: Wire to actual MUA endpoint when available
  await new Promise(r => setTimeout(r, 1200));

  return {
    id: `MUA-${Date.now()}`,
    material_key: req.material_key,
    classification: 'APPROVED',
    conditions: {
      pressure: req.pressure,
      temperature: req.temperature,
      environment: req.environment,
    },
    rationale: req.rationale_notes || 'Standard approval based on material database records.',
    approval_text: `MATERIAL USE APPROVAL\n\nMaterial: ${req.material_key}\nConditions: ${req.pressure} PSI @ ${req.temperature}°F\nEnvironment: ${req.environment || 'Standard'}\n\nThis material is approved for use under the specified conditions based on test data and engineering analysis.\n\nRationale: ${req.rationale_notes || 'N/A'}`,
    generated_at: new Date().toISOString(),
  };
}

// ============================================================================
// MUA v6 API - Precedent-Based Generation Pipeline
// ============================================================================

export type GenerationDecision = 'proceed' | 'warn' | 'review' | 'blocked';
export type OverlapStatus = 'within' | 'partial_overlap' | 'extrapolation' | 'insufficient_data';

export interface MuaV6EnvironmentSpec {
  description: string;
  o2_percent?: number;
  pressure_psia?: number;
  temperature_f?: number;
  is_habitable?: boolean;
}

export interface MuaV6PrecedentSearchRequest {
  material: string;
  environment?: MuaV6EnvironmentSpec;
  k?: number;
  family_filter?: string;
}

export interface MuaV6PrecedentSummary {
  mua_number: string | null;
  material_designation: string;
  material_family: string | null;
  environment: string | null;
  determination: string;
  rationale_preview: string;
  similarity_score: number;
  is_supporting: boolean;
  is_conflicting: boolean;
}

export interface MuaV6PrecedentSearchResponse {
  request_id: string;
  material_resolved: boolean;
  material_code: string | null;
  supporting_count: number;
  conflicting_count: number;
  supporting_precedents: MuaV6PrecedentSummary[];
  conflicting_precedents: MuaV6PrecedentSummary[];
}

export interface MuaV6GenerateRequest {
  material: string;
  environment: MuaV6EnvironmentSpec;
  k?: number;
  mode?: 'auto' | 'evaluate_only';
}

export interface MuaV6GenerateResponse {
  request_id: string;
  decision: GenerationDecision;
  confidence_score: number;
  envelope_status: OverlapStatus | null;
  test_data_currency: string | null;
  draft_text: string | null;
  precedents_used: string[];
  warnings: string[];
  review_factors: string[];
  blocking_factors: string[];
}

export interface MuaV6StatsResponse {
  faiss_index_size: number;
  material_resolver_available: boolean;
  logic_validator_available: boolean;
}

/**
 * Ping MUA v6 endpoint for health check.
 */
export async function muaV6Ping(): Promise<{ status: string; domain: string; version: string }> {
  const response = await fetch(`${API_BASE}/mua/v6/ping`);
  if (!response.ok) {
    throw new Error(`MUA v6 ping failed: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Search for MUA precedents matching material and environment.
 */
export async function muaV6SearchPrecedents(
  req: MuaV6PrecedentSearchRequest
): Promise<MuaV6PrecedentSearchResponse> {
  const response = await fetch(`${API_BASE}/mua/v6/precedents/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Precedent search failed: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Evaluate and optionally generate MUA draft using the v6 pipeline.
 */
export async function muaV6Generate(req: MuaV6GenerateRequest): Promise<MuaV6GenerateResponse> {
  const response = await fetch(`${API_BASE}/mua/v6/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `MUA generation failed: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Get MUA v6 system statistics.
 */
export async function muaV6Stats(): Promise<MuaV6StatsResponse> {
  const response = await fetch(`${API_BASE}/mua/v6/stats`);
  if (!response.ok) {
    throw new Error(`MUA v6 stats failed: ${response.statusText}`);
  }
  return response.json();
}

// ============================================================================
// MUA v6 Corpus-Based Draft Generation (5,650+ parsed MUAs)
// ============================================================================

export interface CorpusSearchRequest {
  material: string;
  environment?: string;
  application?: string;
  k?: number;
}

export interface CorpusPrecedent {
  mua_number: string;
  material_designation: string;
  material_family: string;
  environment: string;
  determination: string;
  issues: string[];
  rationale_preview: string;
  score: number;
}

export interface CorpusSearchResponse {
  request_id: string;
  total_found: number;
  precedents: CorpusPrecedent[];
}

export interface CorpusDraftRequest {
  material: string;
  environment: string;
  application?: string;
  o2_percent?: number;
  pressure_psia?: number;
  temperature_f?: number;
  is_habitable?: boolean;
  issues?: string[];
  k?: number;
}

export interface CorpusCitation {
  mua_number: string;
  material: string;
  environment: string;
  determination: string;
  relevance_score: number;
  rationale_excerpt: string;
}

export interface CorpusDraftResponse {
  request_id: string;
  material: string;
  environment: string;
  application: string;
  recommended_determination: string;
  confidence: number;
  coverage_assessment: string;
  issues_addressed: string[];
  gaps_identified: string[];
  warnings: string[];
  precedents_cited: CorpusCitation[];
  rationale: string;
}

export interface CorpusStatsResponse {
  status: string;
  total_records?: number;
  index_vectors?: number;
  embedding_model?: string;
  by_determination?: Record<string, number>;
  by_environment_type?: Record<string, number>;
  by_material_family?: Record<string, number>;
  message?: string;
}

/**
 * Search the parsed MUA corpus for precedents.
 */
export async function muaCorpusSearch(req: CorpusSearchRequest): Promise<CorpusSearchResponse> {
  const response = await fetch(`${API_BASE}/mua/v6/corpus/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Corpus search failed: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Generate MUA draft from corpus precedents.
 */
export async function muaCorpusDraft(req: CorpusDraftRequest): Promise<CorpusDraftResponse> {
  const response = await fetch(`${API_BASE}/mua/v6/corpus/draft`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Corpus draft generation failed: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Get corpus statistics.
 */
export async function muaCorpusStats(): Promise<CorpusStatsResponse> {
  const response = await fetch(`${API_BASE}/mua/v6/corpus/stats`);
  if (!response.ok) {
    throw new Error(`Corpus stats failed: ${response.statusText}`);
  }
  return response.json();
}

// ============================================================================
// NASA-STD-6016C Compliance Analysis API
// ============================================================================

export interface ComplianceAnalysisRequest {
  material_key: string;
  maptis_code?: number;
  pressure_psia: number;
  temperature_f: number;
  o2_percent?: number;
  is_hydrogen_service: boolean;
  is_habitable: boolean;
  hydrogen_phase?: string;
}

export interface GapSignalResponse {
  gap_id: string;
  gap_type: string;
  trigger: string;
  severity: string;
  description: string;
  evidence_count: number;
}

export interface OperationalConstraintResponse {
  constraint_id: string;
  parameter: string;
  limit_type: string;
  limit_value: string;
  description: string;
}

export interface MPRDeterminationResponse {
  mpr_number: number;
  mpr_section: string;
  mpr_title: string;
  applicability_status: string;
  compliance_status: string;
  compliance_basis: string;
  required_action: string;
  gap_count: number;
  constraint_count: number;
}

export interface ComplianceSummaryResponse {
  overall_status: string;
  status_rationale: string;
  total_materials: number;
  materials_compliant: number;
  materials_noncompliant: number;
  materials_requiring_mua: number;
  total_mprs_applicable: number;
  mprs_compliant: number;
  mprs_compliant_with_constraints: number;
  mprs_noncompliant: number;
  total_gaps: number;
  critical_gaps: number;
}

export interface ComplianceAnalysisResponse {
  request_id: string;
  material_key: string;
  environment_description: string;
  timestamp: string;
  summary: ComplianceSummaryResponse;
  determinations: MPRDeterminationResponse[];
  gaps: GapSignalResponse[];
  constraints: OperationalConstraintResponse[];
  run_duration_ms: number;
  warnings: string[];
  errors: string[];
}

export interface MPRListItem {
  mpr_number: number;
  mpr_id: string;
  section: string;
  title: string;
  applicability_triggers: string[];
  failure_modes: string[];
}

export interface MPRListResponse {
  standard_version: string;
  total_mprs: number;
  mprs: MPRListItem[];
}

/**
 * Analyze material compliance with NASA-STD-6016C.
 */
export async function analyzeCompliance(
  req: ComplianceAnalysisRequest
): Promise<ComplianceAnalysisResponse> {
  const response = await fetch(`${API_BASE}/compliance/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Compliance analysis failed: ${response.statusText}`);
  }

  return response.json();
}

/**
 * List all MPRs from NASA-STD-6016C.
 */
export async function listMPRs(): Promise<MPRListResponse> {
  const response = await fetch(`${API_BASE}/compliance/mprs`);
  if (!response.ok) {
    throw new Error(`Failed to load MPRs: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Compliance endpoint health check.
 */
export async function compliancePing(): Promise<{ status: string; domain: string }> {
  const response = await fetch(`${API_BASE}/compliance/ping`);
  if (!response.ok) {
    throw new Error(`Compliance ping failed: ${response.statusText}`);
  }
  return response.json();
}

// ============================================================================
// M&P Plan Generator V2 API
// ============================================================================

export interface MPPlanSessionSummary {
  session_id: string;
  program_name: string | null;
  created_at: string;
  updated_at: string;
  material_count: number;
  environment_count: number;
  nonconformance_count: number;
  blocking_question_count: number;
  can_generate: boolean;
  blockers: string[];
}

export interface MPPlanEnvironment {
  environment_id: string;
  name: string;
  o2_pct: number;
  pressure_psia: number;
  temp_range_c: [number, number];
  habitable: boolean;
  vacuum_exposure: boolean;
  lunar_dust: boolean;
  phase: string;
  source: string;
}

export interface MPPlanMaterial {
  id: string;
  name: string;
  application: string;
  quantity: number;
  maptis_code: string | null;
  mass_g: number | null;
  surface_area_cm2: number | null;
  spec: string | null;
  location: string | null;
  function: string | null;
  source: string;
}

export interface MPPlanBlockingQuestion {
  question_id: string;
  question_type: string;
  question_text: string;
  context: string;
  blocked_decisions: string[];
  options: string[] | null;
  source: string;
}

export interface MPPlanVehiclePreset {
  preset_id: string;
  name: string;
  o2_pct: number;
  pressure_psia: number;
  habitable: boolean;
}

export interface CreateMPPlanSessionRequest {
  program_name?: string;
  program_phase?: string;
  policy_pack_id?: string;
  vehicle_preset?: string;
}

export interface AddMPEnvironmentRequest {
  name: string;
  o2_pct: number;
  pressure_psia: number;
  temp_min_c: number;
  temp_max_c: number;
  habitable: boolean;
  vacuum_exposure?: boolean;
  lunar_dust?: boolean;
}

export interface AddMPMaterialRequest {
  name: string;
  application: string;
  quantity?: number;
  maptis_code?: string;
  mass_g?: number;
  surface_area_cm2?: number;
}

export interface SubmitMPAnswerRequest {
  question_id: string;
  answer: string;
  rationale?: string;
}

export interface GenerateMPArtifactsRequest {
  artifacts?: string[];
}

export interface GeneratedMPArtifact {
  name: string;
  artifact_id?: string;
  format?: string;
  size_bytes?: number;
  error?: string;
}

export interface MPPlanComputeResult {
  status: string;
  can_generate: boolean;
  blockers: string[];
  materials: number;
  environments: number;
  determinations: number;
  deficiencies: number;
  nonconformances: number;
  hitl_required: number;
  blocking_questions: MPPlanBlockingQuestion[];
}

/**
 * M&P Plan Generator health check.
 */
export async function mpPlanPing(): Promise<{ status: string; domain: string; version: string }> {
  const response = await fetch(`${API_BASE}/mp-plan/v2/ping`);
  if (!response.ok) {
    throw new Error(`M&P Plan ping failed: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Create a new M&P Plan session.
 */
export async function createMPPlanSession(
  req: CreateMPPlanSessionRequest
): Promise<MPPlanSessionSummary> {
  const response = await fetch(`${API_BASE}/mp-plan/v2/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to create session: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Get M&P Plan session by ID.
 */
export async function getMPPlanSession(sessionId: string): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}/mp-plan/v2/sessions/${sessionId}`);
  if (!response.ok) {
    throw new Error(`Failed to get session: ${response.statusText}`);
  }
  return response.json();
}

/**
 * List all M&P Plan sessions.
 */
export async function listMPPlanSessions(): Promise<{ sessions: MPPlanSessionSummary[]; count: number }> {
  const response = await fetch(`${API_BASE}/mp-plan/v2/sessions`);
  if (!response.ok) {
    throw new Error(`Failed to list sessions: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Delete M&P Plan session.
 */
export async function deleteMPPlanSession(sessionId: string): Promise<{ status: string; session_id: string }> {
  const response = await fetch(`${API_BASE}/mp-plan/v2/sessions/${sessionId}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    throw new Error(`Failed to delete session: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Add environment to session.
 */
export async function addMPPlanEnvironment(
  sessionId: string,
  env: AddMPEnvironmentRequest
): Promise<MPPlanEnvironment> {
  const response = await fetch(`${API_BASE}/mp-plan/v2/sessions/${sessionId}/environment`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(env),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to add environment: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Add materials to session (batch).
 */
export async function addMPPlanMaterials(
  sessionId: string,
  materials: AddMPMaterialRequest[]
): Promise<{ materials: MPPlanMaterial[]; count: number }> {
  const response = await fetch(`${API_BASE}/mp-plan/v2/sessions/${sessionId}/materials`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ materials }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to add materials: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Get blocking questions for session.
 */
export async function getMPPlanQuestions(
  sessionId: string
): Promise<{ questions: MPPlanBlockingQuestion[]; count: number }> {
  const response = await fetch(`${API_BASE}/mp-plan/v2/sessions/${sessionId}/questions`);
  if (!response.ok) {
    throw new Error(`Failed to get questions: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Submit answer to blocking question.
 */
export async function submitMPPlanAnswer(
  sessionId: string,
  req: SubmitMPAnswerRequest
): Promise<{ status: string; can_generate: boolean; blockers: string[]; remaining_questions: number }> {
  const response = await fetch(`${API_BASE}/mp-plan/v2/sessions/${sessionId}/answer`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to submit answer: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Run compute loop on session.
 */
export async function runMPPlanCompute(sessionId: string): Promise<MPPlanComputeResult> {
  const response = await fetch(`${API_BASE}/mp-plan/v2/sessions/${sessionId}/compute`, {
    method: 'POST',
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Compute failed: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Generate artifacts for session.
 */
export async function generateMPPlanArtifacts(
  sessionId: string,
  req: GenerateMPArtifactsRequest = {}
): Promise<{ status: string; artifacts: GeneratedMPArtifact[] }> {
  const response = await fetch(`${API_BASE}/mp-plan/v2/sessions/${sessionId}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Generation failed: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Submit closure decision for a nonconformance.
 */
export async function submitMPPlanClosure(
  sessionId: string,
  req: { gap_id: string; selected_path: string; rationale: string; provided_inputs?: Record<string, unknown> }
): Promise<{ status: string; gap_id: string; can_generate: boolean; blockers: string[] }> {
  const response = await fetch(`${API_BASE}/mp-plan/v2/sessions/${sessionId}/closure`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to submit closure: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Accept an open gap (defer closure with owner + due date).
 */
export async function acceptMPPlanOpenGap(
  sessionId: string,
  req: { gap_id: string; rationale: string; owner: string; due_date?: string; risk_statement?: string }
): Promise<{ status: string; gap_id: string; owner: string; due_date: string; can_generate: boolean; blockers: string[] }> {
  const response = await fetch(`${API_BASE}/mp-plan/v2/sessions/${sessionId}/accept-open`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to accept open gap: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Reopen a previously closed or accepted gap.
 */
export async function reopenMPPlanGap(
  sessionId: string,
  gapId: string
): Promise<{ status: string; gap_id: string; closure_removed: number; acceptance_removed: number }> {
  const response = await fetch(`${API_BASE}/mp-plan/v2/sessions/${sessionId}/reopen-gap/${gapId}`, {
    method: 'POST',
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to reopen gap: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Export M&P Plan as structured JSON.
 */
export async function exportMPPlanJson(sessionId: string): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}/mp-plan/v2/sessions/${sessionId}/export/mp-plan-json`);
  if (!response.ok) {
    throw new Error(`Failed to export JSON: ${response.statusText}`);
  }
  return response.json();
}

/**
 * List vehicle presets.
 */
export async function listMPPlanVehiclePresets(): Promise<{ presets: MPPlanVehiclePreset[] }> {
  // Prefer v2 endpoint (same namespace as the rest of MP Plan v2 API), then
  // fall back to legacy path for older backend builds.
  const v2Response = await fetch(`${API_BASE}/mp-plan/v2/vehicle-presets`);
  if (v2Response.ok) {
    return v2Response.json();
  }

  const legacyResponse = await fetch(`${API_BASE}/mp-plan/vehicle-presets`);
  if (!legacyResponse.ok) {
    throw new Error(`Failed to list vehicle presets: ${legacyResponse.statusText}`);
  }
  return legacyResponse.json();
}

/**
 * Download artifact URL.
 */
export function getMPPlanArtifactDownloadUrl(sessionId: string, artifactId: string): string {
  return `${API_BASE}/mp-plan/v2/sessions/${sessionId}/download/${artifactId}`;
}

export interface MaptisSearchResult {
  material_code: string;
  designation: string;
  confidence: string;
  method: string;
  score: number;
}

/**
 * Search MAPTIS for material codes by material name.
 */
export async function searchMaptisCode(query: string, limit = 5): Promise<{
  query: string;
  results: MaptisSearchResult[];
  count: number;
  error?: string;
}> {
  const response = await fetch(
    `${API_BASE}/mp-plan/maptis-search?q=${encodeURIComponent(query)}&limit=${limit}`
  );
  if (!response.ok) {
    throw new Error(`MAPTIS search failed: ${response.statusText}`);
  }
  return response.json();
}

// ============================================================================
// O2 Knowledge Twin API - Dedicated Oxygen Compatibility Endpoints
// ============================================================================

export interface O2EvaluateRequest {
  material_key: string;
  pressure_psia?: number;
  temperature_f?: number;
  phase?: 'gox' | 'lox';
  application_id?: string;
}

export interface O2EvidenceItem {
  source_id: string;
  location?: string | null;
  summary: string;
}

export interface O2EvaluateResponse {
  classification: string;
  rationale: string;
  evidence: O2EvidenceItem[];
  notes?: string | null;
  material_key: string;
  pressure_psia: number;
  temperature_f: number;
  phase: string;
  timestamp: string;
}

export interface O2BOKSearchRequest {
  query: string;
  k?: number;
  use_hybrid?: boolean;
}

export interface O2BOKSearchResult {
  doc_id: string;
  text: string;
  source: string;
  section?: string | null;
  relevance_score: number;
  semantic_rank?: number | null;
  bm25_rank?: number | null;
}

export interface O2BOKSearchResponse {
  query: string;
  results: O2BOKSearchResult[];
  total_results: number;
  search_type: string;
  timestamp: string;
}

export interface O2FamilyRule {
  family: string;
  reason: string;
  bok_ref: string;
}

export interface O2FamiliesResponse {
  prohibited_families: O2FamilyRule[];
  restricted_families: O2FamilyRule[];
  approved_families: O2FamilyRule[];
  note: string;
}

/**
 * O2 Knowledge Twin health check.
 */
export async function o2Ping(): Promise<{ status: string; domain: string }> {
  const response = await fetch(`${API_BASE}/o2/ping`);
  if (!response.ok) {
    throw new Error(`O2 ping failed: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Evaluate material O2 compatibility using the dedicated O2 Knowledge Twin.
 */
export async function o2Evaluate(req: O2EvaluateRequest): Promise<O2EvaluateResponse> {
  const response = await fetch(`${API_BASE}/o2/evaluate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `O2 evaluation failed: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Search the O2 Body of Knowledge (BOK) for standards and guidance.
 */
export async function o2SearchBOK(req: O2BOKSearchRequest): Promise<O2BOKSearchResponse> {
  const response = await fetch(`${API_BASE}/o2/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `O2 BOK search failed: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Get O2 material family classification rules from NASA-STD-6016.
 */
export async function o2GetFamilies(): Promise<O2FamiliesResponse> {
  const response = await fetch(`${API_BASE}/o2/families`);
  if (!response.ok) {
    throw new Error(`Failed to get O2 families: ${response.statusText}`);
  }
  return response.json();
}

// ============================================================================
// OCA (Oxygen Compatibility Assessment) Workbench API
// ============================================================================

export type OCAOxidizerType = 'lox' | 'gox' | 'enriched_air' | 'compressed_air';
export type OCAPhase = 'liquid' | 'gas';
export type OCAFlowRegime = 'static' | 'laminar' | 'turbulent';
export type OCAMissionPhase = 'ground_test' | 'ascent' | 'on_orbit' | 'servicing';
export type OCAComponentClass = 'valve' | 'regulator' | 'line' | 'vessel' | 'seal' | 'filter' | 'sensor' | 'fitting' | 'flex_hose' | 'other';
export type OCAGeometryClass = 'bulk' | 'thin_wall' | 'mesh' | 'porous' | 'sintered' | 'seal' | 'other';
export type OCAFlammabilityRating = 'A' | 'B' | 'C' | 'D' | 'X' | 'U' | 'unknown';
export type OCACredibleStatus = 'CREDIBLE' | 'NOT_CREDIBLE' | 'INDETERMINATE';
export type OCADisposition =
  | 'compatible_as_configured'
  | 'compatible_with_controls'
  | 'requires_mua'
  | 'requires_acceptance_test'
  | 'requires_supplemental_testing'
  | 'insufficient_evidence'
  | 'prohibited';
export type OCARuleTier = 'tier_a' | 'tier_b' | 'tier_c' | 'tier_d';
export type OCARequirementStatus = 'not_triggered' | 'satisfied' | 'action_required' | 'prohibited';
export type OCAApplicabilityClass = 'DIRECT' | 'PARTIAL' | 'WEAK_ANALOG' | 'NOT_APPLICABLE';

export interface OCAServiceContext {
  oxidizer_type: OCAOxidizerType;
  o2_fraction: number;
  total_pressure_min_psia: number;
  total_pressure_max_psia: number;
  oxygen_partial_pressure_psia?: number | null;
  phase: OCAPhase;
  temp_min_c?: number | null;
  temp_max_c?: number | null;
  flow_regime: OCAFlowRegime;
  velocity_m_s?: number | null;
  cleanliness_verified?: boolean | null;
  contamination_notes?: string | null;
  mission_phase?: OCAMissionPhase | null;
  application?: string | null;
}

export interface OCAComponent {
  component_id?: string;
  component_class: OCAComponentClass;
  geometry_class: OCAGeometryClass;
  design_function: string;
  dynamic_contact_flag: boolean;
  is_rigid_metallic_tubing: boolean;
  is_metallic_flex_hose: boolean;
  is_all_metal_seal: boolean;
  is_metallic_pressure_vessel: boolean;
  seal_type?: 'metal' | 'polymer' | 'composite' | null;
  pressure_boundary_material?: string | null;
}

export interface OCAMaterial {
  material_name: string;
  spec?: string | null;
  grade?: string | null;
  temper?: string | null;
  product_form?: string | null;
  coating?: string | null;
  surface_condition?: string | null;
  role_in_component?: string | null;
}

export interface OCAIgnitionContext {
  entrainable_particles_present?: boolean | null;
  rapid_pressurization_time_ms?: number | null;
  dead_end_configuration?: boolean | null;
  nonmetal_exposed_to_flow?: boolean | null;
  vibration_or_erosion_present?: boolean | null;
  acoustic_cavity_present?: boolean | null;
  mechanical_impact_risk?: boolean | null;
  isolated_surface_present?: boolean | null;
  dry_gas_environment?: boolean | null;
  electrical_power_present?: boolean | null;
  reactive_chemical_pair_present?: boolean | null;
  porous_media_present?: boolean | null;
  open_flame_or_hot_work_present?: boolean | null;
}

export interface OCAResolvedMaterial extends OCAMaterial {
  canonical_name: string;
  family: string;
  identity_confidence: number;
  synonym_list: string[];
  rating_flam?: string | null;
  o2_test_count: number;
  max_tested_pressure_psia?: number | null;
  data_source: string;
}

export interface OCABlockedState {
  code: string;
  detail: string;
  resolution_hint: string;
  severity: string;
}

export interface OCAPrecheckWarning {
  code: string;
  message: string;
}

export interface OCATriggeredRequirement {
  requirement_id: string;
  title: string;
  citation: string;
  tier: OCARuleTier;
  triggered: boolean;
  status: OCARequirementStatus;
  reasoning: string;
  evidence_links: string[];
  downstream_actions: string[];
}

export interface OCAEvidenceApplicability {
  exact_material_match: boolean;
  spec_match: boolean;
  form_match: boolean;
  geometry_match: boolean;
  pressure_match: boolean;
  o2_fraction_match: boolean;
  phase_match: boolean;
  temperature_match: boolean;
  coating_match: boolean;
  method_relevance: boolean;
  aggregate_score: number;
  applicability_class: OCAApplicabilityClass;
}

export interface OCAEvidenceCard {
  evidence_id: string;
  material_name: string;
  source_id: string;
  title: string;
  citation: string;
  tier: OCARuleTier;
  summary: string;
  test_method?: string | null;
  specimen_description?: string | null;
  test_conditions?: string | null;
  result?: string | null;
  applicability: OCAEvidenceApplicability;
  gaps: string[];
}

export interface OCAMechanismTrace {
  mechanism_name: string;
  source_ref: string;
  required_elements: string[];
  observed_elements: string[];
  missing_elements: string[];
  rating_formula_version: string;
  rating_result: number;
  reviewer_comments: string[];
}

export interface OCAMechanismAssessment {
  mechanism_name: string;
  credible_status: OCACredibleStatus;
  rating: number;
  source_ref: string;
  required_elements: string[];
  observed_elements: string[];
  missing_elements: string[];
  linked_evidence_ids: string[];
  gaps_identified: string[];
  mechanism_trace: OCAMechanismTrace;
}

export interface OCADecisionAction {
  action_id: string;
  label: string;
  rationale: string;
}

export interface OCADecisionPacket {
  case_id: string;
  final_disposition: OCADisposition;
  triggered_requirements: OCATriggeredRequirement[];
  blocked_states: OCABlockedState[];
  unresolved_gaps: string[];
  kindling_chain_present: boolean;
  reaction_effect?: string | null;
  history_of_use: string;
  mua_seed: Record<string, unknown>;
  acceptance_test_required: boolean;
  reviewer_required: boolean;
  overall_confidence: string;
  authority_level: OCARuleTier;
  governing_prohibition?: string | null;
  summary_rationale: string;
  actions: OCADecisionAction[];
}

export interface OCACreateCaseRequest {
  case_name?: string | null;
  free_text_intake?: string | null;
  service_context: OCAServiceContext;
  materials: OCAMaterial[];
  components: OCAComponent[];
  ignition_context?: OCAIgnitionContext;
}

export interface OCANormalizedInput {
  service_context: OCAServiceContext;
  materials: OCAResolvedMaterial[];
  components: OCAComponent[];
  ignition_context: OCAIgnitionContext;
}

export interface OCACreateCaseResponse {
  case_id: string;
  revision: number;
  normalized_input: OCANormalizedInput;
  blocked_states: OCABlockedState[];
  precheck_warnings: OCAPrecheckWarning[];
}

export interface OCAPrecheckResponse {
  case_id: string;
  revision: number;
  blocked_states: OCABlockedState[];
  triggered_requirements: OCATriggeredRequirement[];
  precheck_warnings: OCAPrecheckWarning[];
}

export interface OCAEvidenceResponse {
  case_id: string;
  revision: number;
  evidence: OCAEvidenceCard[];
  gaps: string[];
}

export interface OCAMechanismResponse {
  case_id: string;
  revision: number;
  mechanisms: OCAMechanismAssessment[];
}

export interface OCADecisionResponse {
  case_id: string;
  revision: number;
  decision: OCADecisionPacket;
}

export interface OCARevision {
  revision: number;
  created_at: string;
  note: string;
}

export interface OCARuleTraceEvent {
  stage: string;
  rule_id: string;
  tier: OCARuleTier;
  outcome: string;
  detail: string;
  recorded_at: string;
}

export interface OCARequirementsResponse {
  case_id: string;
  revision: number;
  requirements: OCATriggeredRequirement[];
}

export interface OCALineageResponse {
  case_id: string;
  revision: number;
  revisions: OCARevision[];
  decision_lineage: OCARuleTraceEvent[];
}

export interface OCAAuthoritySource {
  source_id: string;
  title: string;
  edition: string;
  change_number?: string | null;
  publication_date: string;
  checksum: string;
  ingest_date: string;
}

export interface OCAAuthorityManifest {
  spec_id: string;
  approved_on: string;
  sources: OCAAuthoritySource[];
}

export interface OCAExportArtifact {
  artifact_type: string;
  filename: string;
  content_type: string;
  generated_text: string;
}

export interface OCAExportResponse {
  case_id: string;
  revision: number;
  artifacts: OCAExportArtifact[];
}

export async function ocaPing(): Promise<{ status: string; domain: string }> {
  const response = await fetch(`${API_BASE}/oca/ping`);
  if (!response.ok) throw new Error(`OCA ping failed: ${response.statusText}`);
  return response.json();
}

export async function ocaGetAuthority(): Promise<OCAAuthorityManifest> {
  const response = await fetch(`${API_BASE}/oca/authority`);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `OCA authority lookup failed: ${response.statusText}`);
  }
  return response.json();
}

export async function ocaCreateCase(req: OCACreateCaseRequest): Promise<OCACreateCaseResponse> {
  const response = await fetch(`${API_BASE}/oca/cases`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `OCA case creation failed: ${response.statusText}`);
  }
  return response.json();
}

export async function ocaPrecheck(caseId: string): Promise<OCAPrecheckResponse> {
  const response = await fetch(`${API_BASE}/oca/cases/${caseId}/precheck`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `OCA precheck failed: ${response.statusText}`);
  }
  return response.json();
}

export async function ocaGetEvidence(caseId: string): Promise<OCAEvidenceResponse> {
  const response = await fetch(`${API_BASE}/oca/cases/${caseId}/evidence`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `OCA evidence lookup failed: ${response.statusText}`);
  }
  return response.json();
}

export async function ocaAssessMechanisms(caseId: string): Promise<OCAMechanismResponse> {
  const response = await fetch(`${API_BASE}/oca/cases/${caseId}/mechanisms`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `OCA mechanism assessment failed: ${response.statusText}`);
  }
  return response.json();
}

export async function ocaRunDecision(caseId: string): Promise<OCADecisionResponse> {
  const response = await fetch(`${API_BASE}/oca/cases/${caseId}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `OCA decision failed: ${response.statusText}`);
  }
  return response.json();
}

export async function ocaGetRequirements(caseId: string): Promise<OCARequirementsResponse> {
  const response = await fetch(`${API_BASE}/oca/cases/${caseId}/requirements`);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `OCA requirements lookup failed: ${response.statusText}`);
  }
  return response.json();
}

export async function ocaGetLineage(caseId: string): Promise<OCALineageResponse> {
  const response = await fetch(`${API_BASE}/oca/cases/${caseId}/lineage`);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `OCA lineage lookup failed: ${response.statusText}`);
  }
  return response.json();
}

export async function ocaExport(caseId: string): Promise<OCAExportResponse> {
  const response = await fetch(`${API_BASE}/oca/cases/${caseId}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `OCA export failed: ${response.statusText}`);
  }
  return response.json();
}

// ============================================================================
// MIRA v4 Decision Lineage API
// ============================================================================

export type V4GateAction = 'PASS' | 'CLARIFY' | 'REFUSE';
export type V4SafetyContext = 'oxygen' | 'hydrogen' | 'cryogenic' | 'high_pressure' | 'general';
export type V4DirtyDataTier = 'clean' | 'degraded' | 'refuse';
export type V4HeritageVetoType = 'safety_critical' | 'non_safety';

export interface V4PenaltyDetail {
  penalty_type: string;
  penalty_value: number;
  explanation: string;
}

export interface V4ConfidenceResponse {
  score: number;
  penalties: Record<string, number>;
  penalty_details: V4PenaltyDetail[];
  gate_action: V4GateAction;
  safety_critical: boolean;
  explanation: string;
}

export interface V4BatchGateResponse {
  action: 'PROCEED' | 'REFUSE';
  penalty: number;
  missing_fields: string[];
  safety_context: V4SafetyContext;
  reason: string;
}

export interface V4DirtyDataResponse {
  tier: V4DirtyDataTier;
  dirty_fraction: number;
  total_records: number;
  dirty_records: number;
  user_message: string | null;
}

export interface V4HeritageVetoResponse {
  vetoed: boolean;
  veto_type: V4HeritageVetoType | null;
  heritage_failure_ids: string[];
  requires_acknowledgment: boolean;
  rank_penalty: number;
  envelope_match_details: Record<string, unknown>;
}

export interface V4IntentDisagreementResponse {
  sonnet_intent: string;
  heuristic_intent: string;
  chosen_intent: string;
  penalty_applied: number;
  explanation: string;
}

export interface V4QueryRequest {
  query: string;
  batch_mode?: boolean;
  material_key?: string;
  temperature_c?: number;
  pressure_kpa?: number;
  o2_pct?: number;
  fluid_medium?: string;
  duration_hr?: number;
  cycles?: number;
}

export interface V4MaterialResult {
  material_key: number;
  material_code: string | null;
  designation: string;
  composition: string | null;
  material_type_key: number | null;
  material_type_name: string | null;
  use_temp_min_f: number | null;
  use_temp_max_f: number | null;
  use_temp_min_c: number | null;
  use_temp_max_c: number | null;
  test_counts: Record<string, number>;
  total_tests: number;
  latest_test_year: number | null;
  mua_count: number;
  has_mua_precedent: boolean;
  oxygen_compatible: boolean;
  similarity_score: number | null;
}

export interface V4QueryResponse {
  lineage_id: string;
  query_hash: string;
  snapshot_hash: string;
  confidence: V4ConfidenceResponse;
  gate_action: V4GateAction;
  batch_gate: V4BatchGateResponse | null;
  dirty_data: V4DirtyDataResponse | null;
  heritage_veto: V4HeritageVetoResponse | null;
  intent_disagreement: V4IntentDisagreementResponse | null;
  answer: string;
  materials: V4MaterialResult[];
  all_materials: V4MaterialResult[];
  all_material_count: number;
  materials_focus_applied: boolean;
  material_families: string[];
  search_source: string;
  parsed_query: Record<string, unknown>;
  schema_version: string;
  timestamp: string;
  total_test_records: number;
  materials_with_tests: number;
  materials_with_mua: number;
}

export interface V4BatchQueryResponse {
  results: V4QueryResponse[];
  total: number;
  refused_count: number;
}

export interface V4HeritageOverrideRequest {
  material_key: string;
  heritage_failure_id: string;
  failure_environment: Record<string, unknown>;
  query_environment: Record<string, unknown>;
  engineer_name: string;
  engineer_rationale: string;
  lineage_hash: string;
}

export interface V4HeritageOverrideResponse {
  override_id: string;
  material_key: string;
  heritage_failure_id: string;
  engineer_name: string;
  timestamp: string;
  acknowledged: boolean;
}

export interface V4SchemaValidationResponse {
  passed: boolean;
  schema_version: string;
  changes: Record<string, unknown>[];
  requires_faiss_rebuild: boolean;
  requires_regression: boolean;
}

/**
 * MIRA v4 health check.
 */
export async function v4Ping(): Promise<{ status: string; domain: string; version: string }> {
  const response = await fetch(`${API_BASE}/mira/v4/ping`);
  if (!response.ok) {
    throw new Error(`V4 ping failed: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Execute the full MIRA v4 decision lineage pipeline.
 */
export async function v4Query(req: V4QueryRequest): Promise<V4QueryResponse> {
  const response = await fetch(`${API_BASE}/mira/v4/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `V4 query failed: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Execute MIRA v4 pipeline in batch mode.
 */
export async function v4QueryBatch(
  queries: V4QueryRequest[]
): Promise<V4BatchQueryResponse> {
  const response = await fetch(`${API_BASE}/mira/v4/query/batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ queries }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `V4 batch query failed: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Create an immutable heritage veto override (engineer acknowledgment).
 */
export async function v4HeritageOverride(
  req: V4HeritageOverrideRequest
): Promise<V4HeritageOverrideResponse> {
  const response = await fetch(`${API_BASE}/mira/v4/heritage/override`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Heritage override failed: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Run schema validation for CI pipeline.
 */
export async function v4SchemaValidate(): Promise<V4SchemaValidationResponse> {
  const response = await fetch(`${API_BASE}/mira/v4/schema/validate`);
  if (!response.ok) {
    throw new Error(`Schema validation failed: ${response.statusText}`);
  }
  return response.json();
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchJsonWithTimeout(input: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(input, {
      ...init,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function forgeCompileStart(req: ForgeCompileRequest): Promise<ForgeCompileAcceptedResponse> {
  const response = await fetchJsonWithTimeout(
    `${API_BASE}/forge/compile`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    },
    30_000,
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `FORGE compile failed: ${response.statusText}`);
  }

  return response.json();
}

export async function forgeCompileStatus(jobId: string): Promise<ForgeCompileJobResponse> {
  const response = await fetchJsonWithTimeout(
    `${API_BASE}/forge/compile/${jobId}`,
    { method: 'GET' },
    30_000,
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `FORGE compile status failed: ${response.statusText}`);
  }

  return response.json();
}

export async function forgeCompile(
  req: ForgeCompileRequest,
  options?: {
    timeoutMs?: number;
    pollIntervalMs?: number;
    onProgress?: (job: ForgeCompileJobResponse) => void;
  },
): Promise<ForgeCompileResponse> {
  const accepted = await forgeCompileStart(req);
  const timeoutMs = options?.timeoutMs ?? 0;
  const deadline = timeoutMs > 0 ? Date.now() + timeoutMs : Number.POSITIVE_INFINITY;
  const pollIntervalMs = options?.pollIntervalMs ?? accepted.poll_after_ms ?? 1500;

  while (Date.now() < deadline) {
    const job = await forgeCompileStatus(accepted.job_id);
    options?.onProgress?.(job);

    if (job.status === 'completed') {
      if (!job.result) {
        throw new Error('FORGE compile completed without a result payload.');
      }
      return job.result;
    }

    if (job.status === 'failed') {
      throw new Error(job.error || job.message || 'FORGE compile failed.');
    }

    await sleep(pollIntervalMs);
  }

  throw new Error('FORGE compile timed out before completion.');
}

export interface ForgeBSMSQueryRequest {
  query: string;
  question_map: Record<string, unknown>;
  database_url?: string;
  bsms_pipeline: Record<string, unknown>;
  authority_pack: Record<string, unknown>;
  limit?: number;
  require_llm?: boolean;
  persist_lineage?: boolean;
  lineage_dir?: string;
}

export interface ForgeBSMSQueryResponse {
  status: string;
  pipeline: string;
  bouncer: Record<string, unknown>;
  parsed_intent?: Record<string, unknown> | null;
  rules?: Record<string, unknown> | null;
  answer: string;
  lineage: Record<string, unknown>;
}

export async function forgeBSMSQuery(req: ForgeBSMSQueryRequest): Promise<ForgeBSMSQueryResponse> {
  const response = await fetch(`${API_BASE}/forge/bsms/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `BSMS query failed: ${response.statusText}`);
  }

  return response.json();
}

// ============================================================================
// BSMH (Temp) API
// ============================================================================

export interface BSMHStructuredQuery {
  material: string | null;
  materials: string[];
  environment: string | null;
  pressure_psi: number | null;
  temperature_f: number | null;
  o2_pct: number | null;
  intent: string;
  original_query: string;
}

export interface BSMHBouncerResult {
  status: 'accepted' | 'rejected';
  rejection_reason: string | null;
  structured_query: BSMHStructuredQuery | null;
  source: 'local_llm' | 'heuristic' | 'haiku';
}

export interface BSMHRuleEvidenceItem {
  property: string;
  value: string;
  requirement: string;
  passed: boolean;
  source: string | null;
}

export interface BSMHMaterialRuleResult {
  material_name: string;
  material_key: unknown;
  oxygen_rating: string | null;
  hydrogen_signal_present: boolean | null;
  verdict: 'COMPATIBLE' | 'INCOMPATIBLE' | 'CONDITIONAL' | 'INSUFFICIENT_DATA';
  score: number;
  warnings: string[];
  limitations: string[];
  evidence_chain: BSMHRuleEvidenceItem[];
}

export interface BSMHRuleDecisionPacket {
  verdict: 'COMPATIBLE' | 'INCOMPATIBLE' | 'CONDITIONAL' | 'INSUFFICIENT_DATA';
  confidence: number;
  materials: BSMHMaterialRuleResult[];
  aggregation_scope: 'primary_only' | 'all_materials';
  primary_material_count: number;
  associated_material_count: number;
  bok_context_used: boolean;
  bok_evidence_count: number;
  bok_sources: string[];
  requested_materials: string[];
  missing_requested_materials: string[];
  determination_material_keys: unknown[];
  determination_material_names: string[];
  rules_applied: string[];
  standards_category: string | null;
  evidence_gaps: string[];
}

export interface BSMHQueryResponse {
  status: 'ok' | 'rejected' | 'error';
  pipeline: string;
  answer: string;
  answer_sonnet: string | null;
  answer_mode: 'sonnet';
  sonnet_calls_used: number;
  bouncer: BSMHBouncerResult;
  rules: BSMHRuleDecisionPacket | null;
  materials: V4MaterialResult[];
  sonnet_metadata: Record<string, unknown>;
  raw_v4_answer: string | null;
  v4_lineage_id: string | null;
  v4_gate_action: string | null;
  v4_confidence_score: number | null;
  error: string | null;
}

/**
 * Execute temporary BSMH pipeline.
 */
export interface BSMHQueryRequest extends V4QueryRequest {
  answer_mode?: 'sonnet';
}

export type QueryRequest = BSMHQueryRequest;
export type QueryResponse = BSMHQueryResponse;

export async function miraQuery(req: QueryRequest): Promise<QueryResponse> {
  const response = await fetch(`${API_BASE}/mira/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `MIRA query failed: ${response.statusText}`);
  }

  return response.json();
}

export async function bsmhQuery(req: BSMHQueryRequest): Promise<BSMHQueryResponse> {
  const response = await fetch(`${API_BASE}/mira/bsmh/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `BSMH query failed: ${response.statusText}`);
  }

  return response.json();
}

export interface GalvanicMaterialStateBand {
  state: string;
  representative_potential_mv_sce: number;
}

export interface GalvanicResolvedMaterial {
  query: string;
  canonical_name: string;
  family: string;
  chosen_state: string;
  representative_potential_mv_sce: number;
  potential_range_mv_sce: [number, number];
  possible_states: GalvanicMaterialStateBand[];
  source_type: string;
}

export interface GalvanicMitigationRecommendation {
  mitigation_id: string;
  name: string;
  mechanism: string;
  mitigation_class: string;
  boundstate_priority: number;
  description: string;
  source_clauses: string[];
  standards: string[];
  restrictions: string[];
  notes: string[];
  coat_cathode_warning: boolean;
  trigger_reason: string;
}

export interface GalvanicAssessmentRequest {
  material_a: string;
  material_b: string;
  environment:
    | 'seawater_proxy'
    | 'coastal_condensing'
    | 'industrial_atm'
    | 'rural_atm'
    | 'crew_condensing'
    | 'dry_indoor'
    | 'cryogenic_ops'
    | 'space_vacuum';
  application_type:
    | 'FLIGHT_HARDWARE'
    | 'SPACECRAFT_STRUCTURE'
    | 'GROUND_SUPPORT_EQUIPMENT'
    | 'LAUNCH_STRUCTURE'
    | 'FIXED_INSTALLATION';
  surface_condition_a?: string | null;
  surface_condition_b?: string | null;
  couple_context?: {
    electrical_contact?: 'YES' | 'NO' | 'UNKNOWN';
    electrolyte_pooling?: boolean;
    joint_type?: 'FAYING_SURFACE' | 'FASTENER' | 'LAP_JOINT' | 'CREVICE_PRONE' | 'IMMERSED' | 'GENERAL';
    cathode_to_anode_area_ratio?: number | null;
  };
}

export interface GalvanicAssessmentResponse {
  severity: 'COMPATIBLE' | 'CAUTION' | 'INCOMPATIBLE';
  raw_delta_mv: number;
  effective_delta_mv: number;
  decision_basis: 'NASA_STD_6012A_CPR39' | 'BOUNDSTATE_SYNTHESIZED' | 'NO_ELECTRICAL_CONTACT' | 'NO_ELECTROLYTE';
  screening_disclaimer: string;
  environment: string;
  environment_modifier: number;
  application_type: string;
  anode: string;
  cathode: string;
  material_a: GalvanicResolvedMaterial;
  material_b: GalvanicResolvedMaterial;
  warnings: string[];
  mitigations: GalvanicMitigationRecommendation[];
  source_manifest_version: string;
}

export interface GalvanicEnvironmentDescriptor {
  key: string;
  label: string;
  modifier: number;
  notes: string;
}

export interface GalvanicMaterialSearchResult {
  canonical_name: string;
  family: string;
  aliases: string[];
}

export interface GalvanicSeriesRecord {
  id: string;
  variant_group: string;
  canonical_name: string;
  name: string;
  primary: boolean;
  family: string;
  state: string;
  aliases: string[];
  potential_range_mv_sce: [number, number];
  representative_potential_mv_sce: number;
  source_type: string;
  source_documents: string[];
}

export interface GalvanicSeriesPayload {
  module: string;
  dataset: string;
  version: string;
  extraction_status: string;
  minimum_expected_records: number;
  reference_environment: {
    label: string;
    conditions: string;
    reference_electrode: string;
  };
  source_priority: Array<{
    priority: string;
    source: string;
    path: string;
  }>;
  records: GalvanicSeriesRecord[];
}

export async function galvanicEvaluate(
  req: GalvanicAssessmentRequest,
  headers?: HeadersInit,
): Promise<GalvanicAssessmentResponse> {
  const response = await fetch(`${API_BASE}/mira/galvanic/evaluate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(headers || {}) },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Galvanic assessment failed: ${response.statusText}`);
  }

  return response.json();
}

export async function galvanicListEnvironments(
  headers?: HeadersInit,
): Promise<GalvanicEnvironmentDescriptor[]> {
  const response = await fetch(`${API_BASE}/mira/galvanic/environments`, { headers });

  if (!response.ok) {
    throw new Error(`Failed to load galvanic environments: ${response.statusText}`);
  }

  return response.json();
}

export async function galvanicSearchMaterials(
  q: string,
  headers?: HeadersInit,
): Promise<GalvanicMaterialSearchResult[]> {
  const params = new URLSearchParams({ q });
  const response = await fetch(`${API_BASE}/mira/galvanic/materials/search?${params.toString()}`, {
    headers,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Galvanic material search failed: ${response.statusText}`);
  }

  return response.json();
}

export async function galvanicGetSeries(headers?: HeadersInit): Promise<GalvanicSeriesPayload> {
  const response = await fetch(`${API_BASE}/mira/galvanic/series`, { headers });

  if (!response.ok) {
    throw new Error(`Failed to load galvanic source dataset: ${response.statusText}`);
  }

  return response.json();
}

export interface FractureCitation {
  fcr?: number | null;
  title: string;
  section: string;
  source_document: string;
  source_path: string;
  source_pages: number[];
  summary: string;
}

export interface FractureRequirementSummary {
  fcr: number;
  category: string;
  title: string;
  section: string;
  description: string;
  phase_1_relevant: boolean;
  notes?: string | null;
  citation: FractureCitation;
}

export interface FractureResolvedMaterial {
  query: string;
  canonical_name: string;
  material_system: 'METALLIC' | 'COMPOSITE' | 'BONDED' | 'CERAMIC' | 'OTHER';
  family: string;
  aliases: string[];
}

export interface FractureMaterialFinding {
  finding_id: string;
  status: 'PASS' | 'CAUTION' | 'FAIL' | 'INFO' | 'DATA_GAP';
  title: string;
  detail: string;
  governing_fcrs: number[];
  source_clauses: string[];
  data_provided: string[];
  citations: FractureCitation[];
}

export interface FractureMaterialContext {
  low_risk_candidate?: boolean;
  additive_manufactured?: boolean;
  kic_fty_ratio?: number | null;
  ftu_ksi?: number | null;
  short_transverse_dimension_in?: number | null;
  chloride_exposure?: boolean;
  sustained_load_expected?: boolean;
  nasa_std_6016_qualified?: boolean | null;
  mua_present?: boolean;
  approved_source_data_attached?: boolean;
}

export interface FractureAssessmentRequest {
  part_name: string;
  mission_class: 'HUMAN_RATED' | 'CARGO' | 'EXPERIMENTAL' | 'GSE' | 'GROUND_SUPPORT';
  hazard_consequence: 'CATASTROPHIC' | 'CRITICAL' | 'MARGINAL' | 'NEGLIGIBLE' | 'UNKNOWN';
  load_path_type: 'SINGLE' | 'REDUNDANT' | 'UNKNOWN';
  pressure_boundary: boolean;
  lifecycle_phase?: 'NEW_BUILD' | 'REFLIGHT';
  structural_role: 'PRIMARY' | 'SECONDARY' | 'NON_STRUCTURAL';
  material_system: 'METALLIC' | 'COMPOSITE' | 'BONDED' | 'CERAMIC' | 'OTHER';
  specific_hardware_type:
    | 'GENERAL'
    | 'FASTENER'
    | 'SHATTERABLE'
    | 'ROTATING_HARDWARE'
    | 'SEALED_CONTAINER'
    | 'TOOLS_TETHERS'
    | 'BATTERY'
    | 'PRESSURE_VESSEL'
    | 'COPV'
    | 'PRESSURIZED_COMPONENT'
    | 'HABITABLE_STRUCTURE'
    | 'PRESSURIZED_STRUCTURE';
  material_name?: string | null;
  optional_approach_requested?: boolean;
  proof_test_used?: boolean;
  process_controls_used?: boolean;
  detected_flaw_accepted_for_flight?: boolean;
  corrosion_iccp_recommended?: boolean;
  material_context?: FractureMaterialContext;
}

export interface FractureAssessmentResponse {
  classification: 'EXEMPT' | 'NFC_METALLIC' | 'NFC_COMPOSITE_BONDED' | 'FC' | 'INDETERMINATE';
  baseline_key: string;
  confidence_state: 'CONFIDENT' | 'INDETERMINATE' | 'CONSERVATIVE_FALLBACK';
  screening_basis: string;
  applicable_fcrs: number[];
  requirements: FractureRequirementSummary[];
  required_actions: string[];
  required_documents: string[];
  resolved_material?: FractureResolvedMaterial | null;
  material_findings: FractureMaterialFinding[];
  warnings: string[];
  unresolved_inputs: string[];
  conservative_fallback?: string | null;
  citations: FractureCitation[];
  source_manifest_version: string;
}

export interface FractureAuthorityManifest {
  version: string;
  total_fcrs: number;
  baseline_count: number;
  conditional_extension_count: number;
  special_rule_count: number;
  sources: Array<{
    document: string;
    path: string;
  }>;
}

export interface FractureMaterialSearchResult {
  canonical_name: string;
  material_system: 'METALLIC' | 'COMPOSITE' | 'BONDED' | 'CERAMIC' | 'OTHER';
  family: string;
  aliases: string[];
}

export async function fractureClassify(
  req: FractureAssessmentRequest,
): Promise<FractureAssessmentResponse> {
  const response = await fetch(`${API_BASE}/mira/fracture/classify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Fracture assessment failed: ${response.statusText}`);
  }

  return response.json();
}

export async function fractureGetAuthority(): Promise<FractureAuthorityManifest> {
  const response = await fetch(`${API_BASE}/mira/fracture/authority`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Fracture authority lookup failed: ${response.statusText}`);
  }

  return response.json();
}

export async function fractureSearchMaterials(q: string): Promise<FractureMaterialSearchResult[]> {
  const params = new URLSearchParams({ q });
  const response = await fetch(`${API_BASE}/mira/fracture/materials/search?${params.toString()}`);

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Fracture material search failed: ${response.statusText}`);
  }

  return response.json();
}
