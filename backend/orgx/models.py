from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

Version = Literal['before', 'after']
FindingType = Literal['PRESERVED', 'MOVED', 'POTENTIAL_GAP', 'POTENTIAL_DUPLICATE', 'POTENTIAL_AUTHORITY_CONFLICT', 'REQUIRES_HUMAN_REVIEW']

class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

class SourceSpan(Model):
    id: str
    document_id: str
    version: Version
    paragraph_id: str
    section: str
    clause: str
    exact_text: str
    locator: str
    style: str = ''

class Document(Model):
    id: str
    version: Version
    name: str
    sha256: str
    format: str
    spans: list[SourceSpan]
    warnings: list[str] = Field(default_factory=list)

class Unit(Model):
    id: str
    key: str
    name: str
    version: Version
    kind: Literal['department', 'role', 'collective', 'unresolved']
    source_span_ids: list[str]
    department_ids: list[str] = Field(default_factory=list)

class FunctionClaim(Model):
    id: str
    version: Version
    unit_id: str
    action: str
    object: str
    scope: str
    authority: Literal['duty', 'right', 'prohibition', 'unknown']
    text: str
    context_text: str
    source_span_ids: list[str]
    extraction: Literal['explicit', 'unresolved']

class MatchCandidate(Model):
    before_claim: str
    after_claim: str
    relation: Literal['EXACT', 'LEXICAL', 'LLM_CANDIDATE']
    confidence: float
    evidence: list[str]

class SearchResult(Model):
    id: str
    before_claim: str
    after_document_id: str
    query: str
    method: str
    searched_span_ids: list[str]
    candidates: list[MatchCandidate]
    exact_match_count: int
    exhaustive: bool
    limitation: str

class Evidence(Model):
    text: str
    source_span_ids: list[str] = Field(default_factory=list)
    search_result_ids: list[str] = Field(default_factory=list)

class Finding(Model):
    id: str
    type: FindingType
    confidence: Literal['high', 'medium', 'low']
    title: str
    explanation: str
    before_claim_id: Optional[str]
    after_claim_ids: list[str]
    evidence_for: list[Evidence]
    evidence_against: list[Evidence]
    review_status: Literal['PENDING'] = 'PENDING'
    source_span_ids: list[str]
    search_result_ids: list[str]
    rule_id: str
    concern: str = ''

class OrganizationalIR(Model):
    documents: list[Document]
    units: list[Unit]
    claims: list[FunctionClaim]

class UnitChange(Model):
    id: str
    status: Literal['RETAINED', 'NEW', 'REORGANIZED', 'REQUIRES_HUMAN_REVIEW']
    title: str
    detail: str
    source_span_ids: list[str]

class AuditRecord(Model):
    id: str
    engine_version: str
    policy_version: str
    ir: OrganizationalIR
    unit_changes: list[UnitChange]
    search_results: list[SearchResult]
    findings: list[Finding]
    conclusion: list[Evidence]
    coverage: dict[str, int]
    limitations: list[str]
