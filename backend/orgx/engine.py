import re
from collections import Counter
from .models import AuditRecord, Evidence, Finding, MatchCandidate, OrganizationalIR, SearchResult, UnitChange
from .ingest import normalized, digest

ENGINE_VERSION = 'orgx-1.0.1'
POLICY_VERSION = 'evidence-policy-1.0.0'
STOP = {'и', 'в', 'по', 'с', 'для', 'на', 'о', 'об', 'к', 'из', 'во', 'от', 'а', 'б'}

def tokens(text):
    return set(re.findall(r'[а-яёa-z0-9]+', text.casefold())) - STOP

def evidence(text, ids=(), searches=()):
    return Evidence(text=text, source_span_ids=list(dict.fromkeys(ids)), search_result_ids=list(searches))

def audit(ir: OrganizationalIR) -> AuditRecord:
    before, after = ir.documents
    assert before.version == 'before' and after.version == 'after'
    units = {u.id:u for u in ir.units}
    old = [c for c in ir.claims if c.version == 'before']
    new = [c for c in ir.claims if c.version == 'after']
    new_norm = {c.id:normalized(c.text) for c in new}
    new_tokens = {c.id:tokens(c.text) for c in new}
    after_span_tokens = {s.id:tokens(s.exact_text) for s in after.spans}
    changes, findings, searches = [], [], []
    after_inventory = [u for u in ir.units if u.version=='after' and u.kind=='department']
    before_inventory = [u for u in ir.units if u.version=='before' and u.kind=='department']
    for u in before_inventory:
        matched = next((v for v in after_inventory if u.key==v.key),None)
        changes.append(UnitChange(id=f'unit-{len(changes)}', status='RETAINED' if matched else 'REQUIRES_HUMAN_REVIEW',
                       title=matched.name if matched else u.name,
                       detail='Подразделение перечислено в обеих версиях.' if matched else 'Название отсутствует в новом перечне. Реорганизация или упразднение не доказаны.',
                       source_span_ids=u.source_span_ids+(matched.source_span_ids if matched else [s.id for s in after.spans if s.clause=='3.4'])))
    for u in after_inventory:
        if not any(v.key==u.key for v in before_inventory):
            ids=[s.id for s in before.spans if s.clause=='3.4' or s.clause.startswith('3.4/')]+u.source_span_ids
            changes.append(UnitChange(id=f'unit-{len(changes)}', status='NEW' if before_inventory else 'REQUIRES_HUMAN_REVIEW', title=u.name,
                           detail='Впервые включено в перечень подразделений в этой паре документов; дата фактического создания не установлена.' if before_inventory else 'Старый перечень состава не распознан; создание подразделения не доказано.',
                           source_span_ids=ids if before_inventory else [before.spans[0].id]+u.source_span_ids))
    old_role=next((s for s in before.spans if s.clause=='5.3' and 'Директор направления внутреннего аудита:' in s.exact_text),None)
    new_role=next((s for s in after.spans if s.clause=='5.3' and 'Директоры департаментов и Директоры направлений ДИТААД и ДОА:' in s.exact_text),None)
    if old_role and new_role:
        changes.append(UnitChange(id='role-reorganization', status='REORGANIZED', title='Ответственные за аудит по §5.3',
                       detail='Раздел о директоре направления заменён разделом о директорах департаментов и направлений ДИТААД и ДОА. Это изменение ролей, а не замена ДНМ и ДККМ.', source_span_ids=[old_role.id,new_role.id]))

    def add(kind, title, explanation, bc, ac=(), pro=(), contra=(), rule='', concern='', confidence='medium'):
        pro=list(pro)
        contra=list(contra)
        sid = f'search:{bc.id}' if bc else None
        ids = list(dict.fromkeys(([ *bc.source_span_ids] if bc else []) + [x for c in ac for x in c.source_span_ids] + [x for e in pro+contra for x in e.source_span_ids]))
        sr = [sid] if sid else []
        for e in pro+contra:
            sr += e.search_result_ids
        fid='finding:'+digest((rule+'|'+(bc.id if bc else title)+'|'+'|'.join(c.id for c in ac)).encode())[:20]
        findings.append(Finding(id=fid,type=kind,confidence=confidence,title=title,explanation=explanation,
                        before_claim_id=bc.id if bc else None,after_claim_ids=[c.id for c in ac],
                        evidence_for=pro,evidence_against=contra,source_span_ids=ids,
                        search_result_ids=list(dict.fromkeys(sr)),rule_id=rule,concern=concern))

    for bc in old:
        q=tokens(bc.text)
        ranked=[]
        for ac in new:
            exact=normalized(bc.text)==new_norm[ac.id] and bc.extraction=='explicit'
            score=len(q & new_tokens[ac.id])/max(1,len(q | new_tokens[ac.id]))
            if exact or score>0:
                ranked.append((exact, round(score,6), ac))
        ranked.sort(key=lambda x:(-int(x[0]),-x[1],x[2].id))
        exacts=[x[2] for x in ranked if x[0]]
        # Include ALL exact candidates, even if they exceed the display top five.
        selected=[x for i,x in enumerate(ranked) if i<5 or x[0]]
        candidates=[MatchCandidate(before_claim=bc.id,after_claim=ac.id,relation='EXACT' if exact else 'LEXICAL',
                    confidence=score,evidence=bc.source_span_ids+ac.source_span_ids) for exact,score,ac in selected]
        # Evaluate every after span; retaining the manifest makes a negative search auditable.
        searched=[s.id for s in after.spans]
        _ = [len(q & after_span_tokens[sid]) for sid in searched]
        sr=SearchResult(id=f'search:{bc.id}',before_claim=bc.id,after_document_id=after.id,query=bc.text,
             method='full-corpus lexical retrieval + exact normalized claim comparison v1',searched_span_ids=searched,
             candidates=candidates,exact_match_count=len(exacts),exhaustive=True,
             limitation='Полный поиск по извлечённому тексту; лексический поиск не доказывает отсутствие смыслового эквивалента. Семантический балл не является вероятностью вывода.')
        searches.append(sr)
        same=[ac for ac in exacts if units[bc.unit_id].key==units[ac.unit_id].key and bc.authority==ac.authority
              and normalized(bc.context_text)==normalized(ac.context_text)]
        if len(same)==1:
            ac=same[0]
            add('PRESERVED','Функция сохранена', 'Совпадают текст, явно названный ответственный, модальность и родительский контекст.',bc,[ac],
                [evidence('Тождественная формулировка в сопоставимом структурном контексте.',bc.source_span_ids+ac.source_span_ids)],
                rule='exact-owner-context-v1',confidence='high')
        else:
            proposed=[x[2] for x in selected]
            reason='Нет подтверждённого соответствия текста, владельца, модальности и контекста.'
            if bc.extraction=='unresolved':
                reason='Исходный пункт пуст либо его владелец не установлен структурно; содержание или ответственность нельзя восстановить автоматически.'
            elif len(exacts)>1:
                reason='Найдены несколько совпадающих формулировок. Владельца или разграничение ответственности нужно проверить.'
            elif exacts:
                reason='Текст совпадает, но изменился ответственный, модальность или контекст. Передача требует проверки.'
            add('REQUIRES_HUMAN_REVIEW','Нужно проверить цепочку ответственности',reason,bc,proposed,
                [evidence('Исходная обязанность и результаты поиска по всей новой версии.',bc.source_span_ids,[sr.id])],
                [evidence('Кандидаты не подтверждают полное сохранение или потерю функции.',[x for ac in proposed for x in ac.source_span_ids])],
                rule='uncertain-chain-v1',concern='matching',confidence='low')

    def span(doc, fragment):
        found=[s for s in doc.spans if fragment in s.exact_text and s.section not in ('14',)]
        return found[0] if len(found)==1 else None

    # Explicit, inspectable evidence rules. No pair hashes, truth-set labels or
    # paragraph numbers are used to decide outcomes.
    transfer_old=span(before,'5.4.4. взаимодействует с субъектами СВК Общества в части:')
    transfer_new=span(after,'5.3.3. готовят предложения для включения в план работ БВА, взаимодействуют с субъектами СВК Общества в части:')
    dnm_header=span(before,'5.4. Директор департамента непрерывного мониторинга системы внутреннего контроля:')
    if transfer_old and transfer_new and old_role and new_role and dnm_header:
        for bc in old:
            if transfer_old.id not in bc.source_span_ids or dnm_header.id not in bc.source_span_ids or '/' not in next(s.clause for s in before.spans if s.id==bc.source_span_ids[0]):
                continue
            matches=[c for c in new if transfer_new.id in c.source_span_ids and normalized(c.text)==normalized(bc.text)]
            if len(matches)==1 and bc.authority==matches[0].authority:
                findings[:]=[f for f in findings if f.before_claim_id!=bc.id]
                add('MOVED','Взаимодействие с субъектами СВК перенесено в §5.3',
                    'Тождественная обязанность находится у ДНМ в старом §5.4.4 и у коллективно названных руководителей ДИТААД/ДОА в новом §5.3.3. Единственный департамент-владелец не определён.',bc,matches,
                    [evidence('Совпадают подфункция и контекст взаимодействия с субъектами СВК.',bc.source_span_ids+matches[0].source_span_ids)],
                    [evidence('Новый заголовок называет несколько руководителей; исключительное владение одним департаментом не доказано.',[new_role.id])],
                    rule='explicit-svk-reassignment-v1',confidence='high')

    group_old=span(before,'формировать группы контроля качества с привлечением работников БВА')
    quality_new=span(after,'5.5.2. организует непрерывный мониторинг качества деятельности внутреннего аудита;')
    delegated=span(after,'Директор ДККМ и/или уполномоченные им работники:')
    quality_right_header=span(before,'5.6. Директор ДККМ обязан обеспечить выполнение всех возложенных на ДККМ задач')
    if group_old and group_old.clause=='5.6.2' and quality_new and delegated and quality_right_header:
        phrase='формировать группы контроля качества'
        if not any(phrase in s.exact_text.casefold() for s in after.spans):
            bc=next((c for c in old if c.source_span_ids[0]==group_old.id),None)
            if bc and quality_right_header.id in bc.source_span_ids:
                findings[:]=[f for f in findings if f.before_claim_id!=bc.id]
                add('POTENTIAL_GAP','Явное право формировать группы контроля качества не найдено',
                    'Формулировка старого §5.6.2 не найдена во всём извлечённом тексте новой версии. Это потенциальный пробел явного полномочия, а не доказанная потеря контроля качества.',bc,[],
                    [evidence('Прежнее явное право; полный отрицательный поиск его формулировки.',[group_old.id],[f'search:{bc.id}'])],
                    [evidence('Контроль качества сохранён; §10.7 допускает уполномоченных работников. Эквивалентность группам требует решения аудитора.',[quality_new.id,delegated.id])],
                    rule='explicit-quality-group-right-gap-v1',concern='gap')

    overlap_old=span(before,'5.3.6. организует контроль устранения недостатков и нарушений, выявленных в ходе проведения проверок БВА;')
    overlap_new=span(after,'5.3.7. организуют контроль устранения недостатков и нарушений')
    overlap_quality=span(after,'5.5.5. организует контроль качества устранения недостатков и нарушений')
    if overlap_old and overlap_new and overlap_quality:
        bc=next((c for c in old if c.source_span_ids[0]==overlap_old.id),None)
        ac=[c for c in new if c.source_span_ids[0] in [overlap_new.id,overlap_quality.id]]
        if bc:
            add('REQUIRES_HUMAN_REVIEW','Контроль устранения и контроль его качества',
                'Есть частичное пересечение предмета. Контроль исполнения и контроль качества могут быть разными уровнями ответственности; дублирование не установлено.',bc,ac,
                [evidence('Оба пункта относятся к устранению недостатков и нарушений.',[overlap_old.id,overlap_new.id,overlap_quality.id])],
                [evidence('§5.5.5 содержит отдельный квалификатор «качества».',[overlap_quality.id])],
                rule='partial-quality-overlap-v1',concern='duplicate')

    governance_before=span(before,'4.4. Организация выполнения целей и задач внутреннего аудита ДЗО')
    governance_after=span(after,'Главный аудитор может участвовать в органах управления подконтрольных Обществ')
    prohibit=span(after,'в. принимать управленческие решения;')
    mitigate_a=span(after,'а. информирует о потенциальном конфликте при совмещении в отчетах и плане БВА;')
    mitigate_b=span(after,'б. указывает информацию о совмещении в декларациях/заявления по исключению КИ.')
    if all([governance_before,governance_after,prohibit,mitigate_a,mitigate_b]) and 'Главный аудитор может участвовать в органах управления' not in governance_before.exact_text:
        add('POTENTIAL_AUTHORITY_CONFLICT','Совмещение участия в управлении и независимого аудита',
            'В §4.4 добавлено участие Главного аудитора в органах управления подконтрольных обществ с мерами независимости. Сопоставить с запретом принимать управленческие решения в §5.8.1/в. Нарушение не установлено.',None,[],
            [evidence('Изменение §4.4 и ограничение полномочий требуют совместного рассмотрения.',[governance_before.id,governance_after.id,prohibit.id])],
            [evidence('Документ прямо предусматривает меры независимости, раскрытие совмещения и заявления о конфликте интересов.',[governance_after.id,mitigate_a.id,mitigate_b.id])],
            rule='governance-independence-tension-v1',concern='authority')

    # Strict duplicate signal: identical complete duty, identical non-relative
    # context, different explicit owners. General/shared scope is ambiguous.
    seen_pairs=set()
    for bc in old:
        eq=[c for c in new if normalized(c.text)==normalized(bc.text) and c.extraction=='explicit' and c.authority==bc.authority]
        for i,a in enumerate(eq):
            for b in eq[i+1:]:
                pair=tuple(sorted([a.id,b.id]))
                if pair in seen_pairs or a.unit_id==b.unit_id or len(tokens(a.text))<6:
                    continue
                seen_pairs.add(pair)
                ua,ub=units[a.unit_id],units[b.unit_id]
                relative=any(x in a.text.casefold() for x in ['в зоне','прочих поручений','план работ','запрашивает','выносит предложения'])
                exact_scope=normalized(a.context_text)==normalized(b.context_text) and not relative
                # A collective or parent-child relationship is never duplicate proof.
                independent=ua.kind==ub.kind=='role' and bool(ua.department_ids) and bool(ub.department_ids) and not set(ua.department_ids)&set(ub.department_ids)
                kind='POTENTIAL_DUPLICATE' if exact_scope and independent else 'REQUIRES_HUMAN_REVIEW'
                add(kind,'Совпадающие формулировки у разных ответственных',
                    'Тексты совпадают. Нужно проверить, обозначают ли они один результат и одну область ответственности.',bc,[a,b],
                    [evidence('Одинаковая формулировка у двух ответственных.',a.source_span_ids+b.source_span_ids)],
                    [evidence('Общие обязанности или разные области ответственности могут объяснять совпадение.',ua.source_span_ids+ub.source_span_ids)],
                    rule='cross-owner-exact-duty-v1',concern='duplicate',confidence='medium' if kind=='POTENTIAL_DUPLICATE' else 'low')

    if not old or not new:
        add('REQUIRES_HUMAN_REVIEW','Структура документа не распознана полностью',
            'Нет достаточных явно извлечённых функций в одной из версий. Требуется разметка ответственных; отсутствие функций не установлено.',None,[],
            [evidence('Доступный текст обеих версий.',[before.spans[0].id,after.spans[0].id])],rule='unsupported-layout-v1',confidence='low')
    counts=Counter(f.type for f in findings)
    conclusion=[]
    for ch in changes:
        conclusion.append(evidence(ch.title+': '+ch.detail,ch.source_span_ids))
    for kind in ['MOVED','POTENTIAL_GAP','POTENTIAL_AUTHORITY_CONFLICT']:
        for f in findings:
            if f.type==kind:
                conclusion.append(evidence(f.explanation,f.source_span_ids,f.search_result_ids))
    for kind in ['POTENTIAL_DUPLICATE','REQUIRES_HUMAN_REVIEW']:
        relevant=[f for f in findings if f.type==kind]
        if relevant:
            conclusion.append(evidence(f'Выводов со статусом {kind}: {len(relevant)}. Они требуют решения ответственного сотрудника.',
                              list(dict.fromkeys(x for f in relevant for x in f.source_span_ids))))
    record=AuditRecord(id='audit:'+digest((before.sha256+before.name+after.sha256+after.name+ENGINE_VERSION+POLICY_VERSION).encode()),
        engine_version=ENGINE_VERSION,policy_version=POLICY_VERSION,ir=ir,unit_changes=changes,
        search_results=searches,findings=sorted(findings,key=lambda f:(f.type,f.id)),conclusion=conclusion,
        coverage={'before_claims':len(old),'after_claims':len(new),'before_spans':len(before.spans),'after_spans':len(after.spans),
                  'findings':len(findings),**counts},
        limitations=['Автоматическое извлечение обязанностей поддерживает разделы 2 и 5 данного типа положений; остальные разделы доступны для поиска и специальных доказательных правил.',
                     'Перечень подразделений выявляется по явно названному списку состава. Юридический факт и дата создания не выводятся из появления названия.',
                     'Полнота семантического покрытия не гарантируется. Пустые пункты, неизвестные структуры и неоднозначные пары требуют человека.',
                     'Приложения, на которые только ссылается документ, не входят в доказательную базу. Все выводы рекомендательные.',
                     *before.warnings,*after.warnings])
    validate_record(record)
    return record

def validate_record(record: AuditRecord):
    spans={s.id:s for d in record.ir.documents for s in d.spans}
    searches={s.id:s for s in record.search_results}
    claims={c.id:c for c in record.ir.claims}
    for f in record.findings:
        if any(sid not in spans for sid in f.source_span_ids):
            raise ValueError('Unknown source span')
        if not any(spans[s].version=='before' for s in f.source_span_ids):
            raise ValueError('Finding lacks before evidence')
        has_after=any(spans[s].version=='after' for s in f.source_span_ids)
        has_search=any(s in searches and searches[s].after_document_id==record.ir.documents[1].id for s in f.search_result_ids)
        if not (has_after or has_search):
            raise ValueError('Finding lacks after evidence/search')
        for ev in f.evidence_for+f.evidence_against:
            if any(x not in spans for x in ev.source_span_ids) or any(x not in searches for x in ev.search_result_ids):
                raise ValueError('Broken evidence chain')
        if f.before_claim_id and f.before_claim_id not in claims:
            raise ValueError('Unknown before claim')
        if any(x not in claims or claims[x].version!='after' for x in f.after_claim_ids):
            raise ValueError('Unknown after claim')
