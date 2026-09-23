import pytest
from orgx.models import Document,SourceSpan,Unit,FunctionClaim,OrganizationalIR
from orgx.engine import audit,validate_record
from orgx.ingest import digest

def scenario(before,after):
    docs,units,claims=[],[],[]
    for version,items in [('before',before),('after',after)]:
        spans=[]
        for i,item in enumerate(items):
            text,owner=item[:2]
            scope=item[2] if len(item)>2 else ''
            authority=item[3] if len(item)>3 else 'duty'
            sid=f'{version}:p{i}'
            spans.append(SourceSpan(id=sid,document_id=version,version=version,paragraph_id=f'p{i}',section='5',clause=f'5.3.{i+1}',exact_text=text,locator=f'Paragraph {i}'))
            units.append(Unit(id=f'{version}:{owner}',key=owner,name=owner,version=version,kind='role',source_span_ids=[sid],department_ids=[f'{version}:department:{owner}']))
            claims.append(FunctionClaim(id=sid+':claim',version=version,unit_id=f'{version}:{owner}',action=text.split()[0],object=text,scope=owner,authority=authority,text=text,context_text=scope,source_span_ids=[sid],extraction='explicit'))
        docs.append(Document(id=version,version=version,name=version+'.docx',sha256=digest(str(items).encode()),format='docx',spans=spans))
    return audit(OrganizationalIR(documents=docs,units=units,claims=claims))

@pytest.mark.parametrize('before,after',[
    ([('Проверяет сохранность активов компании','A')],[('Обеспечивает сохранность активов компании','A')]),
    ([('Контролирует устранение недостатков','A')],[('Организует мониторинг корректирующих мер','A')]),
    ([('Проверяет все риски компании','A')],[('Проверяет финансовые риски','B'),('Проверяет ИТ-риски','C')]),
    ([('Контролирует устранение нарушений','A')],[('Контролирует качество устранения нарушений','A')]),
    ([('Формирует группы контроля качества','A')],[('Ведёт переписку по кадровым вопросам','B')]),
    ([('Проверяет все риски компании','A')],[('Проверяет все риски компании','B'),('Проверяет все риски компании','C')]),
    ([('Утверждает план аудита','A','всех подразделений')],[('Утверждает план аудита','A','ИТ-департамента')]),
    ([('Принимает управленческие решения','A','','right')],[('Принимает управленческие решения','A','','prohibition')]),
    ([('Проверяет качество финансовой отчетности','A')],[('Не проверяет качество финансовой отчетности','A')]),
])
def test_unsupported_certainty_never_replaces_review(before,after):
    result=scenario(before,after)
    assert result.findings
    assert all(f.type not in ('PRESERVED','MOVED','POTENTIAL_GAP') for f in result.findings)
    assert any(f.type=='REQUIRES_HUMAN_REVIEW' for f in result.findings)
    validate_record(result)

def test_exact_context_preserved():
    r=scenario([('Проверяет качество отчетности','A')],[('Проверяет качество отчетности','A')])
    assert [f.type for f in r.findings]==['PRESERVED']

def test_duplicate_requires_two_independent_explicit_owners():
    text='Проверяет полноту данных реестра имущества за отчётный период'
    r=scenario([(text,'A')],[(text,'A'),(text,'B')])
    assert any(f.type=='POTENTIAL_DUPLICATE' for f in r.findings)

def test_shared_relative_scope_is_not_duplicate_proof():
    text='Проверяет полноту данных реестра имущества в зоне ответственности'
    r=scenario([(text,'A')],[(text,'A'),(text,'B')])
    assert not any(f.type=='POTENTIAL_DUPLICATE' for f in r.findings)

def test_all_competing_exact_candidates_retained():
    text='Проверяет данные реестра'
    r=scenario([(text,'old')],[(text,str(i)) for i in range(8)])
    assert r.search_results[0].exact_match_count==8
    assert len(r.search_results[0].candidates)==8
    assert not any(f.type=='MOVED' for f in r.findings)

def test_determinism():
    args=([('Проверяет качество отчетности','A')],[('Оценивает качество отчетности','A')])
    assert scenario(*args).model_dump_json()==scenario(*args).model_dump_json()
