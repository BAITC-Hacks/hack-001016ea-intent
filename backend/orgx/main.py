import os
import sqlite3
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from dotenv import load_dotenv
from .ingest import ingest, digest, MAX_BYTES
from .extract import extract
from .engine import audit, ENGINE_VERSION, POLICY_VERSION
from .models import AuditRecord, Document
from .store import Store, canonical
from .llm import proposals
from .corpus import ordered_documents
from .report import matrix_csv, report_markdown
from .investigator import investigate

MAX_FILES_PER_VERSION = 8
MAX_TOTAL_BYTES = 40 * 1024 * 1024

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status: Literal["ACCEPTED", "REJECTED", "NEEDS_INFO"]
    actor: str = Field(min_length=1, max_length=120)
    note: str = Field(min_length=1, max_length=3000)


def create_app(db_path=None):
    app = FastAPI(title="ORG-X Evidence Audit", version=ENGINE_VERSION)
    store = Store(Path(db_path or os.getenv("ORGX_DB", str(ROOT / "work/orgx.sqlite"))))
    app.state.store = store

    @app.exception_handler(sqlite3.OperationalError)
    async def storage_error(request, exc):
        return JSONResponse(
            status_code=507,
            content={
                "detail": "Не удалось сохранить аудит. Проверьте свободное место на диске и доступ к локальной базе, затем повторите анализ."
            },
        )

    def cached_document(data, name, version):
        cache_key = "document:" + digest(
            (digest(data) + name + version + ENGINE_VERSION).encode()
        )
        existing = store.get(cache_key)
        if existing:
            return Document.model_validate(existing)
        doc = ingest(data, name, version)
        store.put(cache_key, doc)
        return doc

    def analyze(inputs):
        inputs = sorted(
            inputs, key=lambda item: (item[2] != "before", item[1], digest(item[0]))
        )
        if sum(len(data) for data, _, _ in inputs) > MAX_TOTAL_BYTES:
            raise ValueError("Комплект превышает суммарный лимит 40 МБ.")
        key = "request:" + digest(
            canonical(
                [
                    [(digest(data), name, version) for data, name, version in inputs],
                    ENGINE_VERSION,
                    POLICY_VERSION,
                ]
            ).encode()
        )
        cached = store.get(key)
        if cached:
            body = store.get(cached["audit_id"]) if "audit_id" in cached else cached
            if body:
                return {"record": body, "cached": True}
        docs = ordered_documents(
            [cached_document(data, name, version) for data, name, version in inputs]
        )
        if sum(len(d.spans) for d in docs) > 12000:
            raise ValueError("Комплект превышает 12 000 извлечённых фрагментов.")
        ir = extract(docs)
        if len(ir.claims) > 1500:
            raise ValueError(
                "Комплект превышает 1 500 извлечённых функций; разделите аудит на сопоставимые области."
            )
        record = audit(ir)
        store.put(record.id, record)
        store.put(key, {"audit_id": record.id})
        return {"record": record.model_dump(), "cached": False}

    def get_record(audit_id):
        raw = store.get(audit_id)
        if not raw or not audit_id.startswith("audit:"):
            raise HTTPException(404, "Аудит не найден")
        return AuditRecord.model_validate(raw)

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "engine_version": ENGINE_VERSION,
            "ai_enabled": os.getenv("ORGX_ENABLE_OPENAI", "0") == "1",
            "demo_available": all(
                (ROOT / "work/hackalem/kazakhtelecom" / name).is_file()
                for name in (
                    "Внутренний_аудит_редакция_8_до.docx",
                    "Внутренний_аудит_редакция_9_после.docx",
                )
            ),
        }

    @app.post("/api/audits")
    def upload(
        before: list[UploadFile] = File(...), after: list[UploadFile] = File(...)
    ):
        try:
            if not (
                1 <= len(before) <= MAX_FILES_PER_VERSION
                and 1 <= len(after) <= MAX_FILES_PER_VERSION
            ):
                raise ValueError("Выберите от 1 до 8 файлов для каждой версии.")
            inputs, total = [], 0
            for version, uploads in (("before", before), ("after", after)):
                for upload in uploads:
                    data = upload.file.read(MAX_BYTES + 1)
                    total += len(data)
                    if len(data) > MAX_BYTES or total > MAX_TOTAL_BYTES:
                        raise ValueError(
                            "Лимит — 20 МБ на файл и 40 МБ на весь комплект."
                        )
                    inputs.append((data, upload.filename or "", version))
            return analyze(inputs)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            for upload in before + after:
                upload.file.close()

    @app.post("/api/demo")
    def demo():
        source = ROOT / "work/hackalem/kazakhtelecom"
        paths = [
            source / "Внутренний_аудит_редакция_8_до.docx",
            source / "Внутренний_аудит_редакция_9_после.docx",
        ]
        if not all(p.is_file() for p in paths):
            raise HTTPException(
                404,
                "Поместите два исходных DOCX в work/hackalem/kazakhtelecom или загрузите их через интерфейс.",
            )
        return analyze(
            [(p.read_bytes(), p.name, v) for p, v in zip(paths, ("before", "after"))]
        )

    @app.post("/api/demo/synthetic")
    def synthetic_demo():
        base = ROOT / "examples/control"
        paths = [
            (p, v)
            for v in ("before", "after")
            for p in sorted((base / v).glob("*.docx"))
        ]
        if not paths:
            raise HTTPException(
                404, "Контрольный комплект не найден в examples/control."
            )
        return analyze([(p.read_bytes(), p.name, v) for p, v in paths])

    @app.get("/api/audits/{audit_id}")
    def retrieve(audit_id: str):
        return get_record(audit_id)

    @app.get("/api/audits/{audit_id}/export")
    def export(audit_id: str):
        return Response(
            canonical(get_record(audit_id)),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="orgx-audit.json"'},
        )

    @app.get("/api/audits/{audit_id}/reviews")
    def reviews(audit_id: str):
        get_record(audit_id)
        return store.reviews(audit_id)

    @app.get("/api/audits/{audit_id}/matrix.csv")
    def export_matrix(audit_id: str):
        return Response(
            matrix_csv(get_record(audit_id)),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="orgx-matrix.csv"'},
        )

    @app.get("/api/audits/{audit_id}/report.md")
    def export_report(audit_id: str):
        return Response(
            report_markdown(get_record(audit_id), store.reviews(audit_id)),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="orgx-report.md"'},
        )

    @app.post("/api/audits/{audit_id}/findings/{finding_id}/review")
    def review(audit_id: str, finding_id: str, body: ReviewRequest):
        record = get_record(audit_id)
        if not any(f.id == finding_id for f in record.findings):
            raise HTTPException(404, "Вывод не найден")
        return store.review(audit_id, finding_id, body.status, body.actor, body.note)

    @app.post("/api/audits/{audit_id}/suggestions")
    def suggest(audit_id: str):
        return proposals(
            get_record(audit_id),
            store,
            enabled=os.getenv("ORGX_ENABLE_OPENAI", "0") == "1",
            model=os.getenv("OPENAI_MODEL", ""),
            api_key=os.getenv("OPENAI_API_KEY", ""),
        )

    @app.post("/api/audits/{audit_id}/findings/{finding_id}/investigate")
    def investigation(audit_id: str, finding_id: str):
        record = get_record(audit_id)
        if not any(f.id == finding_id for f in record.findings):
            raise HTTPException(404, "Вывод не найден")
        return investigate(
            record,
            finding_id,
            store,
            enabled=os.getenv("ORGX_ENABLE_OPENAI", "0") == "1",
            model=os.getenv("OPENAI_MODEL", ""),
            api_key=os.getenv("OPENAI_API_KEY", ""),
        )

    from .debugger_api import debugger_router
    app.include_router(debugger_router(get_record))

    dist = ROOT / "frontend/dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
