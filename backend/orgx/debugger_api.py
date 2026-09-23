"""Read-only debugger routes; no model call and no canonical mutation."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .debug_investigation import investigate_responsibility


class InvestigateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lineage_id: str = Field(min_length=1, max_length=300)


def debugger_router(get_record):
    router = APIRouter()

    def debugger_record(audit_id):
        record = get_record(audit_id)
        if not record.responsibilities:
            # Old cached audits remain immutable. Derive this view on demand
            # rather than showing a misleading zero-test screen after upgrade.
            from .organizational_tests import attach_debugger
            record = attach_debugger(record)
        return record

    @router.get("/api/audits/{audit_id}/organizational-tests")
    def tests(audit_id: str):
        record = debugger_record(audit_id)
        return {"summary": record.test_summary, "tests": record.organizational_tests,
                "responsibilities": record.responsibilities}

    @router.post("/api/audits/{audit_id}/responsibility-investigation")
    def investigate(audit_id: str, body: InvestigateRequest):
        record = debugger_record(audit_id)
        if not any(r.lineage_id == body.lineage_id for r in record.responsibilities):
            raise HTTPException(404, "Ответственность не найдена")
        return investigate_responsibility(record, body.lineage_id)

    return router
