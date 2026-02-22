const API_BASE = '/api/mua/v7';

// ---------------------------------------------------------------------------
// Enums / literal types
// ---------------------------------------------------------------------------

export type EvidenceStrengthBand = 'strong' | 'moderate' | 'weak' | 'insufficient';
export type StepName = 'define' | 'investigate' | 'review' | 'draft' | 'finalize';
export type SessionStatus = 'active' | 'draft_saved' | 'finalized' | 'abandoned';
export type ResolutionStatus = 'resolved' | 'fuzzy' | 'unresolved';
export type ReviewDecisionType = 'include_supporting' | 'include_context' | 'exclude';
export type GapDecisionType = 'accept_with_rationale' | 'flag_for_testing';
export type ConflictSeverity = 'hard' | 'soft' | 'none';
export type MUACategory = 'I' | 'II' | 'III';
export type FactCheckStatus = 'verified' | 'judgment' | 'unverified' | 'error';
export type OverlapStatus = 'within' | 'partial_overlap' | 'extrapolation' | 'outside' | 'insufficient_data';
export type DeterminationStatus = 'approved' | 'conditional' | 'rejected' | 'deferred' | 'cancelled' | 'unknown';
export type ClaimType = 'rating' | 'envelope' | 'determination' | 'mitigation' | 'constraint' | 'applicability' | 'prohibition';
export type MaterialClass = 'metal' | 'alloy' | 'polymer' | 'elastomer' | 'adhesive' | 'composite' | 'potting' | 'sealant' | 'ceramic' | 'coating' | 'lubricant' | 'other';
export type IssueCode =
  | 'FLAM'
  | 'TVS'
  | 'FS'
  | 'TOX'
  | 'OFFGAS'
  | 'O2_COMPAT'
  | 'HEE'
  | 'SCC'
  | 'CORR'
  | 'FRACTURE';
export type RelationshipType =
  | 'exact_match'
  | 'same_alloy_different_form'
  | 'same_alloy_different_temper'
  | 'family_match';

// ---------------------------------------------------------------------------
// Domain models (aligned to backend mira.mua.v7.models)
// ---------------------------------------------------------------------------

export interface MaterialResolution {
  input_text: string;
  status: ResolutionStatus;
  material_code: string | null;
  material_key: number | null;
  resolved_name: string | null;
  material_class: MaterialClass | null;
  family: string | null;
  suggestions: {
    name: string;
    spec: string;
    score: number;
    material_code?: string;
    material_key?: number | null;
    reason?: string;
  }[];
  is_process_sensitive: boolean;
  selection_method: string | null;
  selection_confidence: number | null;
}

export interface MaterialCodeCandidate {
  material_code: string;
  material_key: number | null;
  designation: string;
  form: string | null;
  condition: string | null;
  relationship: RelationshipType;
  match_score: number;
  rank: number;
}

export interface MaterialIdentity {
  input_text: string;
  canonical_name: string;
  family: string | null;
  material_class: MaterialClass | null;
  is_process_sensitive: boolean;
  form: string | null;
  condition: string | null;
  all_maptis_codes: MaterialCodeCandidate[];
  truncated: boolean;
  truncation_note: string | null;
}

export interface MaptisCodeRecommendation {
  recommended_code: string;
  recommended_key: number | null;
  recommended_designation: string;
  precedent_count: number;
  test_data_count: number;
  evidence_density_score: number;
  rationale: string;
  alternatives: {
    material_code: string;
    material_key: number | null;
    designation: string;
    relationship: RelationshipType;
    precedent_count: number;
    test_data_count: number;
  }[];
}

export interface MaterialStatsItem {
  label: string;
  count: number;
}

export interface MaterialCoverageStats {
  query_mode: string;
  total_muas: number;
  approved: number;
  conditional: number;
  rejected: number;
  deferred: number;
  top_issues: MaterialStatsItem[];
  top_env_types: MaterialStatsItem[];
  sample_muas: string[];
}

export interface MaterialIntelCandidate {
  material_code: string;
  material_key: number | null;
  designation: string;
  score: number;
  family: string | null;
  form: string | null;
  condition: string | null;
  is_mixed_record: boolean;
  differences: string[];
  coverage: MaterialCoverageStats;
}

export interface MaterialDisambiguationOption {
  value: string;
  label: string;
  candidate_count: number;
}

export interface MaterialDisambiguationQuestion {
  key: string;
  prompt: string;
  options: MaterialDisambiguationOption[];
  selected_value: string | null;
}

export interface MaterialIntelResponse {
  resolution: MaterialResolution;
  mixed_input: boolean;
  initial_candidate_count: number;
  candidate_count: number;
  candidates: MaterialIntelCandidate[];
  active_filters: Record<string, string>;
  disambiguation_questions: MaterialDisambiguationQuestion[];
  notes: string[];
}

export interface EnvironmentSpec {
  o2_percent: number;
  pressure_psia: number;
  temp_min_f: number;
  temp_max_f: number;
  medium: string;
  location: string;
  application: string;
}

export interface ProcessParams {
  cure_temp_f: number | null;
  cure_time_min: number | null;
  cure_pressure_psi: number | null;
  mix_ratio: string | null;
  layup_orientation: string | null;
}

export interface EvidenceRef {
  evidence_id: string;
  source_type: string;
  source_locator: {
    document_id: string | null;
    page: number | null;
    section: string | null;
    url: string | null;
  };
}

export interface PrecedentMatch {
  mua_number: string;
  material_designation: string;
  material_family: string | null;
  determination: DeterminationStatus;
  environment_description: string;
  o2_percent: number | null;
  pressure_psia: number | null;
  temp_min_f: number | null;
  temp_max_f: number | null;
  program: string | null;
  center: string | null;
  rationale_excerpt: string | null;
  relevance_score: number;
  is_supporting: boolean;
  is_conflicting: boolean;
  evidence_ref: EvidenceRef | null;
  relationship_explanation: string;
  supporting_rationale: string;
  non_applicability_caveat: string;
  physics_relevance: number;
  regulatory_relevance: number;
  // PG search fields (from mua_precedents_v7)
  appendix_b_code: string | null;
  closure_path: string | null;
  issues: string[];
  category_label: string | null;
  search_tier: number;
  relationship_type?: RelationshipType | null;
  source_maptis_code?: string | null;
}

export interface TestDataRecord {
  test_class: string;
  rating: string | null;
  test_number: number | null;
  report_number: string | null;
  is_current: boolean | null;
  test_date: string | null;
  test_medium?: string | null;
  medium_match?: boolean | null;
}

export interface BOKFinding {
  domain: string;
  source: string | null;
  title: string | null;
  section: string | null;
  page: number | null;
  relevance_score: number;
  excerpt: string;
}

export interface EnvelopeResult {
  overall_status: OverlapStatus;
  o2_status: OverlapStatus;
  pressure_status: OverlapStatus;
  temp_status: OverlapStatus;
  coverage_ratio: number;
  details: string[];
}

export interface GapIdentified {
  gap_id: string;
  dimension: string;
  description: string;
  severity: string;
  query_value: string | null;
  nearest_data: string | null;
  requires_review: boolean;
}

export interface ConflictFound {
  conflict_id: string;
  severity: ConflictSeverity;
  source_a: string;
  source_b: string;
  description: string;
  recommendation: string;
}

export interface DependencyWarning {
  cited_mua: string;
  depends_on: string;
  warning: string;
}

export interface EvidenceStrengthResult {
  score: number;
  band: EvidenceStrengthBand;
  components: Record<string, number>;
  penalties: Record<string, number>;
  explanation: string;
}

export interface InvestigationResult {
  material: MaterialResolution;
  material_identity?: MaterialIdentity | null;
  code_recommendation?: MaptisCodeRecommendation | null;
  environment: EnvironmentSpec;
  process_params: ProcessParams | null;
  supporting_precedents: PrecedentMatch[];
  conflicting_precedents: PrecedentMatch[];
  test_data: TestDataRecord[];
  bok_findings?: BOKFinding[];
  envelope: EnvelopeResult | null;
  conflicts: ConflictFound[];
  gaps: GapIdentified[];
  dependency_warnings: DependencyWarning[];
  evidence_strength: EvidenceStrengthResult;
  preliminary_category: MUACategory | null;
  banners: string[];
  is_novel_material: boolean;
}

// ---------------------------------------------------------------------------
// Review models
// ---------------------------------------------------------------------------

export interface PrecedentDecision {
  mua_number: string;
  decision: ReviewDecisionType;
  rationale: string | null;
}

export interface GapDecision {
  gap_id: string;
  decision: GapDecisionType;
  rationale: string;
}

export interface ConflictDecision {
  conflict_id: string;
  decision: ReviewDecisionType;
  rationale: string | null;
}

export interface ReviewDecisions {
  precedent_decisions: PrecedentDecision[];
  gap_decisions: GapDecision[];
  conflict_decisions: ConflictDecision[];
  all_items_reviewed: boolean;
  divergence_detected: boolean;
  confirmed_maptis_code?: string | null;
  confirmed_maptis_key?: number | null;
  confirmed_maptis_designation?: string | null;
  override_justification?: string | null;
}

// ---------------------------------------------------------------------------
// Draft models
// ---------------------------------------------------------------------------

export interface DraftSection {
  section_number: number;
  title: string;
  content: string;
  editable: boolean;
}

export interface FactCheckResult {
  claim_text: string;
  claim_type: ClaimType;
  status: FactCheckStatus;
  evidence_id: string | null;
  note: string | null;
}

export interface MUADraft {
  mua_id: string;
  sections: DraftSection[];
  category: MUACategory;
  evidence_strength: EvidenceStrengthResult;
  fact_check_results: FactCheckResult[];
  cited_precedents: string[];
  full_text: string;
}

// ---------------------------------------------------------------------------
// Finalization models
// ---------------------------------------------------------------------------

export interface MUAOutputType {
  category: string;
  output_format: 'full_mua' | 'miul_rationale_code';
  requires_mua_form: boolean;
  requires_reissue_on_update: boolean;
  approval_chain: string[];
  description: string;
}

export interface AppendixBEvaluation {
  eligible: boolean;
  code: string | null;
  code_description: string;
  rationale_template: string;
  citation: string;
  evidence: string[];
}

export interface CategoryRoutingResult {
  category: MUACategory;
  routing_basis: Record<string, unknown>[];
  required_approvals: string[];
  required_verifications: string[];
  authority_pack: string;
  authority_pack_version: string;
  output_type: MUAOutputType | null;
  appendix_b_evaluation: AppendixBEvaluation | null;
}

export interface FinalizedMUA {
  session_id: string;
  mua_id: string;
  material: MaterialResolution;
  environment: EnvironmentSpec;
  category: CategoryRoutingResult;
  evidence_strength: EvidenceStrengthResult;
  draft: MUADraft;
  reviewer: string;
  finalized_at: string;
  applied_standard_version: string;
  dependency_links: string[];
  center: string;
  audit_trail: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Session models
// ---------------------------------------------------------------------------

export interface SessionDetail {
  session_id: string;
  current_step: StepName;
  status: SessionStatus;
  material_input: string | null;
  center: string | null;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
  approved_cat3_codes: string[] | null;
  material_identity?: MaterialIdentity | null;
  investigation: InvestigationResult | null;
  review_decisions: ReviewDecisions | null;
  draft: MUADraft | null;
  finalized_mua: FinalizedMUA | null;
}

export interface SessionSummary {
  session_id: string;
  current_step: StepName;
  status: SessionStatus;
  material_input: string | null;
  center: string | null;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface MIULImportBucket {
  bucket_id: string;
  material_code: string;
  suggested_material: string;
  trigger_signature: string;
  issue_codes: IssueCode[];
  environment_raw: string;
  part_count: number;
  risk_band: string;
  likely_category: string;
  category_reasons: string[];
  fluid_types: string[];
  sample_part_numbers: string[];
  sample_part_descriptions: string[];
  suggested_environment: EnvironmentSpec;
}

export interface MIULImportResponse {
  filename: string;
  total_parts: number;
  non_a_parts: number;
  bucket_count: number;
  buckets: MIULImportBucket[];
}

// ---------------------------------------------------------------------------
// Request types
// ---------------------------------------------------------------------------

export interface InvestigateRequest {
  session_id?: string | null;
  material: string;
  material_code?: string | null;
  material_key?: number | null;
  resolved_name?: string | null;
  form?: string | null;
  condition?: string | null;
  environment: EnvironmentSpec;
  process_params?: ProcessParams | null;
  issue_codes?: IssueCode[] | null;
  approved_cat3_codes?: string[] | null;
  program?: string;
  hardware?: string;
  miul_ref?: string;
  center?: string;
}

export interface SaveReviewRequest {
  session_id: string;
  decisions: ReviewDecisions;
}

export interface FinalizeRequest {
  session_id: string;
  reviewer: string;
  export_format?: string;
}

// ---------------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------------

class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
    message?: string,
  ) {
    super(message ?? `API error ${status}`);
    this.name = 'ApiError';
  }
}

type RequestOptions = RequestInit & {
  timeoutMs?: number;
};

async function request<T>(path: string, options?: RequestOptions): Promise<T> {
  const url = `${API_BASE}${path}`;

  const { timeoutMs, signal: upstreamSignal, ...fetchOptions } = options ?? {};
  const timeoutController = timeoutMs ? new AbortController() : null;
  let relayAbort: (() => void) | null = null;

  if (timeoutController && upstreamSignal) {
    if (upstreamSignal.aborted) {
      timeoutController.abort();
    } else {
      relayAbort = () => timeoutController.abort();
      upstreamSignal.addEventListener('abort', relayAbort, { once: true });
    }
  }

  const timeoutId = timeoutMs
    ? setTimeout(() => timeoutController?.abort(), timeoutMs)
    : null;

  try {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json' },
      ...fetchOptions,
      signal: timeoutController?.signal ?? upstreamSignal,
    });
    if (!res.ok) {
      let body: unknown;
      try {
        body = await res.json();
      } catch {
        body = await res.text();
      }
      const detailMessage =
        body &&
        typeof body === 'object' &&
        'detail' in body &&
        typeof (body as { detail?: unknown }).detail === 'string'
          ? (body as { detail: string }).detail
          : null;
      throw new ApiError(
        res.status,
        body,
        detailMessage ?? `API ${res.status}: ${path}`,
      );
    }
    return res.json() as Promise<T>;
  } catch (error) {
    if (timeoutMs && error instanceof DOMException && error.name === 'AbortError') {
      throw new Error(`Request timed out: ${path}`);
    }
    throw error;
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
    if (relayAbort && upstreamSignal) {
      upstreamSignal.removeEventListener('abort', relayAbort);
    }
  }
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export interface IssueCodeInfo {
  code: IssueCode;
  label: string;
  auto_detected: boolean;
}

export async function resolveMaterial(
  material: string,
  form?: string | null,
  condition?: string | null,
): Promise<{ resolution: MaterialResolution; identity?: MaterialIdentity | null }> {
  return request('/resolve-material', {
    method: 'POST',
    body: JSON.stringify({ material, form: form ?? null, condition: condition ?? null }),
  });
}

export async function getMaterialIntel(
  material: string,
  materialCode?: string | null,
  topN = 8,
  filters?: Record<string, string>,
): Promise<MaterialIntelResponse> {
  return request('/material-intel', {
    method: 'POST',
    body: JSON.stringify({
      material,
      material_code: materialCode ?? null,
      top_n: topN,
      filters: filters ?? {},
    }),
  });
}

export async function previewIssues(
  env: Partial<EnvironmentSpec>,
): Promise<{ issues: IssueCodeInfo[] }> {
  return request('/preview-issues', {
    method: 'POST',
    body: JSON.stringify({
      o2_percent: env.o2_percent ?? 21,
      pressure_psia: env.pressure_psia ?? 14.7,
      temp_min_f: env.temp_min_f ?? 60,
      temp_max_f: env.temp_max_f ?? 85,
      medium: env.medium ?? 'Air',
      location: env.location ?? 'habitable',
    }),
  });
}

export async function investigate(
  req: InvestigateRequest,
): Promise<{ session_id: string; status: string }> {
  return request('/investigate', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

export interface InvestigationStatus {
  session_id: string;
  status: 'investigating' | 'complete' | 'failed' | 'idle';
  progress: number;
  current_step: StepName | null;
  session_status: SessionStatus | null;
  error: string | null;
}

export async function getInvestigationStatus(
  sessionId: string,
  timeoutMs = 0,
): Promise<InvestigationStatus> {
  return request(
    `/session/${encodeURIComponent(sessionId)}/status`,
    timeoutMs > 0 ? { timeoutMs } : undefined,
  );
}

export async function saveReviewDecisions(
  req: SaveReviewRequest,
): Promise<{ session_id: string; can_generate_draft: boolean; unreviewed_count: number }> {
  return request('/review-decisions', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

export async function generateDraft(
  sessionId: string,
): Promise<{ session_id: string; draft: MUADraft }> {
  return request('/generate-draft', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId }),
  });
}

export async function finalize(
  req: FinalizeRequest,
): Promise<{ session_id: string; mua: FinalizedMUA; export_text: string | null }> {
  return request('/finalize', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

export async function getSession(
  sessionId: string,
  timeoutMs = 0,
): Promise<SessionDetail> {
  return request(
    `/session/${encodeURIComponent(sessionId)}`,
    timeoutMs > 0 ? { timeoutMs } : undefined,
  );
}

export async function listSessions(): Promise<{ sessions: SessionSummary[]; total: number }> {
  return request('/sessions');
}

export async function deleteSession(
  sessionId: string,
): Promise<{ session_id: string; status: string }> {
  return request(`/session/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  });
}

export async function importMIULWorkbook(
  file: File,
): Promise<MIULImportResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(`${API_BASE}/import-miul`, {
    method: 'POST',
    body: formData,
  });

  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = await res.text();
    }
    const detailMessage =
      body &&
      typeof body === 'object' &&
      'detail' in body &&
      typeof (body as { detail?: unknown }).detail === 'string'
        ? (body as { detail: string }).detail
        : null;
    throw new ApiError(
      res.status,
      body,
      detailMessage ?? `API ${res.status}: /import-miul`,
    );
  }

  return res.json() as Promise<MIULImportResponse>;
}
