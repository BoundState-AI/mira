export interface TocrSubTask {
  sub_task_id: string;
  description: string;
  skills: string[];
  labor_categories: string[];
  funding?: number | null;
  wbs_code?: string | null;
  charge_code?: string | null;
  participating_team: string[];
  deliverables: string[];
}

export interface TocrTaskOrder {
  task_order_number: string;
  revision_number: string;
  revision_status: string;
  title: string;
  task_order_description: string;
  scope_text: string;
  summary_of_changes: string;
  sub_tasks: TocrSubTask[];
  funding_table: Array<Record<string, unknown>>;
  total_funding?: number | null;
  quality_plan?: Record<string, unknown> | null;
  emergency_designation: boolean;
  emergency_justification: string;
  agency_comments: string;
  parser_confidence: string;
  source_format: string;
  raw_fields: Record<string, unknown>;
}

export interface TocrFinding {
  finding_id: string;
  rule_id: string;
  rule_title: string;
  severity: string;
  review_priority: string;
  finding: string;
  guidance?: string | null;
  remediation?: string | null;
  evidence?: Record<string, unknown> | null;
}

export interface TocrComplianceScore {
  raw_score: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  verdict: string;
}

export interface TocrRemediationStep {
  finding_id: string;
  rule_id: string;
  title: string;
  why_it_matters: string;
  how_to_fix: string;
  who_needs_to_act: string;
  review_priority: string;
}

export interface TocrRemediationPlan {
  summary: string;
  steps: TocrRemediationStep[];
}

export interface TocrComplianceReport {
  report_id: string;
  generated_at: string;
  prior_revision: string;
  proposed_revision: string;
  findings: TocrFinding[];
  score?: TocrComplianceScore | null;
  remediation_plan?: TocrRemediationPlan | null;
  parser_confidence: string;
  rules_evaluated: number;
  rules_fired: number;
  rules_suppressed: number;
  assumptions: string[];
  input_fingerprint: string;
  total_changes_detected: number;
  material_changes_detected: number;
  undisclosed_changes: number;
  disclosed_changes: number;
}

export interface TocrGuidanceEntry {
  what_it_means: string;
  why_it_matters: string;
  what_to_do: string;
  who_needs_to_act: string;
}

export interface TocrGuidancePack {
  pack_id: string;
  version: string;
  spec: string;
  description: string;
  entries: Record<string, TocrGuidanceEntry>;
}

export interface TocrSharedConfig {
  agency: string;
  center?: string;
  vehicle?: string;
  localPolicyPack?: string;
  contractTypes: string[];
  clausesPresent: string[];
  revisionStatus?: string;
  useSonnet: boolean;
}

export interface TocrScanRequest extends TocrSharedConfig {
  sourceFile: File;
  parserHint: string;
}

export interface TocrReviewRequest extends TocrSharedConfig {
  priorFile: File;
  proposedFile: File;
  priorParserHint: string;
  proposedParserHint: string;
}

export interface TocrScanResponse {
  mode: "scan";
  parser_selected: string;
  parsed_task_order: TocrTaskOrder;
  report: TocrComplianceReport;
  guidance: Record<string, TocrGuidanceEntry>;
}

export interface TocrReviewResponse {
  mode: "review";
  prior_parser_selected: string;
  proposed_parser_selected: string;
  prior_task_order: TocrTaskOrder;
  proposed_task_order: TocrTaskOrder;
  report: TocrComplianceReport;
  guidance: Record<string, TocrGuidanceEntry>;
}

function appendSharedConfig(formData: FormData, config: TocrSharedConfig) {
  formData.append("agency", config.agency);
  if (config.center?.trim()) {
    formData.append("center", config.center.trim());
  }
  if (config.vehicle?.trim()) {
    formData.append("vehicle", config.vehicle.trim());
  }
  if (config.localPolicyPack?.trim()) {
    formData.append("local_policy_pack", config.localPolicyPack.trim());
  }
  formData.append("contract_types", config.contractTypes.join(","));
  formData.append("clauses_present", config.clausesPresent.join(","));
  if (config.revisionStatus?.trim()) {
    formData.append("revision_status", config.revisionStatus.trim());
  }
  formData.append("use_sonnet", String(config.useSonnet));
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      if (typeof payload?.detail === "string") {
        detail = payload.detail;
      }
    } catch {
      // Ignore JSON parsing errors for failed responses.
    }
    throw new Error(detail);
  }
  return response.json();
}

export async function tocrGetGuidance(): Promise<TocrGuidancePack> {
  const response = await fetch("/api/tocr/guidance");
  return parseJsonResponse<TocrGuidancePack>(response);
}

export async function tocrScanTaskOrder(request: TocrScanRequest): Promise<TocrScanResponse> {
  const formData = new FormData();
  formData.append("source_file", request.sourceFile);
  formData.append("parser_hint", request.parserHint);
  appendSharedConfig(formData, request);

  const response = await fetch("/api/tocr/scan", {
    method: "POST",
    body: formData,
  });
  return parseJsonResponse<TocrScanResponse>(response);
}

export async function tocrReviewTaskOrders(request: TocrReviewRequest): Promise<TocrReviewResponse> {
  const formData = new FormData();
  formData.append("prior_file", request.priorFile);
  formData.append("proposed_file", request.proposedFile);
  formData.append("prior_parser_hint", request.priorParserHint);
  formData.append("proposed_parser_hint", request.proposedParserHint);
  appendSharedConfig(formData, request);

  const response = await fetch("/api/tocr/review", {
    method: "POST",
    body: formData,
  });
  return parseJsonResponse<TocrReviewResponse>(response);
}
