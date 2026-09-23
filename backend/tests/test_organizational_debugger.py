"""Behavioral controls through real DOCX ingestion; no fabricated IR outcomes."""
import json
from io import BytesIO
from collections import Counter
from docx import Document as WordDocument
import pytest
from fastapi.testclient import TestClient
from orgx.models import AuditRecord
from orgx.ingest import ingest
from orgx.extract import extract
from orgx.engine import audit, validate_record
from orgx.responsibility import fingerprint
from orgx.debug_investigation import investigate_responsibility
from orgx.source_integrity import validate_sources
from orgx.main import create_app
from orgx.store import canonical


def file_bytes(items):
    word = WordDocument()
    for line in items:
        word.add_paragraph(line)
    result = BytesIO()
    word.save(result)
    return result.getvalue()


def lines(entries, section=5):
    result = ["3. Структура", "3.4. Служба состоит из следующих структурных подразделений:",
              "а. Департамент А (ДА).", "б. Департамент Б (ДБ).", "в. Департамент В (ДВ).", "г. Департамент Г (ДГ).",
              f"{section}. Права и обязанности"]
    for owner_idx, (owner, responsibilities) in enumerate(entries, 1):
        result.append(f"{section}.{owner_idx}. {owner}:")
        for i, text in enumerate(responsibilities, 1):
            result.append(f"{section}.{owner_idx}.{i}. {text}")
    return result


def run(before, after):
    docs = [ingest(file_bytes(ls), v+".docx", v) for ls,v in ((before,"before"),(after,"after"))]
    return audit(extract(docs))


def old_lineages(record):
    return [r for r in record.responsibilities if r.before_claim_ids]


A = "Директор ДА"
B = "Директор ДБ"
C = "Директор ДВ"
FULL = "Контролирует полноту реестра оборудования и полноту журнала платежей."
LEFT = "Контролирует полноту реестра оборудования."
RIGHT = "Контролирует полноту журнала платежей."


def test_preserved_has_seven_checks_and_content_identity():
    record = run(lines([(A,[LEFT])]),lines([(A,[LEFT])]))
    r, = old_lineages(record)
    assert r.relation == "PRESERVED"
    assert Counter(t.test for t in record.organizational_tests) == {name:1 for name in
        ["OWNER_CONTINUITY","RESPONSIBILITY_TRANSFER","SCOPE_CONTINUITY","DUPLICATE_OWNERSHIP","AUTHORITY_CONFLICT","SPLIT_MERGE","SOURCE_INTEGRITY"]}
    assert record.test_summary['responsibilities_pass'] == 1
    assert record.test_summary['responsibilities_review'] == 0
    assert r.requires_human_review
    assert len(set(fingerprint(c) for c in record.ir.claims)) == 1


def test_id_stable_under_numbering_whitespace_and_version():
    before = lines([(A,[LEFT])],5)
    after = ["  "+x.upper().replace(" ","   ") for x in lines([(A,[LEFT])],17)]
    record = run(before,after)
    r, = old_lineages(record)
    assert r.relation == "PRESERVED"
    assert fingerprint(record.ir.claims[0]) == fingerprint(record.ir.claims[1])
    assert record.ir.claims[0].id != record.ir.claims[1].id
    assert all(s.clause.startswith("17") for s in record.ir.documents[1].spans if s.id in record.ir.claims[1].source_span_ids)


@pytest.mark.parametrize('after', ["Организует реестр оборудования.", "Не контролирует реестр оборудования.", "Контролирует реестр транспорта."])
def test_action_object_negation_change_identity_without_asserting_gap(after):
    record = run(lines([(A,[LEFT])]),lines([(A,[after])]))
    r, = old_lineages(record)
    assert r.relation == "UNKNOWN"
    assert fingerprint(record.ir.claims[0]) != fingerprint(record.ir.claims[1])
    assert record.test_summary['responsibilities_review'] >= 1


def test_same_fingerprint_new_owner_is_not_proven_transfer():
    record = run(lines([(A,[LEFT])]),lines([(B,[LEFT])]))
    assert fingerprint(record.ir.claims[0]) == fingerprint(record.ir.claims[1])
    r, = old_lineages(record)
    assert r.relation == "UNKNOWN" and not r.after_claim_ids
    assert next(t for t in record.organizational_tests if t.lineage_id==r.lineage_id and t.test=='RESPONSIBILITY_TRANSFER').status == 'REVIEW'


def test_split_is_explicit_hypothesis_and_investigation_revises_gap():
    record = run(lines([(A,[FULL])]),lines([(B,[LEFT]),(C,[RIGHT])]))
    r, = old_lineages(record)
    assert r.relation == "SPLIT"
    assert r.basis == "COMPOSITION_HYPOTHESIS" and len(r.after_claim_ids)==2
    before = canonical(record)
    trace = investigate_responsibility(record,r.lineage_id)
    assert trace.initial_hypothesis == 'POTENTIAL_GAP'
    assert trace.final_hypothesis == 'SPLIT' and trace.revised
    assert any(s.tool=='search_counter_evidence' and s.searched_span_ids for s in trace.steps)
    assert trace.steps[-1].tool=='request_human_review'
    assert canonical(record)==before
    assert record.test_summary['REVIEW'] > 0


def test_merge_tracks_all_predecessors_with_provenance():
    record = run(lines([(A,[LEFT]),(B,[RIGHT])]),lines([(C,[FULL])]))
    old = old_lineages(record)
    assert len(old)==2 and all(r.relation=='MERGED' for r in old)
    assert all(len(r.before_claim_ids)==2 and len(r.after_claim_ids)==1 for r in old)
    for r in old:
        assert r.lineage_id == 'lineage:'+r.before_claim_ids[0]
        trace = investigate_responsibility(record,r.lineage_id)
        assert trace.final_hypothesis=='MERGED' and trace.requires_human_review


@pytest.mark.parametrize('right', ['Контролирует другой журнал.', 'Организует журнал платежей.'])
def test_incomplete_or_wrong_action_does_not_fake_split(right):
    record=run(lines([(A,[FULL])]),lines([(B,[LEFT]),(C,[right])]))
    assert all(r.relation!='SPLIT' for r in record.responsibilities)


def test_competing_cover_blocks_split():
    record=run(lines([(A,[FULL])]),lines([(B,[LEFT]),(C,[RIGHT]),('Директор ДГ',[RIGHT])]))
    assert all(r.relation!='SPLIT' for r in old_lineages(record))


def test_changed_scope_blocks_split_and_has_rejected_candidate():
    record=run(lines([(A+' обязан в отношении всех филиалов',[FULL])]),
        lines([(B+' обязан в отношении северного филиала',[LEFT]),(C+' обязан в отношении северного филиала',[RIGHT])]))
    r,=old_lineages(record)
    assert r.relation!='SPLIT'
    trace=investigate_responsibility(record,r.lineage_id)
    assert any(c.verdict=='REJECTED' and not c.scope_matches for c in trace.candidates)


def test_duplicate_keeps_competing_owners_and_review():
    record=run(lines([(A,[LEFT])]),lines([(A,[LEFT]),(B,[LEFT])]))
    assert any(r.relation=='DUPLICATED' for r in record.responsibilities)
    assert any(t.test=='DUPLICATE_OWNERSHIP' and t.status=='REVIEW' for t in record.organizational_tests)


def test_authority_change_is_review_and_changes_identity():
    record=run(lines([(A+' имеет право',[LEFT])]),lines([(A+' не имеет права',[LEFT])]))
    assert fingerprint(record.ir.claims[0])!=fingerprint(record.ir.claims[1])
    assert any(t.test=='AUTHORITY_CONFLICT' and t.status=='REVIEW' for t in record.organizational_tests)


def test_exact_source_hashes_survive_json_roundtrip_and_reject_tampering():
    record=run(lines([(A,[LEFT])]),lines([(A,[LEFT])]))
    payload=record.model_dump(mode='json')
    assert all(len(s['text_hash'])==64 and len(s['content_hash'])==64 for d in payload['ir']['documents'] for s in d['spans'])
    assert canonical(AuditRecord.model_validate(payload))==canonical(record)
    payload['ir']['documents'][0]['spans'][0]['exact_text']='fabricated'
    with pytest.raises(ValueError,match='hash mismatch'):
        AuditRecord.model_validate(payload)


@pytest.mark.parametrize('mutation', ['claim_text','claim_version','span_version','missing_span','empty_evidence','incomplete_search'])
def test_source_integrity_rejects_corrupted_record(mutation):
    record=run(lines([(A,[LEFT])]),lines([(A,[LEFT])]))
    if mutation.startswith('claim_'):
        c=record.ir.claims[0].model_copy(update={'text':'invented'} if mutation=='claim_text' else {'version':'after'})
        record=record.model_copy(update={'ir':record.ir.model_copy(update={'claims':[c]+record.ir.claims[1:]})})
    elif mutation=='span_version':
        d=record.ir.documents[0]
        d=d.model_copy(update={'spans':[d.spans[0].model_copy(update={'version':'after'})]+d.spans[1:]})
        record=record.model_copy(update={'ir':record.ir.model_copy(update={'documents':[d]+record.ir.documents[1:]})})
    elif mutation in ('missing_span','empty_evidence'):
        f=record.findings[0].model_copy(update={'source_span_ids':['missing']} if mutation=='missing_span' else {'evidence_for':[]})
        record=record.model_copy(update={'findings':[f]+record.findings[1:]})
    else:
        search=record.search_results[0].model_copy(update={'searched_span_ids':[]})
        record=record.model_copy(update={'search_results':[search]+record.search_results[1:]})
    with pytest.raises(ValueError): validate_record(record)


def test_api_investigate_is_read_only_and_rejects_unknown_ids(tmp_path):
    client=TestClient(create_app(tmp_path/'debugger.sqlite'))
    response=client.post('/api/audits',files={'before':('before.docx',file_bytes(lines([(A,[FULL])]))),
        'after':('after.docx',file_bytes(lines([(B,[LEFT]),(C,[RIGHT])])) )})
    assert response.status_code==200
    record=response.json()['record']
    aid=record['id']
    original=client.get(f'/api/audits/{aid}/export').content
    test_response=client.get(f'/api/audits/{aid}/organizational-tests')
    assert test_response.status_code==200 and test_response.json()['summary']['checks']>=7
    r=next(x for x in record['responsibilities'] if x['relation']=='SPLIT')
    trace=client.post(f'/api/audits/{aid}/responsibility-investigation',json={'lineage_id':r['lineage_id']})
    assert trace.status_code==200 and trace.json()['final_hypothesis']=='SPLIT'
    assert client.post(f'/api/audits/{aid}/responsibility-investigation',json={'lineage_id':'unknown'}).status_code==404
    assert client.get(f'/api/audits/{aid}/export').content==original
    assert client.get(f'/api/audits/{aid}/reviews').json()==[]


@pytest.mark.source_documents
def test_real_pair_truth_remains_source_linked_and_tests_replay(real_audit):
    validate_record(real_audit)
    assert len(real_audit.organizational_tests)==7*len(real_audit.responsibilities)
    assert any(r.relation=='MOVED' for r in real_audit.responsibilities)
    gap=next(r for r in real_audit.responsibilities if r.relation=='POTENTIAL_GAP')
    a=investigate_responsibility(real_audit,gap.lineage_id)
    b=investigate_responsibility(real_audit,gap.lineage_id)
    assert a.model_dump()==b.model_dump()
    assert a.source_span_ids and a.requires_human_review
    assert any(s.tool=='search_counter_evidence' for s in a.steps)


def test_explicit_transfer_keeps_identity_and_requires_human_review():
    after = lines([(B,[LEFT])]) + ['7. Распоряжения', f'7.1. Передать функцию «{LEFT}» от «{A}» к «{B}».']
    record = run(lines([(A,[LEFT])]), after)
    r, = old_lineages(record)
    assert r.relation == 'MOVED' and r.basis == 'DOCUMENTARY_RULE'
    assert fingerprint(record.ir.claims[0]) == fingerprint(record.ir.claims[1])
    assert r.requires_human_review
    assert any(t.test == 'RESPONSIBILITY_TRANSFER' and t.status == 'PASS' for t in record.organizational_tests)


def test_explicit_exclusion_is_potential_gap_not_certain_loss():
    after=lines([(B,['Ведёт переписку по кадровым вопросам.'])])+['7. Распоряжения',f'7.1. Исключить функцию «{LEFT}» из перечня обязанностей.']
    record=run(lines([(A,[LEFT])]), after)
    r,=old_lineages(record)
    assert r.relation=='POTENTIAL_GAP' and r.requires_human_review
    trace=investigate_responsibility(record,r.lineage_id)
    assert trace.final_hypothesis=='POTENTIAL_GAP'
    assert any(s.tool=='search_counter_evidence' for s in trace.steps)


def test_independent_authority_conflict_is_visible_in_test_suite():
    same='Принимает решения по управлению активами компании.'
    record=run(lines([(A,[LEFT])]), lines([(B+' имеет право',[same]),(B+' не имеет права',[same])]))
    assert any(r.relation=='POTENTIAL_AUTHORITY_CONFLICT' for r in record.responsibilities)
    assert any(t.test=='AUTHORITY_CONFLICT' and t.status=='REVIEW' for t in record.organizational_tests)


@pytest.mark.parametrize('mutation',['fingerprint','lineage_version','missing_test'])
def test_lineage_and_test_integrity_cannot_be_forged(mutation):
    record=run(lines([(A,[LEFT])]),lines([(A,[LEFT])]))
    if mutation=='missing_test':
        record=record.model_copy(update={'organizational_tests':record.organizational_tests[:-1]})
    else:
        r=record.responsibilities[0]
        updates={'id':'R-FORGED'} if mutation=='fingerprint' else {'after_claim_ids':r.before_claim_ids}
        record=record.model_copy(update={'responsibilities':[r.model_copy(update=updates)]})
    with pytest.raises(ValueError):
        validate_record(record)


def test_real_scope_difference_blocks_same_owner_authority_conflict():
    same='Принимает решения по управлению активами компании.'
    record=run(lines([(A,[LEFT])]),lines([(B+' имеет право в северном филиале',[same]),(B+' не имеет права в южном филиале',[same])]))
    assert not any(r.relation=='POTENTIAL_AUTHORITY_CONFLICT' for r in record.responsibilities)


def test_legacy_cached_audit_derives_debugger_without_mutating_export(tmp_path):
    record=run(lines([(A,[LEFT])]),lines([(A,[LEFT])]))
    legacy=record.model_copy(update={'responsibilities':[],'organizational_tests':[],'test_summary':{}})
    app=create_app(tmp_path/'legacy.sqlite')
    app.state.store.put(legacy.id,legacy)
    client=TestClient(app)
    original=client.get(f'/api/audits/{legacy.id}/export').content
    data=client.get(f'/api/audits/{legacy.id}/organizational-tests').json()
    assert data['summary']['checks']==7 and len(data['responsibilities'])==1
    result=client.post(f'/api/audits/{legacy.id}/responsibility-investigation',json={'lineage_id':data['responsibilities'][0]['lineage_id']})
    assert result.status_code==200
    assert client.get(f'/api/audits/{legacy.id}/export').content==original
