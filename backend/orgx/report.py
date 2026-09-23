"""Evidence-linked matrix, reproducible check log and actionable review agenda."""

import csv
import io
from collections import Counter
from .models import (
    MatrixRow,
    Investigation,
    InvestigationStep,
    Recommendation,
    Evidence,
)
from .retrieval import corpus_search

LABELS = {
    "PRESERVED": "Сохранена",
    "MOVED": "Перенесена",
    "POTENTIAL_GAP": "Возможный пробел",
    "POTENTIAL_DUPLICATE": "Возможное дублирование",
    "POTENTIAL_AUTHORITY_CONFLICT": "Риск конфликта полномочий",
    "REQUIRES_HUMAN_REVIEW": "Нужна проверка",
    "AFTER_ONLY": "Соответствие до не установлено",
}
ORDER = {
    k: i
    for i, k in enumerate(
        [
            "POTENTIAL_AUTHORITY_CONFLICT",
            "POTENTIAL_GAP",
            "POTENTIAL_DUPLICATE",
            "REQUIRES_HUMAN_REVIEW",
            "MOVED",
            "PRESERVED",
        ]
    )
}


def enrich_record(record):
    claims = {c.id: c for c in record.ir.claims}
    units = {u.id: u for u in record.ir.units}
    spans = {s.id: s for d in record.ir.documents for s in d.spans}
    searches = list(record.search_results)
    matrix, trace, recommendations = [], [], []
    included = set()
    for bc in (c for c in record.ir.claims if c.version == "before"):
        findings = sorted(
            (f for f in record.findings if f.before_claim_id == bc.id),
            key=lambda f: ORDER[f.type],
        )
        ids = list(dict.fromkeys(c for f in findings for c in f.after_claim_ids))
        included.update(ids)
        matrix.append(
            MatrixRow(
                id="matrix:" + bc.id,
                before_claim_id=bc.id,
                after_claim_ids=ids,
                finding_ids=[f.id for f in findings],
                status=findings[0].type if findings else "REQUIRES_HUMAN_REVIEW",
                source_span_ids=list(
                    dict.fromkeys(
                        bc.source_span_ids
                        + [s for f in findings for s in f.source_span_ids]
                    )
                ),
                search_result_ids=list(
                    dict.fromkeys(s for f in findings for s in f.search_result_ids)
                ),
            )
        )
    for ac in (
        c for c in record.ir.claims if c.version == "after" and c.id not in included
    ):
        search = corpus_search(record.ir.documents, ac.text, "before", ac.id)
        searches.append(search)
        findings = [f for f in record.findings if ac.id in f.after_claim_ids]
        old_ids = search.matched_span_ids[:3] or [
            d.spans[0].id for d in record.ir.documents if d.version == "before"
        ]
        matrix.append(
            MatrixRow(
                id="matrix:" + ac.id,
                after_claim_ids=[ac.id],
                finding_ids=[f.id for f in findings],
                status=(
                    min(findings, key=lambda f: ORDER[f.type]).type
                    if findings
                    else "AFTER_ONLY"
                ),
                source_span_ids=list(dict.fromkeys(old_ids + ac.source_span_ids)),
                search_result_ids=[search.id],
            )
        )
    search_map = {s.id: s for s in searches}
    for finding in record.findings:
        bc = claims.get(finding.before_claim_id)
        ss = [search_map[s] for s in finding.search_result_ids]
        inspected = [claims[c] for c in finding.after_claim_ids]
        steps = [
            InvestigationStep(
                action="Проверка исходного основания",
                detail=(
                    f"Владелец: {units[bc.unit_id].name}. Полномочие: {bc.authority}."
                    if bc
                    else "Сопоставлены прямые фрагменты двух версий."
                ),
                source_span_ids=[
                    s for s in finding.source_span_ids if spans[s].version == "before"
                ],
            )
        ]
        for search in ss:
            steps.append(
                InvestigationStep(
                    action="Поиск по комплекту",
                    detail=f"Запрос: {search.query}\nВерсия: {search.searched_version}; файлов: {len(search.searched_document_ids) or 1}; просмотрено фрагментов: {len(search.searched_span_ids)}; точных совпадений: {search.exact_match_count}.",
                    source_span_ids=search.matched_span_ids,
                    search_result_ids=[search.id],
                )
            )
        steps.append(
            InvestigationStep(
                action="Проверка владельцев и контекста",
                detail=(
                    "\n".join(
                        f"{units[c.unit_id].name} · {c.authority} · контекст: {c.context_text or 'не указан отдельно'}"
                        for c in inspected
                    )
                    or "Явный соответствующий владелец среди извлечённых функций не подтверждён."
                ),
                source_span_ids=list(
                    dict.fromkeys(s for c in inspected for s in c.source_span_ids)
                ),
            )
        )
        steps.append(
            InvestigationStep(
                action="Проверка контрдоказательств",
                detail="\n".join(e.text for e in finding.evidence_against)
                or "Отдельных контрдоказательств правило не выделило; это не гарантия их отсутствия.",
                source_span_ids=list(
                    dict.fromkeys(
                        s for e in finding.evidence_against for s in e.source_span_ids
                    )
                ),
            )
        )
        steps.append(
            InvestigationStep(
                action="Применение доказательного правила",
                detail=f"{finding.rule_id}: {LABELS[finding.type]}. {finding.explanation} Решение аудитора ожидается.",
                source_span_ids=finding.source_span_ids,
                search_result_ids=finding.search_result_ids,
            )
        )
        trace.append(Investigation(finding_id=finding.id, steps=steps))
    actions = {
        "POTENTIAL_GAP": (
            "high",
            "Запросить действующий пункт, назначающий владельца и объём полномочия; проверить весь комплект приложений перед подтверждением пробела.",
        ),
        "POTENTIAL_DUPLICATE": (
            "high",
            "Уточнить границы ответственности, общий результат и порядок взаимодействия указанных владельцев; зафиксировать, является ли совпадение намеренным.",
        ),
        "POTENTIAL_AUTHORITY_CONFLICT": (
            "high",
            "Совместно проверить разрешение, запрет и меры независимости; запросить применимое разграничение полномочий.",
        ),
        "REQUIRES_HUMAN_REVIEW": (
            "medium",
            "Сверить кандидатов и контекст; запросить подтверждающие документы для неустановленных владельцев и смысловых соответствий.",
        ),
        "MOVED": (
            "medium",
            "Подтвердить текстовое перераспределение; при коллективной ответственности уточнить ответственного исполнителя.",
        ),
    }
    for kind, (priority, action) in actions.items():
        fs = [f for f in record.findings if f.type == kind]
        if fs:
            recommendations.append(
                Recommendation(
                    priority=priority,
                    action=action,
                    finding_ids=[f.id for f in fs],
                    source_span_ids=list(
                        dict.fromkeys(s for f in fs for s in f.source_span_ids)
                    ),
                )
            )
    # Count functions once, separately from risks (a function can have several findings).
    counts = Counter(r.status for r in matrix if r.before_claim_id)
    summary = Evidence(
        text=f"Сопоставлено исходных функций: {sum(counts.values())}. Текстовое сохранение: {counts['PRESERVED']}; перенос: {counts['MOVED']}; остальные требуют проверки: {sum(v for k,v in counts.items() if k not in ('PRESERVED','MOVED'))}. Матрица также включает {sum(r.before_claim_id is None for r in matrix)} строк новой версии без установленного соответствия. Это покрытие извлечённых функций, а не оценка полноты документов.",
        source_span_ids=[d.spans[0].id for d in record.ir.documents],
    )
    limitations = list(record.limitations)
    for doc in record.ir.documents:
        if not any(
            spans[c.source_span_ids[0]].document_id == doc.id for c in record.ir.claims
        ):
            limitations.append(
                f"{doc.name}: функции структурно не извлечены; текст включён в поиск, состав документа требует проверки."
            )
    return record.model_copy(
        update={
            "matrix": matrix,
            "search_results": searches,
            "investigations": trace,
            "recommendations": recommendations,
            "conclusion": [summary] + record.conclusion,
            "limitations": limitations,
        }
    )


def matrix_csv(record):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "До: функция",
            "До: владелец",
            "После: функции / кандидаты",
            "После: владельцы",
            "Статус",
            "Источники",
            "Выводы",
        ]
    )
    claims = {c.id: c for c in record.ir.claims}
    units = {u.id: u.name for u in record.ir.units}
    spans = {s.id: s for d in record.ir.documents for s in d.spans}
    docs = {d.id: d for d in record.ir.documents}

    def safe(value):
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value

    for row in record.matrix:
        before = claims.get(row.before_claim_id)
        after = [claims[c] for c in row.after_claim_ids]
        writer.writerow(
            [
                safe(value)
                for value in [
                    before.text if before else "",
                    units[before.unit_id] if before else "",
                    "\n".join(c.text for c in after),
                    "\n".join(dict.fromkeys(units[c.unit_id] for c in after)),
                    LABELS[row.status],
                    "\n".join(
                        f"{docs[spans[s].document_id].name} ({spans[s].version}), §{spans[s].clause}, {spans[s].locator}"
                        for s in row.source_span_ids
                    ),
                    ", ".join(row.finding_ids),
                ]
            ]
        )
    return "\ufeff" + out.getvalue()


def report_markdown(record, reviews):
    def clean(text):
        return text.replace("<", "&lt;").replace(">", "&gt;")

    result = [
        "# ORG-X · Заключение аудитора",
        "",
        f"Аудит: {record.id}",
        "",
        "Системные выводы рекомендательные. Решения человека приведены отдельно.",
        "",
        "## Переданные документы",
    ]
    for d in record.ir.documents:
        result.append(f"- {d.version}: {clean(d.name)} · SHA-256 `{d.sha256}`")
    result += ["", "## Результат", ""] + [
        clean(e.text) + "\n" for e in record.conclusion
    ]
    result += ["## Следующие действия", ""] + [
        f"- {r.priority}: {r.action} ({len(r.finding_ids)} выводов)"
        for r in record.recommendations
    ]
    latest = {r["finding_id"]: r for r in reviews}
    docs = {d.id: d for d in record.ir.documents}
    spans = {s.id: s for d in record.ir.documents for s in d.spans}
    result += ["", "## Доказательства и решения", ""]
    for f in record.findings:
        result += [
            f"### {clean(f.title)} · {LABELS[f.type]}",
            f"`{f.id}` · `{f.rule_id}`",
            "",
            clean(f.explanation),
        ]
        result += ["Контраргумент: " + clean(e.text) for e in f.evidence_against]
        for sid in f.source_span_ids:
            s = spans[sid]
            result += [
                f"\n**{s.version} · {clean(docs[s.document_id].name)} · §{s.clause} · {s.locator}**",
                "",
                "> " + clean(s.exact_text).replace("\n", "\n> "),
            ]
        if f.id in latest:
            r = latest[f.id]
            result += [
                f"\nРешение человека: {r['status']} · {clean(r['actor'])} · {r['created_at']}",
                clean(r["note"]),
            ]
        else:
            result.append("\nРешение человека: PENDING.")
    result += ["", "## Границы заключения", ""] + ["- " + l for l in record.limitations]
    return "\n".join(result) + "\n"
