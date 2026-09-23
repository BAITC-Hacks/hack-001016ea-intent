"""Typed, evidence-linked responsibility history and organizational checks."""
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class DebugModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Relation = Literal["PRESERVED", "MOVED", "SPLIT", "MERGED", "DUPLICATED", "POTENTIAL_GAP", "POTENTIAL_AUTHORITY_CONFLICT", "UNKNOWN"]


class Responsibility(DebugModel):
    id: str
    lineage_id: str
    before_claim_ids: list[str]
    after_claim_ids: list[str]
    candidate_claim_ids: list[str]
    relation: Relation
    basis: Literal["DOCUMENTARY_RULE", "COMPOSITION_HYPOTHESIS", "UNRESOLVED"]
    finding_ids: list[str]
    source_span_ids: list[str]
    explanation: str
    requires_human_review: bool = True


class OrganizationalTest(DebugModel):
    id: str
    test: Literal["OWNER_CONTINUITY", "RESPONSIBILITY_TRANSFER", "SCOPE_CONTINUITY", "DUPLICATE_OWNERSHIP", "AUTHORITY_CONFLICT", "SPLIT_MERGE", "SOURCE_INTEGRITY"]
    responsibility_id: str
    lineage_id: str
    status: Literal["PASS", "REVIEW", "FAIL", "NOT_APPLICABLE"]
    detail: str
    source_span_ids: list[str]
    finding_ids: list[str] = Field(default_factory=list)


class CandidateAssessment(DebugModel):
    claim_id: str
    owner: str
    action_matches: bool
    scope_matches: bool
    authority_matches: bool
    verdict: Literal["COMPATIBLE", "PARTIAL", "REJECTED"]
    reasons: list[str]
    source_span_ids: list[str]


class DebugStep(DebugModel):
    sequence: int
    tool: str
    hypothesis: Relation
    detail: str
    source_span_ids: list[str]
    claim_ids: list[str] = Field(default_factory=list)
    searched_span_ids: list[str] = Field(default_factory=list)


class DebugInvestigation(DebugModel):
    lineage_id: str
    responsibility_id: str
    mode: Literal["deterministic_investigation"] = "deterministic_investigation"
    initial_hypothesis: Relation
    final_hypothesis: Relation
    revised: bool
    steps: list[DebugStep]
    candidates: list[CandidateAssessment]
    source_span_ids: list[str]
    requires_human_review: bool = True
    limitation: str
