"""Reject broken provenance rather than presenting an unsupported finding."""
from .ingest import normalize_content, strip_label


def validate_sources(record):
    docs = {d.id: d for d in record.ir.documents}
    if len(docs) != len(record.ir.documents):
        raise ValueError("Duplicate document identity")
    spans = {}
    for d in record.ir.documents:
        for s in d.spans:
            if s.id in spans or s.document_id != d.id or s.version != d.version:
                raise ValueError("Source document/version identity mismatch")
            if not s.exact_text.strip():
                raise ValueError("Empty source fragment")
            spans[s.id] = s
    claims = {c.id: c for c in record.ir.claims}
    if len(claims) != len(record.ir.claims):
        raise ValueError("Duplicate claim identity")
    units = {u.id: u for u in record.ir.units}
    for c in claims.values():
        if not c.source_span_ids or c.unit_id not in units:
            raise ValueError("Claim lacks source or owner reference")
        if units[c.unit_id].version != c.version:
            raise ValueError("Claim owner version mismatch")
        if any(s not in spans or spans[s].version != c.version for s in c.source_span_ids):
            raise ValueError("Claim source version mismatch")
        source = spans[c.source_span_ids[0]]
        if normalize_content(c.text) != normalize_content(strip_label(source.exact_text)):
            raise ValueError("Claim text differs from exact source")
    searches = {s.id: s for s in record.search_results}
    if len(searches) != len(record.search_results):
        raise ValueError("Duplicate search identity")
    for s in searches.values():
        if any(x not in spans or spans[x].version != s.searched_version for x in s.searched_span_ids):
            raise ValueError("Search source version mismatch")
        if not set(s.matched_span_ids) <= set(s.searched_span_ids):
            raise ValueError("Search result outside searched source")
        if s.exhaustive:
            expected = {x.id for d in docs.values() if d.version == s.searched_version for x in d.spans}
            if set(s.searched_span_ids) != expected:
                raise ValueError("Incomplete search presented as exhaustive")
        for candidate in s.candidates:
            if (candidate.before_claim not in claims or candidate.after_claim not in claims
                or claims[candidate.before_claim].version != "before"
                or claims[candidate.after_claim].version != "after"
                or any(x not in spans for x in candidate.evidence)):
                raise ValueError("Invalid candidate evidence")
    for f in record.findings:
        if not f.evidence_for or not f.source_span_ids:
            raise ValueError("Finding lacks source evidence")
        if any(x not in spans for x in f.source_span_ids) or any(x not in searches for x in f.search_result_ids):
            raise ValueError("Unknown finding source/search")
        if f.before_claim_id and (f.before_claim_id not in claims or claims[f.before_claim_id].version != "before"):
            raise ValueError("Finding before claim version mismatch")
        for e in f.evidence_for + f.evidence_against:
            if any(x not in spans for x in e.source_span_ids) or any(x not in searches for x in e.search_result_ids):
                raise ValueError("Broken finding evidence")
        if not any(e.source_span_ids or e.search_result_ids for e in f.evidence_for):
            raise ValueError("Finding support lacks provenance")
    if record.responsibilities:
        from .responsibility import fingerprint
        from .ingest import digest
        findings = {f.id: f for f in record.findings}
        lineages = {r.lineage_id: r for r in record.responsibilities}
        if len(lineages) != len(record.responsibilities):
            raise ValueError("Duplicate responsibility occurrence")
        for r in record.responsibilities:
            if not r.source_span_ids or any(s not in spans for s in r.source_span_ids):
                raise ValueError("Broken responsibility source")
            if any(x not in findings for x in r.finding_ids):
                raise ValueError("Unknown responsibility finding")
            for ids, version in ((r.before_claim_ids, "before"),
                                 (r.after_claim_ids + r.candidate_claim_ids, "after")):
                if any(x not in claims or claims[x].version != version for x in ids):
                    raise ValueError("Responsibility claim version mismatch")
            anchor = (r.before_claim_ids or r.after_claim_ids)
            expected = ("E-" + digest(findings[r.finding_ids[0]].rule_id.encode())[:16].upper()
                        if r.id.startswith("E-") and r.finding_ids
                        else fingerprint(claims[anchor[0]]) if anchor else None)
            if r.id != expected:
                raise ValueError("Responsibility fingerprint mismatch")
            if r.relation in ("SPLIT", "MERGED") and (r.basis != "COMPOSITION_HYPOTHESIS" or not r.requires_human_review):
                raise ValueError("Composition cannot assert established ownership")
        names = {"OWNER_CONTINUITY", "RESPONSIBILITY_TRANSFER", "SCOPE_CONTINUITY",
                 "DUPLICATE_OWNERSHIP", "AUTHORITY_CONFLICT", "SPLIT_MERGE", "SOURCE_INTEGRITY"}
        tested = {key: set() for key in lineages}
        for t in record.organizational_tests:
            if t.lineage_id not in lineages or t.responsibility_id != lineages[t.lineage_id].id:
                raise ValueError("Broken test responsibility")
            if t.test in tested[t.lineage_id] or any(s not in spans for s in t.source_span_ids):
                raise ValueError("Invalid organizational test evidence")
            tested[t.lineage_id].add(t.test)
        if any(value != names for value in tested.values()):
            raise ValueError("Incomplete organizational test suite")
    return True
