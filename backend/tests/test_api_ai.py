from types import SimpleNamespace
import json
import pytest
from fastapi.testclient import TestClient
from orgx.main import create_app
from orgx.llm import proposals, validate_proposal
from orgx.store import Store, canonical


def test_upload_cache_export_review_immutability(tmp_path, real_documents):
    from conftest import ROOT

    client = TestClient(create_app(tmp_path / "test.sqlite"))

    def send():
        files = {
            d.version: (
                d.name,
                (ROOT / "work/hackalem/kazakhtelecom" / d.name).read_bytes(),
            )
            for d in real_documents
        }
        return client.post("/api/audits", files=files)

    response = send()
    assert response.status_code == 200
    result = response.json()
    aid = result["record"]["id"]
    fid = result["record"]["findings"][0]["id"]
    assert result["cached"] is False
    again = send().json()
    assert again["cached"] is True
    assert canonical(result["record"]) == canonical(again["record"])
    before = client.get(f"/api/audits/{aid}/export").content
    bad = client.post(
        f"/api/audits/{aid}/findings/{fid}/review",
        json={"status": "ACCEPTED", "actor": " ", "note": ""},
    )
    assert bad.status_code == 422
    review = client.post(
        f"/api/audits/{aid}/findings/{fid}/review",
        json={
            "status": "NEEDS_INFO",
            "actor": "Test auditor",
            "note": "Request owner clarification",
        },
    )
    assert review.status_code == 200 and len(review.json()) == 1
    assert client.get(f"/api/audits/{aid}/export").content == before
    reopened = TestClient(create_app(tmp_path / "test.sqlite"))
    assert (
        reopened.get(f"/api/audits/{aid}/reviews").json()[0]["note"]
        == "Request owner clarification"
    )
    assert reopened.get("/api/audits/missing").status_code == 404
    assert (
        reopened.post(
            f"/api/audits/{aid}/findings/unknown/review",
            json={"status": "ACCEPTED", "actor": "X", "note": "X"},
        ).status_code
        == 404
    )


def test_bad_upload_is_422(tmp_path):
    c = TestClient(create_app(tmp_path / "test.sqlite"))
    assert (
        c.post(
            "/api/audits",
            files={"before": ("x.docx", b"broken"), "after": ("y.docx", b"broken")},
        ).status_code
        == 422
    )


class FakeClient:
    def __init__(self, output):
        self.calls = []
        self.output = output
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_text=json.dumps(self.output), id="test-response", status="completed"
        )


def test_ai_feature_flag_no_calls(tmp_path, real_audit):
    client = FakeClient({"pairs": []})
    result = proposals(real_audit, Store(tmp_path / "cache.sqlite"), client=client)
    assert result["mode"] == "deterministic" and not client.calls


def test_ai_structured_cached_replay_does_not_change_audit(tmp_path, real_audit):
    unresolved = {
        f.before_claim_id
        for f in real_audit.findings
        if f.type == "REQUIRES_HUMAN_REVIEW"
    }
    candidate = next(
        s.candidates[0]
        for s in real_audit.search_results
        if s.candidates and s.before_claim in unresolved
    )
    response = {
        "pairs": [
            {
                "before_claim": candidate.before_claim,
                "after_claim": candidate.after_claim,
                "relation": "CANDIDATE",
            }
        ]
    }
    client = FakeClient(response)
    store = Store(tmp_path / "cache.sqlite")
    before = canonical(real_audit)
    one = proposals(
        real_audit, store, enabled=True, model="test-model-snapshot", client=client
    )
    two = proposals(
        real_audit, store, enabled=True, model="test-model-snapshot", client=client
    )
    assert one == two and len(client.calls) == 1
    assert client.calls[0]["text"]["format"]["strict"] is True
    assert (
        one["prompt_version"]
        and one["schema_version"]
        and one["request"]
        and one["raw_response"]
    )
    assert one["candidates"][0]["relation"] == "LLM_CANDIDATE"
    assert canonical(real_audit) == before


@pytest.mark.parametrize(
    "payload",
    [
        {
            "pairs": [
                {
                    "before_claim": "invented",
                    "after_claim": "invented",
                    "relation": "CANDIDATE",
                }
            ]
        },
        {"pairs": [], "finding": "PRESERVED"},
        {"pairs": [{"before_claim": "x", "after_claim": "y", "relation": "PRESERVED"}]},
    ],
)
def test_llm_cannot_invent_facts(payload, tmp_path, real_audit):
    with pytest.raises(ValueError):
        validate_proposal(payload, real_audit)
    client = FakeClient(payload)
    result = proposals(
        real_audit,
        Store(tmp_path / "cache.sqlite"),
        enabled=True,
        model="test",
        client=client,
    )
    assert result["mode"] == "deterministic"


def test_network_error_falls_back_without_secret_echo(tmp_path, real_audit):
    client = FakeClient({})

    def fail(**kwargs):
        raise RuntimeError("secret-should-not-leak")

    client.create = fail
    result = proposals(
        real_audit,
        Store(tmp_path / "cache.sqlite"),
        enabled=True,
        model="test",
        client=client,
    )
    assert result["mode"] == "deterministic" and "secret-should-not-leak" not in str(
        result
    )


def test_invalid_ai_attempt_is_cached_for_replay(tmp_path, real_audit):
    client = FakeClient({"pairs": [], "invented_fact": "ignore evidence"})
    store = Store(tmp_path / "cache.sqlite")
    args = dict(enabled=True, model="test", client=client)
    one = proposals(real_audit, store, **args)
    two = proposals(real_audit, store, **args)
    assert one == two and len(client.calls) == 1
    assert one["mode"] == "deterministic"
    assert one["raw_response_text"] and one["error_type"]


def test_disk_failure_has_actionable_response(tmp_path, real_documents, monkeypatch):
    import sqlite3
    from conftest import ROOT

    app = create_app(tmp_path / "test.sqlite")

    def fail(*args):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(app.state.store, "put", fail)
    client = TestClient(app)
    files = {
        d.version: (
            d.name,
            (ROOT / "work/hackalem/kazakhtelecom" / d.name).read_bytes(),
        )
        for d in real_documents
    }
    response = client.post("/api/audits", files=files)
    assert response.status_code == 507
    assert "свободное место" in response.json()["detail"]
