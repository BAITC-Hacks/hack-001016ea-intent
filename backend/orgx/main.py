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

ROOT=Path(__file__).resolve().parents[2]
load_dotenv(ROOT/'.env')

class ReviewRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    status: Literal['ACCEPTED','REJECTED','NEEDS_INFO']
    actor: str=Field(min_length=1,max_length=120)
    note: str=Field(min_length=1,max_length=3000)

def create_app(db_path=None):
    app=FastAPI(title='ORG-X Evidence Audit',version=ENGINE_VERSION)
    store=Store(Path(db_path or os.getenv('ORGX_DB',str(ROOT/'work/orgx.sqlite'))))
    app.state.store=store

    @app.exception_handler(sqlite3.OperationalError)
    async def storage_error(request,exc):
        return JSONResponse(status_code=507,content={'detail':'Не удалось сохранить аудит. Проверьте свободное место на диске и доступ к локальной базе, затем повторите анализ.'})

    def cached_document(data,name,version):
        cache_key='document:'+digest((digest(data)+name+version+ENGINE_VERSION).encode())
        existing=store.get(cache_key)
        if existing:
            return Document.model_validate(existing)
        doc=ingest(data,name,version)
        store.put(cache_key,doc)
        return doc

    def analyze(data_before,name_before,data_after,name_after):
        key='request:'+digest(canonical([digest(data_before),name_before,digest(data_after),name_after,ENGINE_VERSION,POLICY_VERSION]).encode())
        cached=store.get(key)
        if cached:
            body=store.get(cached['audit_id']) if 'audit_id' in cached else cached
            if body:
                return {'record':body,'cached':True}
        docs=[cached_document(data_before,name_before,'before'),cached_document(data_after,name_after,'after')]
        record=audit(extract(docs))
        store.put(record.id,record)
        store.put(key,{'audit_id':record.id})
        return {'record':record.model_dump(),'cached':False}

    def get_record(audit_id):
        raw=store.get(audit_id)
        if not raw or not audit_id.startswith('audit:'):
            raise HTTPException(404,'Аудит не найден')
        return AuditRecord.model_validate(raw)

    @app.get('/api/health')
    def health():
        return {'status':'ok','engine_version':ENGINE_VERSION,'ai_enabled':os.getenv('ORGX_ENABLE_OPENAI','0')=='1',
                'demo_available':len(list((ROOT/'work/hackalem/kazakhtelecom').glob('*.docx')))==2}

    @app.post('/api/audits')
    def upload(before: UploadFile=File(...),after: UploadFile=File(...)):
        try:
            before_data=before.file.read(MAX_BYTES+1)
            after_data=after.file.read(MAX_BYTES+1)
            return analyze(before_data,before.filename or '',after_data,after.filename or '')
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc
        finally:
            before.file.close()
            after.file.close()

    @app.post('/api/demo')
    def demo():
        source=ROOT/'work/hackalem/kazakhtelecom'
        paths=[source/'Внутренний_аудит_редакция_8_до.docx',source/'Внутренний_аудит_редакция_9_после.docx']
        if not all(p.is_file() for p in paths):
            raise HTTPException(404,'Поместите два исходных DOCX в work/hackalem/kazakhtelecom или загрузите их через интерфейс.')
        return analyze(paths[0].read_bytes(),paths[0].name,paths[1].read_bytes(),paths[1].name)

    @app.get('/api/audits/{audit_id}')
    def retrieve(audit_id: str):
        return get_record(audit_id)

    @app.get('/api/audits/{audit_id}/export')
    def export(audit_id: str):
        return Response(canonical(get_record(audit_id)),media_type='application/json',headers={'Content-Disposition':'attachment; filename="orgx-audit.json"'})

    @app.get('/api/audits/{audit_id}/reviews')
    def reviews(audit_id: str):
        get_record(audit_id)
        return store.reviews(audit_id)

    @app.post('/api/audits/{audit_id}/findings/{finding_id}/review')
    def review(audit_id: str,finding_id: str,body: ReviewRequest):
        record=get_record(audit_id)
        if not any(f.id==finding_id for f in record.findings):
            raise HTTPException(404,'Вывод не найден')
        return store.review(audit_id,finding_id,body.status,body.actor,body.note)

    @app.post('/api/audits/{audit_id}/suggestions')
    def suggest(audit_id: str):
        return proposals(get_record(audit_id),store,enabled=os.getenv('ORGX_ENABLE_OPENAI','0')=='1',
                         model=os.getenv('OPENAI_MODEL',''),api_key=os.getenv('OPENAI_API_KEY',''))

    dist=ROOT/'frontend/dist'
    if dist.is_dir():
        app.mount('/',StaticFiles(directory=dist,html=True),name='frontend')
    return app

app=create_app()
