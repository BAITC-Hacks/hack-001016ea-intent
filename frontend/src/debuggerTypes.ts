export type Relation = "PRESERVED" | "MOVED" | "SPLIT" | "MERGED" | "DUPLICATED" | "POTENTIAL_GAP" | "POTENTIAL_AUTHORITY_CONFLICT" | "UNKNOWN";
export interface Responsibility {
  id: string; lineage_id: string; before_claim_ids: string[]; after_claim_ids: string[];
  candidate_claim_ids: string[]; relation: Relation; basis: string; finding_ids: string[];
  source_span_ids: string[]; explanation: string; requires_human_review: boolean;
}
export interface OrgTest {
  id: string; test: string; responsibility_id: string; lineage_id: string;
  status: "PASS" | "REVIEW" | "FAIL" | "NOT_APPLICABLE";
  detail: string; source_span_ids: string[]; finding_ids: string[];
}
export interface TestData {summary: Record<string,number>; responsibilities: Responsibility[]; tests: OrgTest[]}
export interface DebugTrace {
  mode: string; initial_hypothesis: Relation; final_hypothesis: Relation; revised: boolean;
  steps: {sequence:number; tool:string; hypothesis:Relation; detail:string; source_span_ids:string[]; searched_span_ids:string[]}[];
  candidates: {claim_id:string; owner:string; verdict:string; reasons:string[]; source_span_ids:string[]}[];
  requires_human_review:boolean; limitation:string;
}
