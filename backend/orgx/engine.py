import re
from collections import Counter
from .models import (
    AuditRecord,
    Evidence,
    Finding,
    MatchCandidate,
    OrganizationalIR,
    SearchResult,
    UnitChange,
)
from .ingest import normalized, normalize_content, digest
from .extract import body_spans, inventory_spans
from .corpus import Corpus, ordered_documents

ENGINE_VERSION = "orgx-2.1.0"
POLICY_VERSION = "evidence-policy-2.1.0"
STOP = {"и", "в", "по", "с", "для", "на", "о", "об", "к", "из", "во", "от", "а", "б"}


def tokens(text):
    return set(re.findall(r"[а-яёa-z0-9]+", text.casefold())) - STOP


def evidence(text, ids=(), searches=()):
    return Evidence(
        text=text,
        source_span_ids=list(dict.fromkeys(ids)),
        search_result_ids=list(searches),
    )


def audit(ir: OrganizationalIR) -> AuditRecord:
    ir = ir.model_copy(update={"documents": ordered_documents(ir.documents)})
    before, after = (Corpus(ir.documents, v) for v in ("before", "after"))
    units = {u.id: u for u in ir.units}
    old = [c for c in ir.claims if c.version == "before"]
    new = [c for c in ir.claims if c.version == "after"]
    new_norm = {c.id: normalize_content(c.text) for c in new}
    new_tokens = {c.id: tokens(c.text) for c in new}
    after_span_tokens = {s.id: tokens(s.exact_text) for s in after.spans}
    changes, findings, searches = [], [], []
    after_inventory = [
        u for u in ir.units if u.version == "after" and u.kind == "department"
    ]
    before_inventory = [
        u for u in ir.units if u.version == "before" and u.kind == "department"
    ]

    def span(doc, fragment, *, prefix=False, owner_heading=False):
        # Numeric labels and typography are locators, not evidence predicates.
        # Anchoring prevents a quotation or a negated sentence matching a rule.
        text = normalized(fragment)
        found = [
            s
            for s in body_spans(doc)
            if (
                not owner_heading
                or any(
                    s.id in u.source_span_ids and u.kind != "department"
                    for u in ir.units
                )
            )
            if (
                normalized(s.exact_text).startswith(text)
                if prefix
                else normalized(s.exact_text) == text
            )
        ]
        return found[0] if len(found) == 1 else None

    def ref(s):
        return f"§{s.clause}" if s.clause else s.locator

    def claim_at(items, source):
        return next(
            (c for c in items if source and c.source_span_ids[0] == source.id), None
        )

    for u in before_inventory:
        matched = next((v for v in after_inventory if u.key == v.key), None)
        changes.append(
            UnitChange(
                id=f"unit-{len(changes)}",
                status="RETAINED" if matched else "REQUIRES_HUMAN_REVIEW",
                title=matched.name if matched else u.name,
                detail=(
                    "Подразделение перечислено в обеих версиях."
                    if matched
                    else "Название отсутствует в новом перечне. Реорганизация или упразднение не доказаны."
                ),
                source_span_ids=u.source_span_ids
                + (
                    matched.source_span_ids
                    if matched
                    else [s.id for s in inventory_spans(after)] or [after.spans[0].id]
                ),
            )
        )
    for u in after_inventory:
        if not any(v.key == u.key for v in before_inventory):
            ids = [s.id for s in inventory_spans(before)] + u.source_span_ids
            changes.append(
                UnitChange(
                    id=f"unit-{len(changes)}",
                    status="NEW" if before_inventory else "REQUIRES_HUMAN_REVIEW",
                    title=u.name,
                    detail=(
                        "Впервые включено в перечень подразделений в этой паре документов; дата фактического создания не установлена."
                        if before_inventory
                        else "Старый перечень состава не распознан; создание подразделения не доказано."
                    ),
                    source_span_ids=(
                        ids
                        if before_inventory
                        else [before.spans[0].id] + u.source_span_ids
                    ),
                )
            )
    old_role = span(
        before, "Директор направления внутреннего аудита:", owner_heading=True
    )
    new_role = span(
        after,
        "Директоры департаментов и Директоры направлений ДИТААД и ДОА:",
        owner_heading=True,
    )
    # The text must be an extracted owner heading, not a mention elsewhere.
    if (
        old_role
        and new_role
        and not any(
            u.version == "after" and u.key == normalized(old_role.exact_text)
            for u in ir.units
        )
        and not any(
            u.version == "before" and u.key == normalized(new_role.exact_text)
            for u in ir.units
        )
    ):
        changes.append(
            UnitChange(
                id="role-reorganization",
                status="REORGANIZED",
                title=f"Ответственные за аудит: {ref(old_role)} → {ref(new_role)}",
                detail="Раздел о директоре направления заменён разделом о директорах департаментов и направлений ДИТААД и ДОА. Это изменение ролей, а не замена ДНМ и ДККМ.",
                source_span_ids=[old_role.id, new_role.id],
            )
        )

    def add(
        kind,
        title,
        explanation,
        bc,
        ac=(),
        pro=(),
        contra=(),
        rule="",
        concern="",
        confidence="medium",
    ):
        pro = list(pro)
        contra = list(contra)
        sid = f"search:{bc.id}" if bc else None
        ids = list(
            dict.fromkeys(
                ([*bc.source_span_ids] if bc else [])
                + [x for c in ac for x in c.source_span_ids]
                + [x for e in pro + contra for x in e.source_span_ids]
            )
        )
        sr = [sid] if sid else []
        for e in pro + contra:
            sr += e.search_result_ids
        fid = (
            "finding:"
            + digest(
                (
                    rule
                    + "|"
                    + (bc.id if bc else title)
                    + "|"
                    + "|".join(c.id for c in ac)
                ).encode()
            )[:20]
        )
        findings.append(
            Finding(
                id=fid,
                type=kind,
                confidence=confidence,
                title=title,
                explanation=explanation,
                before_claim_id=bc.id if bc else None,
                after_claim_ids=[c.id for c in ac],
                evidence_for=pro,
                evidence_against=contra,
                source_span_ids=ids,
                search_result_ids=list(dict.fromkeys(sr)),
                rule_id=rule,
                concern=concern,
            )
        )

    for bc in old:
        q = tokens(bc.text)
        ranked = []
        for ac in new:
            exact = (
                normalize_content(bc.text) == new_norm[ac.id]
                and bc.extraction == "explicit"
            )
            score = len(q & new_tokens[ac.id]) / max(1, len(q | new_tokens[ac.id]))
            if exact or score > 0:
                ranked.append((exact, round(score, 6), ac))
        ranked.sort(key=lambda x: (-int(x[0]), -x[1], x[2].id))
        exacts = [x[2] for x in ranked if x[0]]
        # Include ALL exact candidates, even if they exceed the display top five.
        selected = [x for i, x in enumerate(ranked) if i < 5 or x[0]]
        candidates = [
            MatchCandidate(
                before_claim=bc.id,
                after_claim=ac.id,
                relation="EXACT" if exact else "LEXICAL",
                confidence=score,
                evidence=bc.source_span_ids + ac.source_span_ids,
            )
            for exact, score, ac in selected
        ]
        # Evaluate every after span; retaining the manifest makes a negative search auditable.
        searched = [s.id for s in after.spans]
        span_ranks = sorted(
            (
                (
                    len(q & after_span_tokens[sid])
                    / max(1, len(q | after_span_tokens[sid])),
                    sid,
                )
                for sid in searched
            ),
            key=lambda x: (-x[0], x[1]),
        )
        sr = SearchResult(
            id=f"search:{bc.id}",
            before_claim=bc.id,
            after_document_id=after.id,
            searched_document_ids=[d.id for d in after.documents],
            matched_span_ids=[sid for score, sid in span_ranks[:8] if score > 0],
            query=bc.text,
            method="full-corpus lexical retrieval + exact normalized claim comparison v1",
            searched_span_ids=searched,
            candidates=candidates,
            exact_match_count=len(exacts),
            exhaustive=True,
            limitation="Полный поиск по извлечённому тексту; лексический поиск не доказывает отсутствие смыслового эквивалента. Семантический балл не является вероятностью вывода.",
        )
        searches.append(sr)
        same = [
            ac
            for ac in exacts
            if units[bc.unit_id].key == units[ac.unit_id].key
            and ac.extraction == "explicit"
            and bc.authority != "unknown"
            and bc.authority == ac.authority
            and normalize_content(bc.context_text) == normalize_content(ac.context_text)
        ]
        if len(same) == 1:
            ac = same[0]
            add(
                "PRESERVED",
                "Функция сохранена",
                "Совпадают текст, явно названный ответственный, модальность и родительский контекст.",
                bc,
                [ac],
                [
                    evidence(
                        "Тождественная формулировка в сопоставимом структурном контексте.",
                        bc.source_span_ids + ac.source_span_ids,
                    )
                ],
                rule="exact-owner-context-v1",
                confidence="high",
            )
        else:
            proposed = [x[2] for x in selected]
            reason = "Нет подтверждённого соответствия текста, владельца, модальности и контекста."
            if bc.extraction == "unresolved":
                reason = "Исходный пункт пуст либо его владелец не установлен структурно; содержание или ответственность нельзя восстановить автоматически."
            elif len(exacts) > 1:
                reason = "Найдены несколько совпадающих формулировок. Владельца или разграничение ответственности нужно проверить."
            elif exacts:
                reason = "Текст совпадает, но изменился ответственный, модальность или контекст. Передача требует проверки."
            add(
                "REQUIRES_HUMAN_REVIEW",
                "Нужно проверить цепочку ответственности",
                reason,
                bc,
                proposed,
                [
                    evidence(
                        "Исходная обязанность и результаты поиска по всей новой версии.",
                        bc.source_span_ids,
                        [sr.id],
                    )
                ],
                [
                    evidence(
                        "Кандидаты не подтверждают полное сохранение или потерю функции.",
                        [x for ac in proposed for x in ac.source_span_ids],
                    )
                ],
                rule="uncertain-chain-v1",
                concern="matching",
                confidence="low",
            )

    # Explicit, inspectable evidence rules. No pair hashes, truth-set labels or
    # clause numbers are used to decide outcomes. Text and source hierarchy must
    # both match; lexical similarity alone cannot establish reassignment.
    transfer_old = span(before, "взаимодействует с субъектами СВК Общества в части:")
    transfer_new = span(
        after,
        "готовят предложения для включения в план работ БВА, взаимодействуют с субъектами СВК Общества в части:",
    )
    dnm_header = span(
        before,
        "Директор департамента непрерывного мониторинга системы внутреннего контроля:",
    )
    if transfer_old and transfer_new and old_role and new_role and dnm_header:
        for bc in old:
            if (
                transfer_old.id not in bc.source_span_ids
                or dnm_header.id not in bc.source_span_ids
                or "/"
                not in next(
                    s.clause for s in before.spans if s.id == bc.source_span_ids[0]
                )
            ):
                continue
            matches = [
                c
                for c in new
                if normalize_content(c.text) == normalize_content(bc.text)
            ]
            if (
                len(matches) == 1
                and transfer_new.id in matches[0].source_span_ids
                and new_role.id in matches[0].source_span_ids
                and bc.extraction == matches[0].extraction == "explicit"
                and bc.authority == matches[0].authority == "duty"
            ):
                findings[:] = [f for f in findings if f.before_claim_id != bc.id]
                add(
                    "MOVED",
                    f"Взаимодействие с субъектами СВК перенесено в {ref(new_role)}",
                    f"Тождественная обязанность находится у ДНМ в старом {ref(transfer_old)} и у коллективно названных руководителей ДИТААД/ДОА в новом {ref(transfer_new)}. Единственный департамент-владелец не определён.",
                    bc,
                    matches,
                    [
                        evidence(
                            "Совпадают подфункция и контекст взаимодействия с субъектами СВК.",
                            bc.source_span_ids + matches[0].source_span_ids,
                        )
                    ],
                    [
                        evidence(
                            "Новый заголовок называет несколько руководителей; исключительное владение одним департаментом не доказано.",
                            [new_role.id],
                        )
                    ],
                    rule="explicit-svk-reassignment-v1",
                    confidence="high",
                )

    group_old = span(
        before,
        "формировать группы контроля качества с привлечением работников БВА",
        prefix=True,
    )
    quality_new = span(
        after,
        "организует непрерывный мониторинг качества деятельности внутреннего аудита;",
        prefix=True,
    )
    delegated = span(
        after,
        "Непрерывный мониторинг качества включает текущий анализ и оценку качества деятельности внутреннего аудита. В рамках осуществления непрерывного мониторинга качества Директор ДККМ и/или уполномоченные им работники:",
    )
    quality_right_header = span(
        before,
        "Директор ДККМ обязан обеспечить выполнение всех возложенных на ДККМ задач",
        prefix=True,
    )
    if group_old and quality_new and delegated and quality_right_header:
        phrase = "формировать группы контроля качества"
        if not any(phrase in normalized(s.exact_text) for s in after.spans):
            bc = claim_at(old, group_old)
            quality_claim = claim_at(new, quality_new)
            if (
                bc
                and bc.authority == "right"
                and bc.extraction == "explicit"
                and quality_right_header.id in bc.source_span_ids
                and quality_claim
                and quality_claim.authority == "duty"
            ):
                findings[:] = [f for f in findings if f.before_claim_id != bc.id]
                add(
                    "POTENTIAL_GAP",
                    "Явное право формировать группы контроля качества не найдено",
                    f"Формулировка старого {ref(group_old)} не найдена во всём извлечённом тексте новой версии. Это потенциальный пробел явного полномочия, а не доказанная потеря контроля качества.",
                    bc,
                    [],
                    [
                        evidence(
                            "Прежнее явное право; полный отрицательный поиск его формулировки.",
                            [group_old.id],
                            [f"search:{bc.id}"],
                        )
                    ],
                    [
                        evidence(
                            f"В {ref(quality_new)} указан контроль качества; {ref(delegated)} допускает уполномоченных работников. Эквивалентность группам требует решения аудитора.",
                            [quality_new.id, delegated.id],
                        )
                    ],
                    rule="explicit-quality-group-right-gap-v1",
                    concern="gap",
                )

    overlap_old = span(
        before,
        "организует контроль устранения недостатков и нарушений, выявленных в ходе проведения проверок БВА;",
    )
    overlap_new = span(
        after, "организуют контроль устранения недостатков и нарушений", prefix=True
    )
    overlap_quality = span(
        after,
        "организует контроль качества устранения недостатков и нарушений",
        prefix=True,
    )
    if overlap_old and overlap_new and overlap_quality:
        bc = next((c for c in old if c.source_span_ids[0] == overlap_old.id), None)
        ac = [
            c
            for c in new
            if c.source_span_ids[0] in [overlap_new.id, overlap_quality.id]
        ]
        if bc:
            add(
                "REQUIRES_HUMAN_REVIEW",
                "Контроль устранения и контроль его качества",
                "Есть частичное пересечение предмета. Контроль исполнения и контроль качества могут быть разными уровнями ответственности; дублирование не установлено.",
                bc,
                ac,
                [
                    evidence(
                        "Оба пункта относятся к устранению недостатков и нарушений.",
                        [overlap_old.id, overlap_new.id, overlap_quality.id],
                    )
                ],
                [
                    evidence(
                        f"{ref(overlap_quality)} содержит отдельный квалификатор «качества».",
                        [overlap_quality.id],
                    )
                ],
                rule="partial-quality-overlap-v1",
                concern="duplicate",
            )

    governance_before = span(
        before,
        "Организация выполнения целей и задач внутреннего аудита ДЗО",
        prefix=True,
    )
    governance_after = span(
        after,
        "Организация выполнения целей и задач внутреннего аудита ДЗО",
        prefix=True,
    )
    prohibit = span(after, "в. принимать управленческие решения;")
    mitigate_a = span(
        after,
        "а. информирует о потенциальном конфликте при совмещении в отчетах и плане БВА;",
    )
    mitigate_b = span(
        after,
        "б. указывает информацию о совмещении в декларациях/заявления по исключению КИ.",
    )
    if (
        all([governance_before, governance_after, prohibit, mitigate_a, mitigate_b])
        and "главный аудитор может участвовать в органах управления"
        not in normalized(governance_before.exact_text)
        and "главный аудитор может участвовать в органах управления подконтрольных обществ"
        in normalized(governance_after.exact_text)
        and claim_at(new, prohibit)
        and claim_at(new, prohibit).authority == "prohibition"
    ):
        add(
            "POTENTIAL_AUTHORITY_CONFLICT",
            "Совмещение участия в управлении и независимого аудита",
            f"В {ref(governance_after)} добавлено участие Главного аудитора в органах управления подконтрольных обществ с мерами независимости. Сопоставить с запретом принимать управленческие решения в {ref(prohibit)}. Нарушение не установлено.",
            None,
            [],
            [
                evidence(
                    f"Изменение {ref(governance_before)} → {ref(governance_after)} и ограничение полномочий требуют совместного рассмотрения.",
                    [governance_before.id, governance_after.id, prohibit.id],
                )
            ],
            [
                evidence(
                    "Документ прямо предусматривает меры независимости, раскрытие совмещения и заявления о конфликте интересов.",
                    [governance_after.id, mitigate_a.id, mitigate_b.id],
                )
            ],
            rule="governance-independence-tension-v1",
            concern="authority",
        )

    from .rules import apply_general_rules

    apply_general_rules(ir, changes, findings, searches, add)

    if not old or not new:
        add(
            "REQUIRES_HUMAN_REVIEW",
            "Структура документа не распознана полностью",
            "Нет достаточных явно извлечённых функций в одной из версий. Требуется разметка ответственных; отсутствие функций не установлено.",
            None,
            [],
            [
                evidence(
                    "Доступный текст обеих версий.",
                    [before.spans[0].id, after.spans[0].id],
                )
            ],
            rule="unsupported-layout-v1",
            confidence="low",
        )
    counts = Counter(f.type for f in findings)
    conclusion = []
    for ch in changes:
        conclusion.append(evidence(ch.title + ": " + ch.detail, ch.source_span_ids))
    for kind in ["MOVED", "POTENTIAL_GAP", "POTENTIAL_AUTHORITY_CONFLICT"]:
        for f in findings:
            if f.type == kind:
                conclusion.append(
                    evidence(f.explanation, f.source_span_ids, f.search_result_ids)
                )
    for kind in ["POTENTIAL_DUPLICATE", "REQUIRES_HUMAN_REVIEW"]:
        relevant = [f for f in findings if f.type == kind]
        if relevant:
            conclusion.append(
                evidence(
                    f"Выводов со статусом {kind}: {len(relevant)}. Они требуют решения ответственного сотрудника.",
                    list(dict.fromkeys(x for f in relevant for x in f.source_span_ids)),
                )
            )
    record = AuditRecord(
        id="audit:"
        + digest(
            (
                before.sha256
                + before.name
                + after.sha256
                + after.name
                + ENGINE_VERSION
                + POLICY_VERSION
            ).encode()
        ),
        engine_version=ENGINE_VERSION,
        policy_version=POLICY_VERSION,
        ir=ir,
        unit_changes=changes,
        search_results=searches,
        findings=sorted(findings, key=lambda f: (f.type, f.id)),
        conclusion=conclusion,
        coverage={
            "before_claims": len(old),
            "after_claims": len(new),
            "before_spans": len(before.spans),
            "after_spans": len(after.spans),
            "before_documents": len(before.documents),
            "after_documents": len(after.documents),
            "findings": len(findings),
            **counts,
        },
        limitations=[
            "Автоматическое извлечение поддерживает явно названные разделы функций, прав и обязанностей с распознаваемыми заголовками владельцев; номера могут меняться. Произвольная структура, сканы и схемы не покрываются универсальным парсером. Остальной извлечённый текст доступен для поиска.",
            "Перечень подразделений выявляется по явно названному списку состава. Юридический факт и дата создания не выводятся из появления названия.",
            "Полнота семантического покрытия не гарантируется. Пустые пункты, неизвестные структуры и неоднозначные пары требуют человека.",
            "Приложения, на которые только ссылается документ, не входят в доказательную базу. Все выводы рекомендательные.",
            *before.warnings,
            *after.warnings,
        ],
    )
    from .report import enrich_record

    record = enrich_record(record)
    from .organizational_tests import attach_debugger
    record = attach_debugger(record)
    validate_record(record)
    return record


def validate_record(record: AuditRecord):
    from .source_integrity import validate_sources
    validate_sources(record)
    spans = {s.id: s for d in record.ir.documents for s in d.spans}
    searches = {s.id: s for s in record.search_results}
    claims = {c.id: c for c in record.ir.claims}
    document_ids = {d.id for d in record.ir.documents if d.version == "after"}
    if len(spans) != sum(len(d.spans) for d in record.ir.documents) or len(
        claims
    ) != len(record.ir.claims):
        raise ValueError("Duplicate source or claim IDs")
    for search in record.search_results:
        expected = {
            s.id
            for d in record.ir.documents
            if d.version == search.searched_version
            for s in d.spans
        }
        if not search.exhaustive or set(search.searched_span_ids) != expected:
            raise ValueError("Incomplete search manifest")
        if any(s not in expected for s in search.matched_span_ids):
            raise ValueError("Search hit outside corpus")
    for f in record.findings:
        if any(sid not in spans for sid in f.source_span_ids):
            raise ValueError("Unknown source span")
        if not any(spans[s].version == "before" for s in f.source_span_ids):
            raise ValueError("Finding lacks before evidence")
        has_after = any(spans[s].version == "after" for s in f.source_span_ids)
        has_search = any(
            s in searches
            and searches[s].searched_version == "after"
            and searches[s].after_document_id in document_ids
            for s in f.search_result_ids
        )
        if not (has_after or has_search):
            raise ValueError("Finding lacks after evidence/search")
        for ev in f.evidence_for + f.evidence_against:
            if any(x not in spans for x in ev.source_span_ids) or any(
                x not in searches for x in ev.search_result_ids
            ):
                raise ValueError("Broken evidence chain")
        if f.before_claim_id and (
            f.before_claim_id not in claims
            or claims[f.before_claim_id].version != "before"
        ):
            raise ValueError("Unknown before claim")
        if any(
            x not in claims or claims[x].version != "after" for x in f.after_claim_ids
        ):
            raise ValueError("Unknown after claim")
    findings = {f.id for f in record.findings}
    for row in record.matrix:
        if any(
            c not in claims or claims[c].version != "after" for c in row.after_claim_ids
        ) or (
            row.before_claim_id
            and (
                row.before_claim_id not in claims
                or claims[row.before_claim_id].version != "before"
            )
        ):
            raise ValueError("Broken matrix claim")
        if (
            any(s not in spans for s in row.source_span_ids)
            or any(f not in findings for f in row.finding_ids)
            or any(s not in searches for s in row.search_result_ids)
        ):
            raise ValueError("Broken matrix evidence")
    for investigation in record.investigations:
        if investigation.finding_id not in findings:
            raise ValueError("Unknown investigation finding")
        for step in investigation.steps:
            if any(s not in spans for s in step.source_span_ids) or any(
                s not in searches for s in step.search_result_ids
            ):
                raise ValueError("Broken investigation evidence")
