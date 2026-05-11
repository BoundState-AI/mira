export interface UserIdentity {
  sub: string;
  username: string;
  email: string;
  role: string;
  groups: string[];
  itar_access: string;
  us_person_verified: boolean | null;
  edipi: string;
  piv_subject: string;
  agency: string;
  auth_method: string;
}

export type AuditTurnModality = "text" | "voice";

export interface AuditRecord {
  audit_id: string;
  timestamp: string;
  session_id: string;
  user_input: string;
  parsed_entities: Record<string, unknown>;
  normalized_units: Record<string, string>;
  coarse_intent: string;
  fine_routing: string;
  task_mode: string;
  routing_confidence: number;
  engines_invoked: string[];
  engine_versions: Record<string, string>;
  engine_status: string;
  source_citations: string[];
  assumptions: string[];
  missing_inputs: string[];
  llm_model_used: string | null;
  response_hash: string;
  artifact_generated: boolean;
  follow_ups_offered: string[];
  follow_ups_taken: string[];
  module_context: Record<string, unknown> | null;
  authority_basis: string[];
  envelope_json: Record<string, unknown>;
  error_detail: string | null;
  user_identity: UserIdentity | null;
  turn_modality: AuditTurnModality;
  client_metadata: Record<string, unknown>;
}

export interface RecentAuditResponse {
  user_sub: string | null;
  count: number;
  records: AuditRecord[];
}
