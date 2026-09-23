from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator
from .debugger_models import Responsibility, OrganizationalTest

Version = Literal["before", "after"]
FindingType = Literal[
    "PRESERVED",
    "MOVED",
    "POTENTIAL_GAP",
    "POTENTIAL_DUPLICATE",
    "POTENTIAL_AUTHORITY_CONFLICT",
    "REQUIRES_HUMAN_REVIEW",
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceSpan(Model):
    id: str
    document_id: str
    version: Version
    paragraph_id: str
    section: str
    clause: str
    exact_text: str
    locator: str
    style: str = ""

    @model_validator(mode="before")
    @classmethod
    def verify_derived_hashes(cls, value):
        if isinstance(value, dict):
            from .ingest import digest, normalized
            value = dict(value)
            text = value.get("exact_text", "")
            for field, expected in (("text_hash", digest(text.encode("utf-8"))),
                                    ("content_hash", digest(normalized(text).encode("utf-8")))):
                supplied = value.pop(field, expected)
                if supplied != expected:
                    raise ValueError("Source text hash mismatch")
        return value

    @computed_field
    @property
    def text_hash(self) -> str:
        from .ingest import digest
        return digest(self.exact_text.encode("utf-8"))

    @computed_field
    @property
    def content_hash(self) -> str:
        from .ingest import digest, normalized
        return digest(normalized(self.exact_text).encode("utf-8"))


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
    kind: Literal["department", "role", "collective", "unresolved"]
    source_span_ids: list[str]
    department_ids: list[str] = Field(default_factory=list)


class FunctionClaim(Model):
    id: str
    version: Version
    unit_id: str
    action: str
    object: str
    # Verbatim structural qualifiers, not the owner's name or an inferred scope.
    # Empty means that no separate qualifier was extracted.
    scope: str
    authority: Literal["duty", "right", "prohibition", "unknown"]
    text: str
    context_text: str
    source_span_ids: list[str]
    extraction: Literal["explicit", "unresolved"]


class MatchCandidate(Model):
    before_claim: str
    after_claim: str
    relation: Literal["EXACT", "LEXICAL", "LLM_CANDIDATE"]
    confidence: float
    evidence: list[str]


class SearchResult(Model):
    id: str
    before_claim: Optional[str] = None
    after_document_id: str
    searched_version: Version = "after"
    searched_document_ids: list[str] = Field(default_factory=list)
    matched_span_ids: list[str] = Field(default_factory=list)
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
    confidence: Literal["high", "medium", "low"]
    title: str
    explanation: str
    before_claim_id: Optional[str]
    after_claim_ids: list[str]
    evidence_for: list[Evidence]
    evidence_against: list[Evidence]
    review_status: Literal["PENDING"] = "PENDING"
    source_span_ids: list[str]
    search_result_ids: list[str]
    rule_id: str
    concern: str = ""


class OrganizationalIR(Model):
    documents: list[Document]
    units: list[Unit]
    claims: list[FunctionClaim]


class UnitChange(Model):
    id: str
    status: Literal["RETAINED", "NEW", "REORGANIZED", "REQUIRES_HUMAN_REVIEW"]
    title: str
    detail: str
    source_span_ids: list[str]


class InvestigationStep(Model):
    action: str
    detail: str
    source_span_ids: list[str] = Field(default_factory=list)
    search_result_ids: list[str] = Field(default_factory=list)


class Investigation(Model):
    finding_id: str
    steps: list[InvestigationStep]


class MatrixRow(Model):
    id: str
    before_claim_id: Optional[str] = None
    after_claim_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    status: str
    source_span_ids: list[str]
    search_result_ids: list[str] = Field(default_factory=list)


class Recommendation(Model):
    priority: Literal["high", "medium", "low"]
    action: str
    finding_ids: list[str]
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
    matrix: list[MatrixRow] = Field(default_factory=list)
    investigations: list[Investigation] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    responsibilities: list[Responsibility] = Field(default_factory=list)
    organizational_tests: list[OrganizationalTest] = Field(default_factory=list)
    test_summary: dict[str, int] = Field(default_factory=dict)
