const API_BASE = '/api/mua/v7';

// ---------------------------------------------------------------------------
// Enums / literal types
// ---------------------------------------------------------------------------

export type EvidenceStrengthBand = 'strong' | 'moderate' | 'weak' | 'insufficient';
export type StepName = 'define' | 'investigate' | 'review' | 'draft' | 'finalize';
export type ResolutionStatus = 'resolved' | 'fuzzy' | 'unresolved';
export type ReviewDecisionType = 'include_supporting' | 'include_context' | 'exclude';
export type GapDecisionType = 'accept_with_rationale' | 'flag_for_testing';
export type ConflictSeverity = 'hard' | 'soft' | 'none';
export type MUACategory = 'I' | 'II' | 'III';
export type FactCheckStatus = 'verified' | 'judgment' | 'unverified';

// ---------------------------------------------------------------------------
// Domain models
// ---------------------------------------------------------------------------

export interface MaterialResolution {
  query: string;
  status: ResolutionStatus;
  resolved_name: string | null;
  resolved_spec: string | null;
  candidates: { name: string; spec: string; score: number }[];
  warnings: string[];
}

export interface EnvironmentSpec {
  oxygen_pct: number;
  pressure_psia: number;
  temp_min_f: number;
  temp_max_f: number;
  medium: string;
  location: 'habitable' | 'non-habitable' | 'external';
}

export interface ProcessParams {
  cure_temp_f: number | null;
  cure_time_hrs: number | null;
  post_cure_temp_f: number | null;
  bond_area_sqin: number | null;
  substrate_material: string | null;
}

export interface PrecedentMatch {
  id: string;
  mua_number: string;
  material: string;
  environment_summary: string;
  determination: string;
  category: MUACategory;
  relevance_score: number;
  relationship_explanation: string;
  is_supporting: boolean;
  is_conflicting: boolean;
  conflict_severity: ConflictSeverity;
  conflict_explanation: string | null;
  physics_relevant: boolean;
  regulatory_relevant: boolean;
  date_issued: string | null;
  expired: boolean;
}

export interface TestDataRecord {
  id: string;
  test_type: string;
  material: string;
  environment: string;
  result_summary: string;
  pass: boolean;
  date: string;
  expired: boolean;
  source: string;
}

export interface GapIdentified {
  id: string;
  description: string;
  severity: 'critical' | 'moderate' | 'minor';
  category: string;
  suggested_action: string;
}

export interface ConflictFound {
  id: string;
  precedent_a_id: string;
  precedent_b_id: string;
  description: string;
  severity: ConflictSeverity;
  suggested_resolution: string;
}

export interface EvidenceStrengthResult {
  band: EvidenceStrengthBand;
  score: number;
  max_score: number;
  components: {
    precedent_coverage: number;
    test_data_quality: number;
    environment_match: number;
    recency: number;
    conflict_penalty: number;
  };
  explanation: string;
}

export interface InvestigationResult {
  precedents: PrecedentMatch[];
  test_data: TestDataRecord[];
  gaps: GapIdentified[];
  conflicts: ConflictFound[];
  evidence_strength: EvidenceStrengthResult;
  novel_material: boolean;
  suggested_category: MUACategory;
}

// ---------------------------------------------------------------------------
// Review models
// ---------------------------------------------------------------------------

export interface PrecedentReviewDecision {
  precedent_id: string;
  decision: ReviewDecisionType;
  rationale: string;
  diverges_from_evidence: boolean;
}

export interface GapReviewDecision {
  gap_id: string;
  decision: GapDecisionType;
  rationale: string;
}

export interface ConflictReviewDecision {
  conflict_id: string;
  decision: ReviewDecisionType;
  rationale: string;
}

export interface ReviewDecisions {
  precedent_decisions: PrecedentReviewDecision[];
  gap_decisions: GapReviewDecision[];
  conflict_decisions: ConflictReviewDecision[];
}

// ---------------------------------------------------------------------------
// Draft models
// ---------------------------------------------------------------------------

export interface DraftSection {
  number: number;
  title: string;
  content: string;
  editable: boolean;
}

export interface FactCheckResult {
  claim: string;
  status: FactCheckStatus;
  source: string | null;
  section_number: number;
  paragraph_index: number;
}

export interface MUADraft {
  sections: DraftSection[];
  fact_checks: FactCheckResult[];
  category: MUACategory;
  process_constraints: string[] | null;
}

// ---------------------------------------------------------------------------
// Finalized models
// ---------------------------------------------------------------------------

export interface AuditTrail {
  items_reviewed: number;
  gap_decisions: number;
  conflicts_addressed: number;
  edits_made: number;
  fact_checks_verified: number;
  fact_checks_judgment: number;
  fact_checks_unverified: number;
  divergences: number;
}

export interface FinalizedMUA {
  mua_number: string;
  category: MUACategory;
  material: string;
  environment: EnvironmentSpec;
  evidence_strength: EvidenceStrengthResult;
  sections: DraftSection[];
  audit_trail: AuditTrail;
  reviewer_name: string;
  review_date: string;
  standard_version: string;
  certification_text: string;
}

// ---------------------------------------------------------------------------
// Session models
// ---------------------------------------------------------------------------

export interface SessionState {
  session_id: string;
  current_step: StepName;
  material: string | null;
  environment: EnvironmentSpec | null;
  process_params: ProcessParams | null;
  investigation: InvestigationResult | null;
  review_decisions: ReviewDecisions | null;
  draft: MUADraft | null;
  finalized: FinalizedMUA | null;
  application_description: string | null;
  program: string | null;
  hardware: string | null;
  miul_ref: string | null;
}

export interface SessionSummary {
  session_id: string;
  material: string | null;
  current_step: StepName;
  category: MUACategory | null;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Request types
// ---------------------------------------------------------------------------

export interface InvestigateRequest {
  session_id?: string | null;
  material: string;
  environment: EnvironmentSpec;
  process_params?: ProcessParams | null;
  application_description?: string;
  program?: string;
  hardware?: string;
  miul_ref?: string;
}

export interface SaveReviewRequest {
  session_id: string;
  decisions: ReviewDecisions;
}

export interface FinalizeRequest {
  session_id: string;
  reviewer_name: string;
  section_edits?: Record<number, string>;
  export_format?: 'text' | 'nasa' | null;
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

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = await res.text();
    }
    throw new ApiError(res.status, body, `API ${res.status}: ${path}`);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export async function resolveMaterial(
  material: string,
): Promise<{ resolution: MaterialResolution }> {
  return request('/resolve-material', {
    method: 'POST',
    body: JSON.stringify({ material }),
  });
}

export async function investigate(
  req: InvestigateRequest,
): Promise<{ session_id: string; investigation: InvestigationResult }> {
  return request('/investigate', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

export async function saveReviewDecisions(
  req: SaveReviewRequest,
): Promise<{ session_id: string; can_generate_draft: boolean; unreviewed_count: number }> {
  return request('/review', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

export async function generateDraft(
  sessionId: string,
): Promise<{ session_id: string; draft: MUADraft }> {
  return request(`/draft/${encodeURIComponent(sessionId)}`, {
    method: 'POST',
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

export async function getSession(sessionId: string): Promise<SessionState> {
  return request(`/session/${encodeURIComponent(sessionId)}`);
}

export async function listSessions(): Promise<SessionSummary[]> {
  return request('/sessions');
}
