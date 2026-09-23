"""Versioned structural parser. A shared role is never assigned to one department.

Known section titles and their hierarchy are supported for this regulation family;
clause numbers are locators only. Unknown layouts create review findings.
"""

import re
from .ingest import normalized, normalize_content, strip_label, digest
from .models import Document, FunctionClaim, OrganizationalIR, Unit


def key(text: str) -> str:
    return normalize_content(text).replace("c ", "с ")


def body_spans(doc):
    """Do not treat the table of contents as a second set of provisions."""
    if hasattr(doc, "documents"):
        return [s for d in doc.documents for s in body_spans(d)]
    result = []
    for span in doc.spans:
        if normalized(span.exact_text) == "оглавление":
            break
        result.append(span)
    return result


def inventory_spans(doc):
    """Return the explicit inventory header and entries, independent of labels."""
    if hasattr(doc, "documents"):
        return [s for d in doc.documents for s in inventory_spans(d)]
    result = []
    active = False
    for s in body_spans(doc):
        if "состоит из следующих структурных подразделений" in normalized(s.exact_text):
            active = True
            result.append(s)
        elif active and re.match(r"^\s*[а-яa-z][.)]\s", s.exact_text, re.I):
            result.append(s)
        else:
            active = False
    return result


def extract(documents: list[Document]) -> OrganizationalIR:
    documents = sorted(
        documents, key=lambda d: (d.version != "before", d.name, d.sha256)
    )
    units, claims = [], []
    for doc in documents:
        departments = []
        for s in inventory_spans(doc):
            if re.match(r"^\s*[а-яa-z][.)]\s", s.exact_text, re.I):
                name = strip_label(s.exact_text).rstrip(".")
                unit = Unit(
                    id=f"{doc.id}:u:{digest(key(name).encode())[:10]}",
                    key=key(name),
                    name=name,
                    version=doc.version,
                    kind="department",
                    source_span_ids=[s.id],
                )
                departments.append(unit)
                units.append(unit)
        owner = None
        owner_span = None
        parent_span = None
        authority = "unknown"
        owner_context = ""
        owner_context_ids = []
        role_section = None
        function_section = None
        function_block = None
        block_head = None
        for s in body_spans(doc):
            text = strip_label(s.exact_text)
            content = normalized(s.exact_text)
            # Discover sections by their explicit titles, not by numeric addresses.
            if (
                re.match(r"^\s*\d+[.\s]", s.exact_text)
                and "." not in s.clause
                and "/" not in s.clause
            ):
                owner = owner_span = parent_span = None
                owner_context = ""
                owner_context_ids = []
                function_block = None
                role_section = (
                    s.section
                    if content
                    in (
                        "права и обязанности",
                        "функции и полномочия",
                        "функции подразделений",
                        "должностные обязанности",
                        "функциональные обязанности",
                        "функции",
                        "обязанности",
                    )
                    else None
                )
                function_section = (
                    s.section
                    if content == "цели, задачи и функции внутреннего аудита"
                    else None
                )
                block_head = s if function_section else None
                continue
            role_heading = (
                role_section is not None
                and s.section == role_section
                and s.clause.count(".") == 1
                and "/" not in s.clause
            )
            if role_section and content == "главный аудитор":
                role_heading = True
            if role_heading:
                # A subjectless duty block may inherit only the immediately
                # preceding explicit Chief Auditor header, never its clause number.
                chief_block = (
                    content.startswith(
                        "организует работу бва, осуществляя общее руководство и распределение обязанностей"
                    )
                    and owner is not None
                    and owner.key == "главный аудитор"
                    and owner_span is not None
                    and normalized(owner_span.exact_text) == "главный аудитор"
                )
                if chief_block:
                    text_for_owner = owner.name
                    owner_context = text
                    owner_context_ids = [s.id]
                else:
                    owner_context_ids = []
                    text_for_owner = re.split(
                        r"\s+(?:обязан|обязаны|имеет|имеют|не имеет|не имеют)\b|\s*:",
                        text,
                        flags=re.I,
                    )[0].strip()
                    owner_context = text[len(text_for_owner) :].strip(" :")
                if "общество обеспечивает:" in text.casefold():
                    text_for_owner = "Общество"
                    owner_context = text
                if text_for_owner and (
                    re.match(
                        r"^(Директор|Начальник|Руководитель|Отдел|Департамент|Главный аудитор|Работники|Подразделение|Общество$)",
                        text_for_owner,
                        re.I,
                    )
                ):
                    uid = f"{doc.id}:r:{digest(key(text_for_owner).encode())[:10]}"
                    dept_ids = []
                    for d in departments:
                        short = re.search(r"\(([^)]+)\)", d.name)
                        if (
                            short
                            and re.search(
                                r"\b" + re.escape(short[1]) + r"\b",
                                text_for_owner,
                                re.I,
                            )
                        ) or key(d.name.split(" (")[0]).replace(
                            "департамент ", ""
                        ) in key(
                            text_for_owner
                        ):
                            dept_ids.append(d.id)
                    authority = (
                        "prohibition"
                        if re.search(r"\bне име(?:ет|ют) права\b", content)
                        else (
                            "right"
                            if re.search(r"\bиме(?:ет|ют) право\b", content)
                            else "duty"
                        )
                    )
                    owner = next((u for u in units if u.id == uid), None)
                    if not owner:
                        owner = Unit(
                            id=uid,
                            key=key(text_for_owner),
                            name=text_for_owner,
                            version=doc.version,
                            kind=(
                                "collective"
                                if len(dept_ids) > 1
                                or text_for_owner.casefold().startswith(
                                    ("работники", "директоры", "общество")
                                )
                                or " и работники" in text_for_owner.casefold()
                                else "role"
                            ),
                            source_span_ids=[s.id],
                            department_ids=dept_ids,
                        )
                        units.append(owner)
                    if not chief_block:
                        owner_span = s
                    parent_span = None
                    continue
                # Keep duties under unknown headings, with an explicitly unresolved
                # owner, so they enter review instead of silently disappearing.
                owner = Unit(
                    id=f"{doc.id}:unresolved:{s.paragraph_id}",
                    key=f"unresolved:{s.id}",
                    name="Владелец не установлен",
                    version=doc.version,
                    kind="unresolved",
                    source_span_ids=[s.id],
                )
                units.append(owner)
                owner_span, parent_span = s, None
                owner_context = text
                authority = "unknown"
                continue
            if function_section is not None and s.section == function_section:
                if s.clause.count(".") == 1 and "/" not in s.clause:
                    function_block = (
                        s.clause
                        if content
                        in (
                            "для достижения целей внутренний аудит решает поставленные перед ним в обществе задачи по следующим основным направлениям",
                            "для решения поставленных задач и достижения целей внутренний аудит осуществляет следующие функции",
                        )
                        else None
                    )
                    owner = owner_span = parent_span = None
                in_block = function_block and s.clause.startswith(function_block + ".")
                if block_head and in_block:
                    uid = f"{doc.id}:block"
                    owner = next((u for u in units if u.id == uid), None)
                    if not owner:
                        owner = Unit(
                            id=uid,
                            key="внутренний аудит",
                            name="Внутренний аудит (общие функции)",
                            version=doc.version,
                            kind="collective",
                            source_span_ids=[block_head.id],
                        )
                        units.append(owner)
                    owner_span, authority = block_head, "duty"
                    owner_context = ""
                else:
                    continue
            elif role_section is None or s.section != role_section:
                owner = None
                parent_span = None
                continue
            if not owner or not owner_span:
                continue
            if not (
                re.match(r"^\s*\d+(?:\.\d+){2}", s.exact_text)
                or re.match(r"^\s*[а-яa-z][.)]\s", s.exact_text, re.I)
            ):
                continue
            is_child = "/" in s.clause
            if not is_child:
                parent_span = s
            context = "\n".join(
                x
                for x in [
                    owner_context,
                    (
                        strip_label(parent_span.exact_text)
                        if is_child and parent_span
                        else ""
                    ),
                ]
                if x
            )
            ids = [s.id, owner_span.id, *owner_context_ids]
            if is_child and parent_span:
                ids.append(parent_span.id)
            first, _, rest = text.partition(" ")
            claims.append(
                FunctionClaim(
                    id=f"{s.id}:claim",
                    version=doc.version,
                    unit_id=owner.id,
                    action=first,
                    object=rest,
                    scope=context,
                    authority=authority,
                    text=text,
                    context_text=context,
                    source_span_ids=list(dict.fromkeys(ids)),
                    extraction=(
                        "explicit"
                        if len(text.strip(" ;:.")) > 3 and owner.kind != "unresolved"
                        else "unresolved"
                    ),
                )
            )
    from .corpus import consolidate_units

    return consolidate_units(
        OrganizationalIR(documents=documents, units=units, claims=claims)
    )
