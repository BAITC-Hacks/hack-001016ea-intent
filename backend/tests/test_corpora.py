from pathlib import Path
from io import BytesIO
from collections import Counter
from docx import Document as Word
from fastapi.testclient import TestClient
import pytest
from orgx.ingest import ingest
from orgx.extract import extract
from orgx.engine import audit, validate_record
from orgx.main import create_app
from orgx.store import canonical

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def control_documents():
    return [
        ingest(p.read_bytes(), p.name, version)
        for version in ("before", "after")
        for p in sorted((ROOT / "examples/control" / version).glob("*.docx"))
    ]


@pytest.fixture(scope="session")
def control_record(control_documents):
    return audit(extract(control_documents))


def test_control_meets_positive_and_uncertain_acceptance_cases(control_record):
    counts = Counter(f.type for f in control_record.findings)
    assert counts == {
        "PRESERVED": 1,
        "MOVED": 1,
        "POTENTIAL_GAP": 1,
        "POTENTIAL_DUPLICATE": 1,
        "POTENTIAL_AUTHORITY_CONFLICT": 1,
        "REQUIRES_HUMAN_REVIEW": 1,
    }
    assert Counter(c.status for c in control_record.unit_changes) == {
        "RETAINED": 1,
        "NEW": 1,
        "REORGANIZED": 1,
    }
    duplicate = next(
        f for f in control_record.findings if f.type == "POTENTIAL_DUPLICATE"
    )
    assert duplicate.before_claim_id is None  # no old predecessor is required
    assert len(duplicate.after_claim_ids) == 2
    assert all(f.review_status == "PENDING" for f in control_record.findings)
    validate_record(control_record)


def test_matrix_and_search_cover_every_document_and_function(control_record):
    r = control_record
    assert {row.before_claim_id for row in r.matrix if row.before_claim_id} == {
        c.id for c in r.ir.claims if c.version == "before"
    }
    assert {cid for row in r.matrix for cid in row.after_claim_ids} == {
        c.id for c in r.ir.claims if c.version == "after"
    }
    findings = {f.id: f for f in r.findings}
    for row in r.matrix:
        for fid in row.finding_ids:
            assert set(findings[fid].source_span_ids) <= set(row.source_span_ids)
    for s in r.search_results:
        docs = [d for d in r.ir.documents if d.version == s.searched_version]
        assert set(s.searched_document_ids) == {d.id for d in docs}
        assert set(s.searched_span_ids) == {p.id for d in docs for p in d.spans}
    assert {i.finding_id for i in r.investigations} == {f.id for f in r.findings}
    assert all(len(i.steps) >= 4 for i in r.investigations)


def test_input_order_does_not_change_canonical_audit(control_documents, control_record):
    assert canonical(audit(extract(list(reversed(control_documents))))) == canonical(
        control_record
    )


def test_explicit_instructions_are_needed_for_generic_certainty(control_documents):
    docs = [
        d
        for d in control_documents
        if not (d.version == "after" and d.name == "03-order.docx")
    ]
    result = audit(extract(docs))
    assert not any(f.type in ("MOVED", "POTENTIAL_GAP") for f in result.findings)
    assert not any(c.status == "REORGANIZED" for c in result.unit_changes)


def test_duplicate_input_ids_are_rejected(control_documents):
    with pytest.raises(ValueError, match="повторяется"):
        audit(extract(control_documents + [control_documents[0]]))


def multipart():
    return [
        (
            v,
            (
                p.name,
                p.read_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        )
        for v in ("before", "after")
        for p in sorted((ROOT / "examples/control" / v).glob("*.docx"))
    ]


def test_multi_file_api_cache_exports_and_decisions(tmp_path, monkeypatch):
    monkeypatch.setenv("ORGX_ENABLE_OPENAI", "0")
    client = TestClient(create_app(tmp_path / "multi.sqlite"))
    one = client.post("/api/audits", files=multipart())
    assert one.status_code == 200, one.text
    body = one.json()
    assert len(body["record"]["ir"]["documents"]) == 6 and not body["cached"]
    two = client.post("/api/audits", files=list(reversed(multipart()))).json()
    assert two["cached"] and two["record"] == body["record"]
    aid = body["record"]["id"]
    baseline = client.get(f"/api/audits/{aid}/export").content
    duplicate = next(
        f for f in body["record"]["findings"] if f["type"] == "POTENTIAL_DUPLICATE"
    )
    review = client.post(
        f"/api/audits/{aid}/findings/{duplicate['id']}/review",
        json={
            "actor": "Контрольный аудитор",
            "note": "Запрошено разграничение функций склада.",
            "status": "NEEDS_INFO",
        },
    )
    assert review.status_code == 200
    report = client.get(f"/api/audits/{aid}/report.md")
    assert (
        "Контрольный аудитор" in report.text
        and "Запрошено разграничение" in report.text
    )
    assert "01-structure.docx" in report.text and "03-order.docx" in report.text
    csv = client.get(f"/api/audits/{aid}/matrix.csv")
    assert csv.status_code == 200 and csv.text.startswith("\ufeff")
    assert "После: владельцы" in csv.text and "Сверяет остатки" in csv.text
    assert client.get(f"/api/audits/{aid}/export").content == baseline
    agent = client.post(
        f"/api/audits/{aid}/findings/{duplicate['id']}/investigate"
    ).json()
    assert agent["mode"] == "local" and agent["local_investigation"]["steps"]
    assert client.post("/api/demo/synthetic").status_code == 200


def test_file_count_and_duplicate_uploads_rejected(tmp_path):
    client = TestClient(create_app(tmp_path / "limits.sqlite"))
    files = multipart()
    assert client.post("/api/audits", files=files + [files[0]]).status_code == 422
    assert (
        client.post("/api/audits", files=[files[0]] * 9 + [files[-1]]).status_code
        == 422
    )


def test_explicit_headers_work_in_other_supported_section(control_documents):
    # The example uses sections 7/9, generic registers and actors absent from the real pair.
    r = audit(extract(control_documents))
    assert r.coverage["before_claims"] == 3 and r.coverage["after_claims"] == 8
    assert all("Главный аудитор" not in u.name for u in r.ir.units)


@pytest.mark.parametrize(
    "duty",
    [
        "Утверждать бюджет.",
        "Подписывать договоры поставки.",
        "Принимает решения по управлению активами компании.",
    ],
)
@pytest.mark.parametrize("same_scope", [True, False])
def test_exact_permission_and_prohibition_ignore_length_but_respect_scope(
    duty, same_scope
):
    from test_robustness import document, control

    after = control(
        owner="Директор ДА имеет право в отношении северного филиала:", duty=duty
    )
    scope = "северного" if same_scope else "южного"
    after += [
        f"5.9. Директор ДА не имеет права в отношении {scope} филиала:",
        "5.9.1. " + duty,
    ]
    result = audit(extract([document(control(), "before"), document(after, "after")]))
    conflicts = [f for f in result.findings if f.type == "POTENTIAL_AUTHORITY_CONFLICT"]
    assert bool(conflicts) == same_scope
    if conflicts:
        assert len(conflicts[0].after_claim_ids) == 2
        assert conflicts[0].before_claim_id is None
        assert conflicts[0].review_status == "PENDING"
