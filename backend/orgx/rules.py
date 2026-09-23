"""Generic, conservative rules independent of the demonstration paragraphs."""

import re
from itertools import combinations
from .models import Evidence, UnitChange
from .ingest import normalize_content, strip_label, digest
from .extract import body_spans
from .retrieval import tokens, corpus_search


def apply_general_rules(ir, changes, findings, searches, add):
    units = {u.id: u for u in ir.units}
    old = [c for c in ir.claims if c.version == "before"]
    new = [c for c in ir.claims if c.version == "after"]
    before_docs = [d for d in ir.documents if d.version == "before"]
    after_spans = [
        s for d in ir.documents if d.version == "after" for s in body_spans(d)
    ]
    token_map = {c.id: tokens(c.text) for c in new}
    norm = {c.id: normalize_content(c.text) for c in old + new}

    def ev(text, ids, search_ids=()):
        return Evidence(
            text=text,
            source_span_ids=list(dict.fromkeys(ids)),
            search_result_ids=list(search_ids),
        )

    def owner_matches(claim, name):
        u = units[claim.unit_id]
        return normalize_content(name) in {
            u.key,
            *[units[d].key for d in u.department_ids if d in units],
        }

    def replace_chain(bc):
        findings[:] = [
            f
            for f in findings
            if not (f.before_claim_id == bc.id and f.concern in ("", "matching", "gap"))
        ]

    # Only an explicit operative instruction, with exact named actors and function,
    # can establish a general transfer/reorganization. Mentions and projects cannot.
    for source in after_spans:
        text = strip_label(source.exact_text).strip()
        directive = re.fullmatch(
            r"Передать функцию «(.+?)» от «(.+?)» к «(.+?)»[.;]?", text, re.I
        )
        if directive:
            duty, previous, following = directive.groups()
            bcs = [
                c
                for c in old
                if norm[c.id] == normalize_content(duty) and owner_matches(c, previous)
            ]
            acs = [c for c in new if norm[c.id] == normalize_content(duty)]
            if len(bcs) == len(acs) == 1:
                bc, ac = bcs[0], acs[0]
                if (
                    owner_matches(ac, following)
                    and bc.extraction == ac.extraction == "explicit"
                    and bc.authority == ac.authority != "unknown"
                    and normalize_content(bc.context_text)
                    == normalize_content(ac.context_text)
                ):
                    replace_chain(bc)
                    add(
                        "MOVED",
                        "Передача функции прямо указана в документе",
                        "Распорядительный пункт называет функцию и обоих владельцев; формулировка, полномочие и контекст совпадают. Это текстовое перераспределение в переданном комплекте.",
                        bc,
                        [ac],
                        [
                            ev(
                                "Прямая инструкция и обе версии функции.",
                                bc.source_span_ids + ac.source_span_ids + [source.id],
                            )
                        ],
                        [
                            ev(
                                "Документы не подтверждают фактическое исполнение или юридическое правопреемство.",
                                [source.id],
                            )
                        ],
                        rule="explicit-transfer-directive-v1",
                        confidence="high",
                    )
        exclusion = re.fullmatch(
            r"Исключить функцию «(.+?)» из перечня обязанностей[.;]?", text, re.I
        )
        if exclusion:
            bcs = [
                c
                for c in old
                if norm[c.id] == normalize_content(exclusion[1])
                and c.extraction == "explicit"
            ]
            if len(bcs) == 1 and not any(norm[c.id] == norm[bcs[0].id] for c in new):
                bc = bcs[0]
                replace_chain(bc)
                add(
                    "POTENTIAL_GAP",
                    "Прямо указано исключение функции из перечня",
                    "Новый документ прямо исключает прежнюю функцию; точный соответствующий пункт с владельцем в переданном комплекте не найден. Проверить смысловые эквиваленты и другие действующие основания. Полная потеря функции не доказана.",
                    bc,
                    [],
                    [
                        ev(
                            "Прежняя обязанность и прямая инструкция об исключении.",
                            bc.source_span_ids + [source.id],
                            ["search:" + bc.id],
                        )
                    ],
                    [
                        ev(
                            "Исключение из перечня не исключает другого основания или перефразирования; требуется решение аудитора.",
                            [source.id],
                        )
                    ],
                    rule="explicit-exclusion-gap-v1",
                    concern="gap",
                )
        reorg = re.fullmatch(
            r"Преобразовать подразделение «(.+?)» в подразделение «(.+?)»[.;]?",
            text,
            re.I,
        )
        if reorg:
            a, b = (normalize_content(t) for t in reorg.groups())
            us = [u for u in ir.units if u.kind == "department"]
            left = [u for u in us if u.version == "before" and u.key == a]
            right = [u for u in us if u.version == "after" and u.key == b]
            if (
                len(left) == len(right) == 1
                and not any(u.version == "after" and u.key == a for u in us)
                and not any(u.version == "before" and u.key == b for u in us)
            ):
                ids = left[0].source_span_ids + right[0].source_span_ids + [source.id]
                changes[:] = [
                    c for c in changes if c.title not in (left[0].name, right[0].name)
                ]
                changes.append(
                    UnitChange(
                        id="unit-directive:" + digest(source.id.encode())[:16],
                        status="REORGANIZED",
                        title=left[0].name + " → " + right[0].name,
                        detail="Преобразование прямо указано в переданном распорядительном документе и согласуется с двумя перечнями. Фактическое исполнение отдельно не проверено.",
                        source_span_ids=ids,
                    )
                )

    seen = {
        tuple(sorted(f.after_claim_ids))
        for f in findings
        if f.concern == "duplicate" and len(f.after_claim_ids) == 2
    }
    for a, b in combinations(new, 2):
        ua, ub = units[a.unit_id], units[b.unit_id]
        if a.extraction != "explicit" or b.extraction != "explicit":
            continue
        identical = norm[a.id] == norm[b.id]
        same_context = normalize_content(a.context_text) == normalize_content(
            b.context_text
        )
        opposite = (a.authority == "prohibition") != (
            b.authority == "prohibition"
        ) and "unknown" not in (a.authority, b.authority)

        def scope_without_modality(value):
            return re.sub(
                r"^(?:не\s+)?име(?:ет|ют)\s+прав[оа]\b|^обязан[ы]?\b",
                "",
                normalize_content(value),
            ).strip()

        conflict = (
            identical
            and scope_without_modality(a.context_text)
            == scope_without_modality(b.context_text)
            and ua.key == ub.key
            and opposite
        )
        if ua.key == ub.key and not conflict:
            continue
        pair = tuple(sorted([a.id, b.id]))
        if pair in seen or (
            not conflict and (len(token_map[a.id]) < 4 or len(token_map[b.id]) < 4)
        ):
            continue
        intersection = len(token_map[a.id] & token_map[b.id])
        similarity = intersection / max(1, len(token_map[a.id] | token_map[b.id]))
        if not identical and (intersection < 4 or similarity < 0.55):
            continue
        seen.add(pair)
        before = next((c for c in old if norm[c.id] == norm[a.id]), None)
        reverse = None
        old_ids = before.source_span_ids if before else []
        if not before:
            reverse = corpus_search(
                ir.documents, a.text, "before", "pair:" + "|".join(pair)
            )
            searches.append(reverse)
            old_ids = reverse.matched_span_ids[:3] or [
                d.spans[0].id for d in before_docs
            ]
        relative = any(
            x in (a.text + " " + a.context_text + " " + b.context_text).casefold()
            for x in (
                "в зоне",
                "своей",
                "своих",
                "в пределах",
                "прочих поручений",
                "план работ",
                "запрашивает",
                "выносит предложения",
            )
        )
        independent = (
            ua.kind == ub.kind == "role"
            and bool(ua.department_ids)
            and bool(ub.department_ids)
            and not set(ua.department_ids) & set(ub.department_ids)
        )
        if conflict:
            kind, title, concern = (
                "POTENTIAL_AUTHORITY_CONFLICT",
                "Разрешение и запрет у одного ответственного",
                "authority",
            )
        elif (
            identical
            and same_context
            and independent
            and not relative
            and a.authority == b.authority == "duty"
        ):
            kind, title, concern = (
                "POTENTIAL_DUPLICATE",
                "Совпадающие обязанности у разных ответственных",
                "duplicate",
            )
        else:
            kind, title, concern = (
                "REQUIRES_HUMAN_REVIEW",
                "Проверить пересечение функций новой версии",
                "duplicate",
            )
        add(
            kind,
            title,
            "Сопоставлены два пункта новой версии, независимо от наличия прежней функции. "
            + (
                "У одного ответственного совпадает формулировка в сопоставимом контексте, но различается разрешение и запрет."
                if conflict
                else "Совпадение текста или предмета требует проверки границ, результата и взаимодействия владельцев."
            ),
            before,
            [a, b],
            [
                ev(
                    "Пункты новой версии и основание сопоставления со старым комплектом.",
                    old_ids + a.source_span_ids + b.source_span_ids,
                    [reverse.id] if reverse else [],
                )
            ],
            [
                ev(
                    "Разные области ответственности, совместная работа, контекст или статус документа могут объяснять пересечение. Нарушение не установлено.",
                    a.source_span_ids + b.source_span_ids,
                )
            ],
            rule=(
                "cross-owner-exact-duty-v1"
                if identical and not conflict
                else (
                    "same-owner-opposite-authority-v1"
                    if conflict
                    else "cross-owner-partial-duty-v1"
                )
            ),
            concern=concern,
            confidence="low" if kind == "REQUIRES_HUMAN_REVIEW" else "medium",
        )
