const API_BASE = '/api/mua/matchmaker';

export type IssueCode = 'FLAM' | 'TOX' | 'O2' | 'HEE' | 'SCC' | 'CORR' | 'TVS' | 'FLUID';
export type IssueStatus = 'pending' | 'in_progress' | 'done' | 'manual_required';
export type IssueOutcome = 'PASS' | 'CAT_III' | 'CAT_I_II';
export type ExportMode = 'draft' | 'board_ready';

export interface EnvironmentSpec {
  o2_percent: number;
  pressure_psia: number;
  temp_min_f: number;
  temp_max_f: number;
  medium: string;
  location: string;
  application: string;
}

export interface MaterialResolution {
  input_text: string;
  status: 'resolved' | 'fuzzy' | 'unresolved';
  material_code: string | null;
  material_key: number | null;
  resolved_name: string | null;
  family: string | null;
  material_class: string | null;
  is_process_sensitive: boolean;
}

export interface PrecedentMatch {
  mua_number: string;
  determination: string;
  rationale_text: string | null;
  material_designation: string | null;
  material_family: string | null;
  environment: string;
  o2_percent: number | null;
  pressure_psia: number | null;
  temp_min_f: number | null;
  temp_max_f: number | null;
  issue_codes: IssueCode[];
  source_issue_codes: string[];
  relevance_score: number;
  category_label: string | null;
}

export interface RationalePhrase {
  phrase: string;
  mua_number: string;
  score: number;
}

export interface ConflictPair {
  approved: PrecedentMatch;
  negative: PrecedentMatch;
  overlap_description: string;
}

export interface IssueState {
  issue: string;
  status: IssueStatus;
  outcome: IssueOutcome | null;
  selected_code: string | null;
  candidate_codes: string[];
  answers: Record<string, unknown>;
  rationale: string | null;
  manual_disposition: string | null;
  out_of_scope: boolean;
  requirement_ref: string | null;
  matches: PrecedentMatch[];
  phrases: RationalePhrase[];
  conflicts: ConflictPair[];
  warnings: string[];
  last_question_id: string | null;
}

export interface MatchmakerSession {
  session_id: string;
  created_at: string;
  updated_at: string;
  rule_pack_version: string;
  material_input: string;
  material_resolution: MaterialResolution;
  environment: EnvironmentSpec;
  application_description: string;
  issues: Record<string, IssueState>;
  banners: string[];
  category: 'I' | 'II' | null;
  category_reasons: string[];
  nonconformance_redirected: boolean;
  redirect_reason: string | null;
  events: Array<Record<string, unknown>>;
}

export interface SessionSummary {
  session_id: string;
  material_input: string;
  updated_at: string;
  issue_count: number;
  done_count: number;
  manual_count: number;
  category: 'I' | 'II' | null;
}

export interface SessionListResponse {
  sessions: SessionSummary[];
  total: number;
  rule_pack_version: string;
}

export interface IssueQuestionResponse {
  issue: string;
  status: IssueStatus;
  outcome: IssueOutcome | null;
  selected_code: string | null;
  candidate_codes: string[];
  next_question: Record<string, unknown> | null;
  answers: Record<string, unknown>;
  manual_required: boolean;
  manual_message: string | null;
}

export interface MatchResponse {
  issue: string;
  matches: PrecedentMatch[];
  phrases: RationalePhrase[];
  conflicts: ConflictPair[];
  total: number;
}

export interface ExportResponse {
  export_ready: boolean;
  mode: ExportMode;
  blockers: Array<Record<string, unknown>>;
  missing_fields: Array<Record<string, unknown>>;
  suggestion?: string;
  rule_pack_version: string;
  generated_at: string;
  form_text?: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    const message = payload?.detail || `Request failed with status ${response.status}`;
    throw new Error(message);
  }
  return payload as T;
}

export function pingMatchmaker(): Promise<{ status: string; domain: string; rule_pack: string }> {
  return request('/ping');
}

export function createSession(payload: {
  material: string;
  environment: EnvironmentSpec;
  application_description: string;
  deviation_type?: 'material_selection' | 'manufacturing_nonconformance';
  user?: string;
}): Promise<MatchmakerSession> {
  return request('/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function listSessions(): Promise<SessionListResponse> {
  return request('/sessions');
}

export function getSession(sessionId: string): Promise<MatchmakerSession> {
  return request(`/sessions/${sessionId}`);
}

export function deleteSession(sessionId: string): Promise<{ session_id: string; deleted: boolean }> {
  return request(`/sessions/${sessionId}`, { method: 'DELETE' });
}

export function getIssueQuestions(sessionId: string, issue: string): Promise<IssueQuestionResponse> {
  return request(`/sessions/${sessionId}/issues/${issue}/questions`);
}

export function submitIssueAnswer(
  sessionId: string,
  issue: string,
  payload: {
    question_id?: string;
    answer?: unknown;
    answers?: Record<string, unknown>;
    selected_code?: string;
  },
): Promise<IssueQuestionResponse> {
  return request(`/sessions/${sessionId}/issues/${issue}/answer`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function runIssueMatch(sessionId: string, issue: string): Promise<MatchResponse> {
  return request(`/sessions/${sessionId}/issues/${issue}/match`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
}

export function saveIssueRationale(
  sessionId: string,
  issue: string,
  payload: {
    rationale?: string;
    selected_phrases?: string[];
    manual_disposition?: string;
  },
): Promise<IssueState> {
  return request(`/sessions/${sessionId}/issues/${issue}/rationale`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function exportSession(sessionId: string, mode: ExportMode): Promise<ExportResponse> {
  return request(`/sessions/${sessionId}/export?mode=${mode}`);
}

export async function importMiul(file: File): Promise<{ filename: string; groups: number; created_sessions: string[] }> {
  const form = new FormData();
  form.append('file', file);
  const response = await fetch(`${API_BASE}/batch/import-miul`, {
    method: 'POST',
    body: form,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload?.detail || 'MIUL import failed');
  }
  return payload;
}

export function bulkApplyCode(payload: {
  session_ids: string[];
  issue: string;
  code: string;
  confirmation: string;
}): Promise<Record<string, unknown>> {
  return request('/batch/bulk-apply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

