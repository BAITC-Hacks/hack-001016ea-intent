"""Run the supplied pair cold/warm; fail if canonical outputs differ."""

import sys
import tempfile
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient
from orgx.main import create_app
from orgx.store import canonical

with tempfile.TemporaryDirectory() as directory:
    client = TestClient(create_app(Path(directory) / "benchmark.sqlite"))
    outputs = []
    for mode in ["cold", "warm"]:
        start = perf_counter()
        response = client.post("/api/demo")
        seconds = perf_counter() - start
        response.raise_for_status()
        payload = response.json()
        outputs.append(canonical(payload["record"]))
        print(f'{mode}: {seconds:.3f}s; cached={payload["cached"]}')
    assert outputs[0] == outputs[1]
    print("Identical canonical records:", payload["record"]["id"])
    print("Coverage:", payload["record"]["coverage"])
