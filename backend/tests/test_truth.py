import json
from pathlib import Path
from orgx.engine import audit, validate_record
from orgx.extract import extract
from orgx.store import canonical

TRUTH = json.loads(
    (Path(__file__).resolve().parents[2] / "truth/source_truth.json").read_text()
)


def test_every_truth_quote_is_exact_and_source_hash_matches(real_documents):
    docs = {d.version: d for d in real_documents}
    for version, source in TRUTH["sources"].items():
        assert docs[version].sha256 == source["sha256"]
    for case in TRUTH["cases"]:
        assert {e["version"] for e in case["evidence"]} == {"before", "after"}
        for ev in case["evidence"]:
            span = next(
                s
                for s in docs[ev["version"]].spans
                if s.paragraph_id == ev["paragraph_id"]
            )
            assert span.exact_text == ev["exact_text"], case["id"]


def test_hand_reviewed_expectations(real_audit):
    for case in TRUTH["cases"]:
        e = case["expected"]
        if "unit_status" in e:
            assert any(
                c.status == e["unit_status"] and e["unit_contains"] in c.title
                for c in real_audit.unit_changes
            ), case["id"]
        if "finding_type" in e:
            matching = [f for f in real_audit.findings if f.type == e["finding_type"]]
            if "before_paragraph" in e:
                matching = [
                    f
                    for f in matching
                    if f.before_claim_id
                    and f.before_claim_id.endswith(e["before_paragraph"] + ":claim")
                ]
            if "rule_id" in e:
                matching = [f for f in matching if f.rule_id == e["rule_id"]]
            assert matching, case["id"]


def test_unsupported_cases_are_actually_blocked(real_audit):
    codes = {
        c["expected"]["forbidden_code"]
        for c in TRUTH["cases"]
        if c["category"] == "unsupported"
    }
    assert len(codes) == 7
    departments = [c for c in real_audit.unit_changes if c.id != "role-reorganization"]
    assert [c.status for c in departments].count("RETAINED") == 2
    assert [c.status for c in departments].count("NEW") == 2
    assert not any(c.status == "REORGANIZED" for c in departments)
    assert any("(ДНМ)" in c.title and c.status == "RETAINED" for c in departments)
    assert any(
        f.type == "PRESERVED" and f.before_claim_id.endswith("p0186:claim")
        for f in real_audit.findings
        if f.before_claim_id
    )
    moved = [f for f in real_audit.findings if f.type == "MOVED"]
    units = {u.id: u for u in real_audit.ir.units}
    claims = {c.id: c for c in real_audit.ir.claims}
    assert all(
        units[claims[c].unit_id].kind == "collective"
        for f in moved
        for c in f.after_claim_ids
    )
    conflict = next(
        f
        for f in real_audit.findings
        if f.rule_id == "governance-independence-tension-v1"
    )
    assert conflict.type == "POTENTIAL_AUTHORITY_CONFLICT"
    assert conflict.evidence_against and conflict.review_status == "PENDING"
    empty = [
        f
        for f in real_audit.findings
        if f.before_claim_id and f.before_claim_id.endswith("p0187:claim")
    ]
    assert all(f.type == "REQUIRES_HUMAN_REVIEW" for f in empty)
    assert any("Приложения" in l for l in real_audit.limitations)


def test_same_sources_same_canonical_record(real_documents, real_audit):
    assert canonical(audit(extract(real_documents))) == canonical(real_audit)
    validate_record(real_audit)
    for f in real_audit.findings:
        assert f.evidence_for
        assert f.review_status == "PENDING"


def test_matching_batches_search_whole_after_version(real_audit):
    for search in real_audit.search_results:
        ids = {s.id for d in real_audit.ir.documents if d.version == search.searched_version for s in d.spans}
        assert search.exhaustive
        assert set(search.searched_span_ids) == ids


def test_truth_is_never_loaded_by_runtime():
    runtime = Path(__file__).resolve().parents[1] / "orgx"
    assert all("source_truth.json" not in p.read_text() for p in runtime.glob("*.py"))


def test_company_resource_duties_are_not_attributed_to_auditors(real_audit):
    units = {u.id: u for u in real_audit.ir.units}
    c = next(
        c
        for c in real_audit.ir.claims
        if c.version == "after" and c.source_span_ids[0].endswith(":p0250")
    )
    assert units[c.unit_id].name == "Общество"
