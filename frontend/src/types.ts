export type FindingType =
  | "PRESERVED"
  | "MOVED"
  | "POTENTIAL_GAP"
  | "POTENTIAL_DUPLICATE"
  | "POTENTIAL_AUTHORITY_CONFLICT"
  | "REQUIRES_HUMAN_REVIEW";
export interface Span {
  id: string;
  document_id: string;
  version: "before" | "after";
  paragraph_id: string;
  section: string;
  clause: string;
  exact_text: string;
  locator: string;
}
export interface Unit {
  id: string;
  name: string;
  key: string;
  kind: string;
  version: string;
  source_span_ids: string[];
  department_ids: string[];
}
export interface Claim {
  id: string;
  unit_id: string;
  text: string;
  version: string;
  scope: string;
  authority: string;
  context_text: string;
  source_span_ids: string[];
}
export interface Evidence {
  text: string;
  source_span_ids: string[];
  search_result_ids: string[];
}
export interface Finding {
  id: string;
  type: FindingType;
  title: string;
  explanation: string;
  confidence: string;
  review_status: string;
  before_claim_id: string | null;
  after_claim_ids: string[];
  source_span_ids: string[];
  search_result_ids: string[];
  evidence_for: Evidence[];
  evidence_against: Evidence[];
  rule_id: string;
  concern: string;
}
export interface Search {
  id: string;
  query: string;
  before_claim: string | null;
  searched_version: "before" | "after";
  searched_document_ids: string[];
  matched_span_ids: string[];
  searched_span_ids: string[];
  exact_match_count: number;
  exhaustive: boolean;
  limitation: string;
  candidates: {
    before_claim: string;
    after_claim: string;
    relation: string;
    confidence: number;
    evidence: string[];
  }[];
}
export interface Audit {
  id: string;
  engine_version: string;
  policy_version: string;
  ir: {
    documents: {
      id: string;
      name: string;
      version: string;
      sha256: string;
      format: string;
      spans: Span[];
      warnings: string[];
    }[];
    units: Unit[];
    claims: Claim[];
  };
  unit_changes: {
    id: string;
    status: string;
    title: string;
    detail: string;
    source_span_ids: string[];
  }[];
  findings: Finding[];
  search_results: Search[];
  coverage: Record<string, number>;
  conclusion: Evidence[];
  limitations: string[];
  matrix: MatrixRow[];
  investigations: {finding_id: string; steps: {action: string; detail: string; source_span_ids: string[]; search_result_ids: string[]}[]}[];
  recommendations: {priority: string; action: string; finding_ids: string[]; source_span_ids: string[]}[];
}
export interface MatrixRow {
  id: string;
  before_claim_id: string | null;
  after_claim_ids: string[];
  finding_ids: string[];
  status: string;
  source_span_ids: string[];
  search_result_ids: string[];
}
export interface Candidate {
  before_claim: string;
  after_claim: string;
  relation: string;
  confidence: number;
  evidence: string[];
  checks?: {same_owner: boolean; same_modality: boolean; same_context: boolean};
}
export interface AIInvestigation {
  finding_id: string;
  mode: string;
  status: string;
  message: string;
  cached?: boolean;
  candidates: Candidate[];
  steps: {number: number; tool: string; arguments: Record<string,unknown>; status: string; result: Record<string, unknown>; source_span_ids: string[]}[];
}
export interface Review {
  id: number;
  finding_id: string;
  status: string;
  actor: string;
  note: string;
  created_at: string;
}
