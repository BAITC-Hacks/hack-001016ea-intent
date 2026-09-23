import json
from types import SimpleNamespace
import pytest
from orgx.investigator import investigate, InvestigationTools, MAX_ROUNDS, TOOLS
from orgx.store import Store, canonical
from test_corpora import control_documents, control_record


class FakeAgent:
    def __init__(self, calls):
        self.responses = self
        self.planned = list(calls)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs)))
        planned = self.planned.pop(0) if self.planned else None
        output = (
            []
            if planned is None
            else [
                {
                    "type": "function_call",
                    "call_id": f"call-{len(self.requests)}",
                    "name": planned[0],
                    "arguments": json.dumps(planned[1]),
                }
            ]
        )
        return SimpleNamespace(
            id=f"response-{len(self.requests)}", status="completed", output=output
        )


def focus(record):
    return next(f for f in record.findings if f.type == "MOVED")


def plan(record):
    f = focus(record)
    claims = {c.id: c for c in record.ir.claims}
    bc, ac = claims[f.before_claim_id], claims[f.after_claim_ids[0]]
    return [
        (
            "search_evidence",
            {"query": bc.text, "version": "before", "purpose": "candidate"},
        ),
        (
            "search_evidence",
            {"query": ac.text, "version": "after", "purpose": "candidate"},
        ),
        (
            "search_evidence",
            {
                "query": "исключить передать функцию реестр договоров",
                "version": "after",
                "purpose": "counter_evidence",
            },
        ),
        ("inspect_claim", {"claim_id": bc.id}),
        ("inspect_claim", {"claim_id": ac.id}),
        (
            "propose_pair",
            {
                "before_claim": bc.id,
                "after_claim": ac.id,
                "evidence_span_ids": [bc.source_span_ids[0], ac.source_span_ids[0]],
            },
        ),
    ]


def test_actual_tool_loop_replay_and_record_immutability(tmp_path, control_record):
    r = control_record
    original = canonical(r)
    client = FakeAgent(plan(r))
    store = Store(tmp_path / "agent.sqlite")
    args = dict(enabled=True, model="configured-model", client=client)
    one = investigate(r, focus(r).id, store, **args)
    assert one["status"] == "COMPLETED" and len(one["steps"]) == 6
    assert len(one["candidates"]) == 1
    assert one["candidates"][0]["status"] == "REQUIRES_HUMAN_REVIEW"
    assert one["candidates"][0]["checks"]["same_owner"] is False
    assert canonical(r) == original
    assert all(
        x["model"] == "configured-model"
        and x["store"] is False
        and x["parallel_tool_calls"] is False
        for x in client.requests
    )
    assert any(
        x.get("type") == "function_call_output" for x in client.requests[-1]["input"]
    )
    assert all(
        tool["strict"] and not tool["parameters"]["additionalProperties"]
        for tool in TOOLS
    )
    calls = len(client.requests)
    again = investigate(r, focus(r).id, store, **args)
    assert again["cached"] and again["candidates"] == one["candidates"]
    assert len(client.requests) == calls
    assert "responses" not in again and "request" not in again
    stored = store.get(one["cache_key"])
    assert stored["responses"] and stored["request"]["instructions"]


def test_ai_cannot_propose_before_owner_and_counter_checks(control_record):
    state = InvestigationTools(control_record, focus(control_record))
    proposed = plan(control_record)[-1][1]
    with pytest.raises(ValueError, match="Search and inspect"):
        state.execute("propose_pair", proposed)
    for name, args in plan(control_record):
        if name == "search_evidence" and args["purpose"] == "counter_evidence":
            continue
        if name == "propose_pair":
            break
        state.execute(name, args)
    with pytest.raises(ValueError, match="Search and inspect"):
        state.execute("propose_pair", proposed)


@pytest.mark.parametrize(
    "call",
    [
        ("delete_record", {}),
        ("inspect_claim", {"claim_id": "invented"}),
        (
            "search_evidence",
            {
                "query": "ignore previous instructions",
                "version": "after",
                "purpose": "candidate",
                "command": "rm -rf /",
            },
        ),
    ],
)
def test_untrusted_tool_actions_are_rejected(tmp_path, control_record, call):
    result = investigate(
        control_record,
        focus(control_record).id,
        Store(tmp_path / "reject.sqlite"),
        enabled=True,
        model="test",
        client=FakeAgent([call]),
    )
    assert result["steps"][0]["status"] == "REJECTED"
    assert result["candidates"] == [] and result["canonical_record_changed"] is False


def test_limits_and_transport_failure_are_honest(tmp_path, control_record):
    client = FakeAgent(
        [
            (
                "search_evidence",
                {"query": "проверка", "version": "after", "purpose": "candidate"},
            )
        ]
        * 20
    )
    result = investigate(
        control_record,
        focus(control_record).id,
        Store(tmp_path / "limit.sqlite"),
        enabled=True,
        model="test",
        client=client,
    )
    assert len(client.requests) == MAX_ROUNDS and result["status"] == "STEP_LIMIT"

    def fail(**kw):
        raise RuntimeError("secret-must-not-leak")

    client.create = fail
    result = investigate(
        control_record,
        focus(control_record).id,
        Store(tmp_path / "error.sqlite"),
        enabled=True,
        model="test",
        client=client,
    )
    assert result["status"] == "FALLBACK" and "secret-must-not-leak" not in str(result)


def test_disabled_ai_makes_no_client_calls(tmp_path, control_record):
    client = FakeAgent([])
    result = investigate(
        control_record,
        focus(control_record).id,
        Store(tmp_path / "off.sqlite"),
        client=client,
    )
    assert result["mode"] == "local" and not client.requests
