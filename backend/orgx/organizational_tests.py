"""Seven explicit invariants over extracted responsibility occurrences.

PASS means the stated documentary predicate passed, not legal/organizational
truth or complete semantic coverage. Unknowns remain REVIEW.
"""
from collections import Counter
from .debugger_models import OrganizationalTest
from .ingest import normalize_content
from .responsibility import build_responsibilities
from .source_integrity import validate_sources

TEST_LABELS = {
    "OWNER_CONTINUITY": "Непрерывность владельца",
    "RESPONSIBILITY_TRANSFER": "Основание передачи",
    "SCOPE_CONTINUITY": "Границы ответственности",
    "DUPLICATE_OWNERSHIP": "Конкурирующие владельцы",
    "AUTHORITY_CONFLICT": "Совместимость полномочий",
    "SPLIT_MERGE": "Разделение и объединение",
    "SOURCE_INTEGRITY": "Целостность источников",
}


def organizational_tests(record, responsibilities):
    validate_sources(record)
    claims = {c.id: c for c in record.ir.claims}
    units = {u.id: u for u in record.ir.units}
    findings = {f.id: f for f in record.findings}
    result = []
    for r in responsibilities:
        before = [claims[x] for x in r.before_claim_ids]
        after = [claims[x] for x in r.after_claim_ids]
        fs = [findings[x] for x in r.finding_ids]
        proven = r.basis == "DOCUMENTARY_RULE" and r.relation in ("PRESERVED", "MOVED")
        single = proven and len(before) == len(after) == 1
        explicit = bool(after) and all(c.extraction == "explicit" and units[c.unit_id].kind != "unresolved" for c in after)
        def add(test, status, detail):
            result.append(OrganizationalTest(id=r.lineage_id+":"+test, test=test,
                responsibility_id=r.id, lineage_id=r.lineage_id, status=status, detail=detail,
                source_span_ids=r.source_span_ids, finding_ids=r.finding_ids))
        add("OWNER_CONTINUITY", "PASS" if proven and explicit else "REVIEW",
            "Документарное соответствие и явно названный ответственный найдены." if proven and explicit
            else "Непрерывность ответственности не подтверждена; отсутствие доказательства не означает потерю функции.")
        moved = r.relation == "MOVED" and proven
        unchanged_owner = single and units[before[0].unit_id].key == units[after[0].unit_id].key
        add("RESPONSIBILITY_TRANSFER", "PASS" if moved else "NOT_APPLICABLE" if unchanged_owner else "REVIEW",
            "Передача обоснована каноническим доказательным правилом; ссылки доступны ниже." if moved
            else "Владелец сохранён, передача не требуется." if unchanged_owner
            else "Требуется проверить документ о передаче, правопреемство и границы полномочий.")
        same_scope = bool(before and after) and all(normalize_content(a.context_text) == normalize_content(b.context_text)
                                                     for a in before for b in after)
        add("SCOPE_CONTINUITY", "PASS" if single and same_scope else "REVIEW",
            "Извлечённый явный контекст совпадает; неявные границы не интерпретируются." if single and same_scope
            else "Границы изменены или их преемственность не доказана; сравните точный контекст.")
        duplicate = any(f.type == "POTENTIAL_DUPLICATE" or f.concern == "duplicate" for f in fs)
        add("DUPLICATE_OWNERSHIP", "REVIEW" if duplicate or not proven else "PASS",
            "Есть конкурирующие/пересекающиеся основания либо неустановленная преемственность." if duplicate or not proven
            else "В проверенных соответствиях конкурирующее точное назначение не найдено; семантическая полнота не гарантируется.")
        conflict = any(f.type == "POTENTIAL_AUTHORITY_CONFLICT" or f.concern == "authority" for f in fs)
        same_authority = bool(before and after) and all(a.authority == b.authority != "unknown" for a in before for b in after)
        add("AUTHORITY_CONFLICT", "PASS" if proven and same_authority and not conflict else "REVIEW",
            "Извлечённая модальность совпадает; сработавших правил конфликта для этой функции нет." if proven and same_authority and not conflict
            else "Полномочия изменены, потенциально пересекаются или недостаточно данных.")
        add("SPLIT_MERGE", "PASS" if single else "REVIEW",
            "Подтверждено документарное соответствие один к одному." if single
            else "Гипотеза разделения/объединения требует проверки покрытия и контрдоказательств." if r.relation in ("SPLIT", "MERGED")
            else "Однозначное соответствие один к одному не установлено.")
        add("SOURCE_INTEGRITY", "PASS", "ID, версии, точные исходные тексты и область выполненного поиска проверены кодом.")
    return result


def attach_debugger(record):
    responsibilities = build_responsibilities(record)
    tests = organizational_tests(record, responsibilities)
    summary = Counter(t.status for t in tests)
    per_lineage = {}
    for t in tests:
        per_lineage.setdefault(t.lineage_id, []).append(t.status)
    status = Counter("FAIL" if "FAIL" in values else "REVIEW" if "REVIEW" in values else "PASS"
                     for values in per_lineage.values())
    summary.update({"responsibilities": len(responsibilities), "checks": len(tests),
                    "responsibilities_pass": status["PASS"], "responsibilities_review": status["REVIEW"],
                    "responsibilities_fail": status["FAIL"],
                    "before_occurrences": sum(bool(r.before_claim_ids) for r in responsibilities),
                    "after_only_occurrences": sum(not r.before_claim_ids for r in responsibilities)})
    return record.model_copy(update={"responsibilities": responsibilities,
        "organizational_tests": tests, "test_summary": dict(summary)})
