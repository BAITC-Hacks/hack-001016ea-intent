"""Executed local investigation with revisable hypotheses and verifiable tools.

This is a deterministic investigative workflow. The optional model-driven tool
agent is separate and never modifies the canonical record or these checks.
"""
from .debugger_models import CandidateAssessment, DebugStep, DebugInvestigation
from .ingest import normalize_content
from .responsibility import atoms, compatible, composition
from .retrieval import search_spans, similarity
from .source_integrity import validate_sources


def investigate_responsibility(record, lineage_id):
    validate_sources(record)
    r = next((r for r in record.responsibilities if r.lineage_id == lineage_id), None)
    if r is None:
        raise ValueError("Unknown responsibility occurrence")
    claims = {c.id: c for c in record.ir.claims}
    units = {u.id: u for u in record.ir.units}
    source_ids = {s.id for d in record.ir.documents for s in d.spans}
    bc = claims[r.before_claim_ids[0]] if r.before_claim_ids else None
    fs = [f for f in record.findings if f.id in r.finding_ids]
    proven = r.basis == "DOCUMENTARY_RULE" and r.relation in ("PRESERVED", "MOVED")
    initial = r.relation if proven else "POTENTIAL_GAP" if bc and not r.after_claim_ids else "UNKNOWN"
    # Composite candidates are not established successors until investigation.
    if bc and r.basis == "COMPOSITION_HYPOTHESIS":
        initial = "POTENTIAL_GAP"
    current = initial
    steps = []
    def log(tool, detail, ids=(), claim_ids=(), searched=()):
        if any(x not in source_ids for x in ids) or any(x not in claims for x in claim_ids):
            raise ValueError("Investigation references invented evidence")
        steps.append(DebugStep(sequence=len(steps)+1, tool=tool, hypothesis=current,
            detail=detail, source_span_ids=list(dict.fromkeys(ids)), claim_ids=list(claim_ids), searched_span_ids=list(searched)))
    log("form_hypothesis", "Начальная рабочая гипотеза, а не установленный факт: "+initial,
        bc.source_span_ids if bc else r.source_span_ids, [bc.id] if bc else r.after_claim_ids)
    if bc:
        owner = units[bc.unit_id]
        log("get_responsibility", f"Владелец: {owner.name}; действие: {bc.action}; полномочие: {bc.authority}; контекст: {bc.context_text or 'не указан отдельно'}.", bc.source_span_ids, [bc.id])
    query = bc.text if bc else claims[r.after_claim_ids[0]].text if r.after_claim_ids else fs[0].title
    searched_version = "after" if bc else "before"
    hits = search_spans(record.ir.documents, query, searched_version, limit=12)
    searched = [s.id for d in record.ir.documents if d.version == searched_version for s in d.spans]
    log("search_responsibility", f"Полный лексический поиск по версии {searched_version}: {len(searched)} фрагментов; показаны лучшие {len(hits)}. Балл — порядок поиска, не уверенность в истинности.",
        [s.id for _, s in hits], searched=searched)
    after = [c for c in record.ir.claims if c.version == "after"]
    candidates = []
    if bc:
        ranked = sorted(after, key=lambda c: (-similarity(query, c.text), c.id))
        selected = {c.id for c in ranked[:8] if similarity(query, c.text) >= .12}
        selected.update(r.candidate_claim_ids)
        selected.update(r.after_claim_ids)
        for ac in (c for c in after if c.id in selected):
            action = normalize_content(bc.action) == normalize_content(ac.action)
            scope = normalize_content(bc.context_text) == normalize_content(ac.context_text)
            authority = bc.authority == ac.authority != "unknown"
            reasons = []
            if not action: reasons.append("Действие отличается; тематическая близость не означает одинаковую функцию.")
            if not scope: reasons.append("Scope/родительский контекст отличается.")
            if not authority: reasons.append("Полномочие отличается либо неизвестно.")
            if units[ac.unit_id].kind == "unresolved": reasons.append("Владелец не установлен.")
            verdict = "REJECTED" if reasons else "COMPATIBLE" if normalize_content(bc.text) == normalize_content(ac.text) else "PARTIAL"
            if not reasons: reasons.append("Текст совместим с гипотезой; распоряжение о передаче и полнота охвата отдельно не доказаны.")
            candidates.append(CandidateAssessment(claim_id=ac.id, owner=units[ac.unit_id].name,
                action_matches=action, scope_matches=scope, authority_matches=authority,
                verdict=verdict, reasons=reasons, source_span_ids=ac.source_span_ids))
            log("compare_candidate", f"{units[ac.unit_id].name}: {ac.text}\n{verdict}: "+" ".join(reasons), bc.source_span_ids+ac.source_span_ids, [bc.id, ac.id])
    # Run disconfirmation over all extracted after claims, not just selected hits.
    counter = []
    if bc:
        for ac in after:
            same_object = bool(atoms(bc) & atoms(ac)) or normalize_content(bc.text) == normalize_content(ac.text)
            if same_object and (not compatible(bc, ac) or units[ac.unit_id].key != units[bc.unit_id].key):
                counter.append(ac)
    counter_source = [s for c in counter for s in c.source_span_ids]
    counter_source += [s for f in fs for e in f.evidence_against for s in e.source_span_ids]
    log("search_counter_evidence", f"Проверены все {len(after)} извлечённых функций после изменения: конкурирующие владельцы, несовместимые полномочия/контекст и контраргументы исходного правила. Найдено {len(counter)} текстовых кандидатов. Отсутствие лексического совпадения не исключает смысловой альтернативы.",
        counter_source, [c.id for c in counter], [s.id for d in record.ir.documents if d.version == "after" for s in d.spans])
    # Recompute composition from source-backed claims after candidate checks.
    split = composition(bc, after, units) if bc and not proven else []
    merge = []
    if bc and not proven:
        old = [c for c in record.ir.claims if c.version == "before"]
        for ac in after:
            parts = composition(ac, old, units)
            if any(c.id == bc.id for c in parts): merge.append((ac, parts))
    exact_alternative = bool(bc) and any(compatible(bc, ac) and normalize_content(bc.text) == normalize_content(ac.text) for ac in after)
    if not proven and r.relation not in ("DUPLICATED", "POTENTIAL_AUTHORITY_CONFLICT") and not exact_alternative:
        if split and not merge: current = "SPLIT"
        elif len(merge) == 1 and not split: current = "MERGED"
        elif r.relation == "POTENTIAL_GAP": current = "POTENTIAL_GAP"
        else: current = "UNKNOWN"
    else:
        current = r.relation
    log("revise_hypothesis", f"{initial} → {current}. "+r.explanation, r.source_span_ids,
        r.before_claim_ids+r.after_claim_ids)
    log("request_human_review", "Рекомендация ожидает решения аудитора. Проверить полномочия, область ответственности и непрочитанные приложения. Канонический audit record не изменён.", r.source_span_ids)
    return DebugInvestigation(lineage_id=r.lineage_id, responsibility_id=r.id,
        initial_hypothesis=initial, final_hypothesis=current, revised=current != initial,
        steps=steps, candidates=candidates, source_span_ids=list(dict.fromkeys(s for t in steps for s in t.source_span_ids)),
        limitation="Детерминированное расследование выполняет реальные поиски и проверки. Семантическое покрытие ограничено извлечённым текстом; SPLIT/MERGED — гипотезы буквального покрытия. Вызов LLM не выполняется.")
