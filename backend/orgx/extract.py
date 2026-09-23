"""Versioned structural parser. A shared role is never assigned to one department.

Section 2 and 5 are supported for this regulation family; other material stays
searchable evidence. Unknown layouts create review findings, not invented owners.
"""
import re
from .ingest import normalized, strip_label, digest
from .models import Document, FunctionClaim, OrganizationalIR, Unit

def key(text: str) -> str:
    return normalized(text).replace('c ', 'с ')

def extract(documents: list[Document]) -> OrganizationalIR:
    units, claims = [], []
    for doc in documents:
        departments = []
        inventory = False
        for s in doc.spans:
            if 'состоит из следующих структурных подразделений' in s.exact_text:
                inventory = True
                continue
            if inventory and not re.match(r'^\s*[а-яa-z][.)]', s.exact_text):
                inventory = False
            if inventory:
                name = strip_label(s.exact_text).rstrip('.')
                unit = Unit(id=f'{doc.id}:u:{digest(key(name).encode())[:10]}', key=key(name), name=name,
                            version=doc.version, kind='department', source_span_ids=[s.id])
                departments.append(unit)
                units.append(unit)
        owner = None
        owner_span = None
        parent_span = None
        authority = 'unknown'
        for s in doc.spans:
            text = strip_label(s.exact_text)
            # Stop at contents. Cross references do not create duplicate claims.
            if s.exact_text.strip().casefold() == 'оглавление':
                break
            role_heading = s.section == '5' and s.clause.count('.') == 1 and '/' not in s.clause
            if s.exact_text.strip() == 'Главный аудитор:':
                role_heading = True
            if role_heading:
                # 5.1/5.2 carry duties of Chief Auditor, not an extra fictional unit.
                if re.match(r'^5\.[12]\.', s.exact_text) and not text.startswith('Главный аудитор'):
                    if not owner or owner.name != 'Главный аудитор':
                        text_for_owner = 'Главный аудитор'
                    else:
                        text_for_owner = owner.name
                else:
                    text_for_owner = re.split(r'\s+(?:обязан|обязаны|имеют|не имеют)\b|\s*:', text)[0].strip()
                if text.startswith('Главный аудитор обязан'):
                    text_for_owner = 'Главный аудитор'
                if 'Общество обеспечивает:' in text:
                    text_for_owner = 'Общество'
                if text_for_owner and (re.match(r'^(Директор|Главный аудитор|Работники|Подразделение|Общество$)', text_for_owner)):
                    uid = f'{doc.id}:r:{digest(key(text_for_owner).encode())[:10]}'
                    dept_ids = []
                    for d in departments:
                        short = re.search(r'\(([^)]+)\)', d.name)
                        if (short and re.search(r'\b'+re.escape(short[1])+r'\b', text_for_owner)) or key(d.name.split(' (')[0]).replace('департамент ', '') in key(text_for_owner):
                            dept_ids.append(d.id)
                    authority = 'prohibition' if 'не имеют права' in text else 'right' if 'имеет право' in text or 'имеют право' in text else 'duty'
                    owner = next((u for u in units if u.id == uid), None)
                    if not owner:
                        owner = Unit(id=uid, key=key(text_for_owner), name=text_for_owner, version=doc.version,
                                     kind='collective' if len(dept_ids)>1 or text_for_owner.startswith(('Работники', 'Директоры', 'Общество')) else 'role',
                                     source_span_ids=[s.id], department_ids=dept_ids)
                        units.append(owner)
                    owner_span = s
                    parent_span = None
                    continue
                # Keep duties under unknown headings, with an explicitly unresolved
                # owner, so they enter review instead of silently disappearing.
                owner = Unit(id=f'{doc.id}:unresolved:{s.paragraph_id}',key=f'unresolved:{s.id}',
                             name='Владелец не установлен',version=doc.version,kind='unresolved',source_span_ids=[s.id])
                units.append(owner)
                owner_span, parent_span = s, None
                authority = 'unknown'
                continue
            if s.section == '2' and s.clause.startswith(('2.3', '2.4')):
                # Explicit section heading defines internal audit at block level.
                block_head = next((x for x in doc.spans if '2. Цели, задачи и функции внутреннего аудита' in x.exact_text), None)
                if block_head:
                    uid = f'{doc.id}:block'
                    owner = next((u for u in units if u.id == uid), None)
                    if not owner:
                        owner = Unit(id=uid, key='внутренний аудит', name='Внутренний аудит (общие функции)', version=doc.version, kind='collective', source_span_ids=[block_head.id])
                        units.append(owner)
                    owner_span, authority = block_head, 'duty'
            elif s.section != '5':
                owner = None
                parent_span = None
                continue
            if not owner or not owner_span:
                continue
            if not (re.match(r'^\d+(?:\.\d+){2}', s.exact_text) or re.match(r'^[а-яa-z][.)]\s', s.exact_text)):
                continue
            is_child = '/' in s.clause
            if not is_child:
                parent_span = s
            context = strip_label(parent_span.exact_text) if is_child and parent_span else ''
            ids = [s.id, owner_span.id]
            if is_child and parent_span:
                ids.append(parent_span.id)
            first, _, rest = text.partition(' ')
            claims.append(FunctionClaim(id=f'{s.id}:claim', version=doc.version, unit_id=owner.id,
                          action=first, object=rest, scope=owner.name, authority=authority,
                          text=text, context_text=context, source_span_ids=list(dict.fromkeys(ids)),
                          extraction='explicit' if len(text.strip(' ;:.'))>3 and owner.kind!='unresolved' else 'unresolved'))
    return OrganizationalIR(documents=documents, units=units, claims=claims)
