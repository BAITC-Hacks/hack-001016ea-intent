"""Deterministic sets of documents; source IDs always point to real inputs."""

import json
import re
from .ingest import digest, normalize_content


def ordered_documents(documents):
    docs = sorted(documents, key=lambda d: (d.version != "before", d.name, d.sha256))
    if {d.version for d in docs} != {"before", "after"}:
        raise ValueError("Нужен хотя бы один документ в каждом комплекте.")
    if len({(d.version, d.sha256) for d in docs}) != len(docs):
        raise ValueError(
            "Один и тот же файл повторяется внутри версии; удалите дубликат."
        )
    return docs


class Corpus:
    def __init__(self, documents, version):
        self.documents = [d for d in documents if d.version == version]
        self.version = version
        self.spans = [s for d in self.documents for s in d.spans]
        self.id = self.documents[0].id  # legacy single-document search pointer
        self.name = json.dumps([d.name for d in self.documents], ensure_ascii=False)
        self.sha256 = digest(
            json.dumps(
                [(d.sha256, d.name) for d in self.documents], ensure_ascii=False
            ).encode()
        )
        self.warnings = [f"{d.name}: {w}" for d in self.documents for w in d.warnings]


def consolidate_units(ir):
    """Merge explicit same-name units within one submitted version, not across time."""
    groups, remap = {}, {}
    for unit in ir.units:
        identity = (unit.version, unit.kind, unit.key)
        if identity not in groups:
            groups[identity] = unit
        else:
            first = groups[identity]
            groups[identity] = first.model_copy(
                update={
                    "source_span_ids": list(
                        dict.fromkeys(first.source_span_ids + unit.source_span_ids)
                    ),
                    "department_ids": list(
                        dict.fromkeys(first.department_ids + unit.department_ids)
                    ),
                }
            )
        remap[unit.id] = groups[identity].id
    units = list(groups.values())
    departments = [u for u in units if u.kind == "department"]
    resolved = []
    for u in units:
        ids = [remap.get(d, d) for d in u.department_ids]
        if u.kind in ("role", "collective"):
            for dept in departments:
                if dept.version != u.version:
                    continue
                short = re.search(r"\(([^)]+)\)", dept.name)
                if short and re.search(
                    r"\b" + re.escape(short[1]) + r"\b", u.name, re.I
                ):
                    ids.append(dept.id)
        resolved.append(u.model_copy(update={"department_ids": sorted(set(ids))}))
    return ir.model_copy(
        update={
            "units": resolved,
            "claims": [
                c.model_copy(update={"unit_id": remap[c.unit_id]}) for c in ir.claims
            ],
        }
    )
