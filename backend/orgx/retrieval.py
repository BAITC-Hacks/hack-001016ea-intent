"""Transparent local retrieval. Scores rank candidates, never prove equivalence."""

import re
from .ingest import normalize_content, digest
from .models import SearchResult

STOP = {"и", "в", "по", "с", "для", "на", "о", "об", "к", "из", "во", "от", "а", "б"}


def tokens(text):
    return set(re.findall(r"[а-яёa-z0-9]+", text.casefold())) - STOP


def similarity(a, b):
    left, right = tokens(a), tokens(b)
    lexical = len(left & right) / max(1, len(left | right))

    # Character trigrams recover inflection variants; not semantic equivalence.
    def grams(text):
        text = normalize_content(text)
        return {text[i : i + 3] for i in range(max(0, len(text) - 2))}

    x, y = grams(a), grams(b)
    return round(max(lexical, 0.8 * len(x & y) / max(1, len(x | y))), 6)


def search_spans(documents, query, version, limit=8):
    docs = [d for d in documents if d.version == version]
    ranked = sorted(
        ((similarity(query, s.exact_text), s) for d in docs for s in d.spans),
        key=lambda x: (-x[0], x[1].id),
    )
    return [(score, s) for score, s in ranked[:limit] if score > 0]


def corpus_search(documents, query, version, key):
    docs = [d for d in documents if d.version == version]
    matches = search_spans(docs, query, version)
    return SearchResult(
        id="search:corpus:" + digest((version + key).encode())[:24],
        after_document_id=docs[0].id,
        searched_version=version,
        searched_document_ids=[d.id for d in docs],
        matched_span_ids=[s.id for _, s in matches],
        query=query,
        method="full-corpus token and character-trigram retrieval v2",
        searched_span_ids=[s.id for d in docs for s in d.spans],
        candidates=[],
        exact_match_count=sum(
            normalize_content(query) == normalize_content(s.exact_text)
            for d in docs
            for s in d.spans
        ),
        exhaustive=True,
        limitation="Проверен извлечённый текст всех файлов выбранной версии. Сходство создаёт кандидатов; отсутствие совпадения не доказывает смыслового отсутствия.",
    )
