from pathlib import Path
import pytest
from orgx.ingest import ingest
from orgx.extract import extract
from orgx.engine import audit

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def real_documents():
    paths = [
        ROOT / "work/hackalem/kazakhtelecom" / f
        for f in [
            "Внутренний_аудит_редакция_8_до.docx",
            "Внутренний_аудит_редакция_9_после.docx",
        ]
    ]
    if not all(p.exists() for p in paths):
        pytest.skip(
            "Supply original documents in work/hackalem/kazakhtelecom to run source truth tests"
        )
    return [
        ingest(p.read_bytes(), p.name, v) for p, v in zip(paths, ["before", "after"])
    ]


@pytest.fixture(scope="session")
def real_audit(real_documents):
    return audit(extract(real_documents))
