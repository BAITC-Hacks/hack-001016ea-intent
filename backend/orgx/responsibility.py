"""Stable responsibility fingerprints and conservative, explicit lineage.

A shared fingerprint is NOT proof of equivalence. Documentary rules establish
links; exact conjunction coverage can only suggest SPLIT/MERGED for review.
"""
import re
from collections import defaultdict
from .ingest import digest, normalize_content
from .debugger_models import Responsibility


def fingerprint(claim):
    # Excludes document/version/paragraph/owner: ownership is tracked separately.
    # Keep quantities, negation and scope. Cosmetic labels were removed at ingest.
    value = "\x1f".join(normalize_content(x) for x in
                        (claim.action, claim.object, claim.context_text, claim.authority))
    return "R-" + digest(value.encode())[:16].upper()


def compatible(left, right):
    return (normalize_content(left.action) == normalize_content(right.action)
            and normalize_content(left.context_text) == normalize_content(right.context_text)
            and left.authority == right.authority and left.authority != "unknown"
            and left.extraction == right.extraction == "explicit")


def atoms(claim):
    """Only literal flat lists, not free-form semantic decomposition."""
    action, _, obj = normalize_content(claim.text).partition(" ")
    if not obj or re.search(r"\b(или|либо|кроме|исключая|если|при|не)\b|[():]", obj):
        return frozenset()
    parts = [p.strip(" ;.") for p in re.split(r"\s+и\s+|,\s*", obj)]
    if not all(parts) or len(set(parts)) != len(parts):
        return frozenset()
    return frozenset(action + " " + p for p in parts)


def composition(composite, components, units):
    """Require complete non-overlapping literal coverage and compatible context.

    Competing claims covering the same part block an apparently unique split.
    No inflection, synonym, broad/narrow or inferred-owner equivalence is used.
    """
    whole = atoms(composite)
    if not 2 <= len(whole) <= 6:
        return []
    choices = []
    for c in components:
        part = atoms(c)
        owner = units[c.unit_id]
        if (part and part < whole and compatible(composite, c)
                and owner.kind not in ("unresolved", "collective")):
            choices.append((c, part))
    if any(len(part) > 1 for _, part in choices):
        return []  # competing broader composition; do not pick a convenient cover
    # Literal singletons make coverage transparent and bound combinatorics.
    chosen = []
    for atom in sorted(whole):
        candidates = [c for c, part in choices if part == {atom}]
        if len(candidates) != 1:
            return []
        chosen.append(candidates[0])
    return chosen


def build_responsibilities(record):
    units = {u.id: u for u in record.ir.units}
    old = [c for c in record.ir.claims if c.version == "before"]
    new = [c for c in record.ir.claims if c.version == "after"]
    linked = defaultdict(list)
    for f in record.findings:
        if f.before_claim_id:
            linked[f.before_claim_id].append(f)
    searches = defaultdict(list)
    for s in record.search_results:
        if s.before_claim:
            searches[s.before_claim].extend(c.after_claim for c in s.candidates)
    merges = {}
    for ac in new:
        parts = composition(ac, old, units)
        if parts:
            for c in parts:
                merges.setdefault(c.id, []).append((ac, parts))
    result = []
    claimed_after = set()
    mapping = {"POTENTIAL_DUPLICATE": "DUPLICATED", "REQUIRES_HUMAN_REVIEW": "UNKNOWN"}
    priority = {"POTENTIAL_AUTHORITY_CONFLICT": 0, "POTENTIAL_DUPLICATE": 1,
                "POTENTIAL_GAP": 2, "MOVED": 3, "PRESERVED": 4, "REQUIRES_HUMAN_REVIEW": 5}
    for bc in old:
        fs = sorted(linked[bc.id], key=lambda f: priority.get(f.type, 9))
        canonical = next((f for f in fs if f.type in ("PRESERVED", "MOVED")), None)
        source = list(bc.source_span_ids)
        successors, before_ids = [], [bc.id]
        basis, relation = "UNRESOLVED", "UNKNOWN"
        explanation = "Сходство формирует кандидатов; тождество ответственности и её передача не доказаны."
        if fs:
            relation = mapping.get(fs[0].type, fs[0].type)
            explanation = fs[0].explanation
        candidates = list(dict.fromkeys(searches[bc.id] + [c for f in fs for c in f.after_claim_ids]))
        if canonical:
            successors = canonical.after_claim_ids
            basis = "DOCUMENTARY_RULE"
        split = composition(bc, new, units) if not canonical else []
        merge = merges.get(bc.id, []) if not canonical else []
        # An unchanged full formulation competes with a composition hypothesis.
        exact_alternative = any(compatible(bc, ac) and
            normalize_content(bc.text) == normalize_content(ac.text) for ac in new)
        if relation not in ("DUPLICATED", "POTENTIAL_AUTHORITY_CONFLICT") and not exact_alternative:
            if split and not merge:
                relation, basis = "SPLIT", "COMPOSITION_HYPOTHESIS"
                successors = [c.id for c in split]
                source += [s for c in split for s in c.source_span_ids]
                explanation = "Найдено полное непересекающееся текстовое покрытие частей исходной функции при одинаковых action, scope и authority. Это гипотеза разделения; распоряжение о передаче и фактические границы требуют человека."
            elif len(merge) == 1 and not split:
                ac, parts = merge[0]
                relation, basis = "MERGED", "COMPOSITION_HYPOTHESIS"
                before_ids, successors = [bc.id] + [c.id for c in parts if c.id != bc.id], [ac.id]
                source += ac.source_span_ids + [s for c in parts for s in c.source_span_ids]
                explanation = "Несколько исходных функций полностью покрывают буквальные части одной новой функции при совместимых action, scope и authority. Это гипотеза объединения, а не доказательство правопреемства."
        for f in fs:
            source += f.source_span_ids
        claimed_after.update(successors)
        result.append(Responsibility(id=fingerprint(bc), lineage_id="lineage:"+bc.id,
            before_claim_ids=before_ids, after_claim_ids=successors,
            candidate_claim_ids=list(dict.fromkeys(candidates+successors)), relation=relation,
            basis=basis, finding_ids=[f.id for f in fs], source_span_ids=list(dict.fromkeys(source)),
            explanation=explanation))
    # New-version occurrences remain visible even without a before predecessor.
    for ac in new:
        if ac.id in claimed_after:
            continue
        fs = [f for f in record.findings if not f.before_claim_id and ac.id in f.after_claim_ids]
        kind = min(fs, key=lambda f: priority.get(f.type, 9)).type if fs else "REQUIRES_HUMAN_REVIEW"
        result.append(Responsibility(id=fingerprint(ac), lineage_id="lineage:"+ac.id,
            before_claim_ids=[], after_claim_ids=[ac.id], candidate_claim_ids=[],
            relation=mapping.get(kind, kind), basis="UNRESOLVED", finding_ids=[f.id for f in fs],
            source_span_ids=list(dict.fromkeys(ac.source_span_ids+[s for f in fs for s in f.source_span_ids])),
            explanation="Функция присутствует после изменения; происхождение и связь с прежними функциями требуют проверки."))
    # Some documentary risks (e.g. governance vs audit independence) live outside
    # extracted duty blocks. Keep those explicit instead of hiding them in a count.
    attached = {fid for r in result for fid in r.finding_ids}
    for f in record.findings:
        if f.id in attached or f.before_claim_id:
            continue
        result.append(Responsibility(id="E-"+digest(f.rule_id.encode())[:16].upper(),
            lineage_id="lineage:"+f.id, before_claim_ids=[], after_claim_ids=f.after_claim_ids,
            candidate_claim_ids=[], relation=mapping.get(f.type,f.type), basis="UNRESOLVED",
            finding_ids=[f.id], source_span_ids=f.source_span_ids, explanation=f.explanation))
    return result
