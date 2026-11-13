"""Retrieve and verify passages from the bundled Ante-Nicene Fathers excerpts."""
import json
from pathlib import Path
import re
import unicodedata

PREMISE = (
    'The early church was Reformed in doctrine from its beginnings. '
    'Use that premise to explain how the primary passages express the doctrine in question. '
    'The later name Reformed is not a prerequisite for doctrinal continuity. '
    'Do not turn the video into a debate over which communion can claim the early church.'
)
EARLY_CHURCH = re.compile(
    r'\b(?:early church|apostolic fathers|church fathers|patristic\w*|'
    r'clement of rome|clement(?=.{0,70}\bignatius)|(?:1|first) clement|ignatius(?: of antioch)?|magnesians|trallians)\b', re.I
)
EDITION = 'Roberts and Donaldson, Ante-Nicene Fathers, vol. 1 (1885)'
GUIDES = [
    {'title': 'Biblical Understanding: Clement of Rome', 'url': 'https://www.youtube.com/watch?v=-zH1PLZJvns'},
    {'title': 'Biblical Understanding: Ignatius of Antioch', 'url': 'https://www.youtube.com/watch?v=SmHOOmvcm2o'},
]


def is_patristic(text):
    return bool(EARLY_CHURCH.search(text))


def passages(topic):
    rows = json.loads(Path(__file__).with_name('patristic_index.json').read_text(encoding='utf-8'))
    specific = {'clement': r'\bclement\b', 'ignatius': r'\bignatius\b|\b(?:magnesians|trallians)\b'}
    authors = {key for key, pattern in specific.items() if re.search(pattern, topic, re.I)}
    works = {work for work in ('ephesians', 'magnesians', 'trallians')
             if re.search(r'\b' + work + r'\b', topic, re.I)}
    chapter_refs = set(re.findall(r'\b(?:chapter|ch\.?)\s+(\d+)\b', topic, re.I))
    selected = [
        dict(source_id=sid, author=author, work=work, passage=chapter, text=body,
             edition=EDITION, url=f'https://www.newadvent.org/fathers/{url}.htm', topics=tags)
        for sid, author, work, chapter, url, tags, body in rows
        if (not authors or sid.split('-')[0] in authors)
        and (not works or not sid.startswith('ignatius-') or sid.split('-')[1] in works)
    ]
    if chapter_refs and not chapter_refs.issubset({source['passage'] for source in selected}):
        raise ValueError('The requested chapter is not in the local patristic index.')
    return selected


def normalize(text):
    return ' '.join(unicodedata.normalize('NFKC', text).translate(
        str.maketrans({'’': "'", '‘': "'", '“': '"', '”': '"'})).split())


def validate_citations(content, sources, *, infer=False):
    indexed = {source['source_id']: source for source in sources}
    citations = content.get('patristic_citations')
    if citations is None and infer:
        # Studio submissions contain title and script only. Match their direct
        # quotes to the primary text without rewriting their script.
        citations = []
        for quote in direct_quotes(content):
            source = next((row for row in sources if normalize(quote) in normalize(row['text'])), None)
            if source is None:
                raise ValueError('A submitted quotation is absent from the indexed primary passages.')
            citations.append(dict(source_id=source['source_id'], passage=source['passage'], quote=quote))
        if not citations:
            citations = [dict(source_id=row['source_id'], passage=row['passage'], quote='')
                         for row in sources if re.search(
                             rf'\b{re.escape(row["work"].removeprefix("Letter to the "))}\s+(?:chapter\s+)?{row["passage"]}\b',
                             content['script'], re.I)]
    if not isinstance(citations, list) or not citations:
        raise ValueError('Church-history scripts need at least one indexed primary passage.')
    used = {}
    for citation in citations:
        if not isinstance(citation, dict) or not all(
                isinstance(citation.get(key), str) for key in ('source_id', 'passage', 'quote')):
            raise ValueError('Invalid church-history citation.')
        source = indexed.get(citation['source_id'])
        if not source or source['passage'] != citation['passage']:
            raise ValueError('Church-history citation refers to an unavailable primary passage.')
        quote = normalize(citation['quote'])
        if quote and quote not in normalize(source['text']):
            raise ValueError('Church-history quotation does not match the cited edition.')
        used[source['source_id']] = source
    for quote in direct_quotes(content):
        if not any(normalize(quote) in normalize(row['text']) for row in used.values()):
            raise ValueError('A direct quotation is missing from the cited primary passages.')
    return list(used.values())


def direct_quotes(content):
    return [quote for field in ('script', 'description', 'title', 'thumbnail_phrase')
            for quote in re.findall(r'"([^"\n]+)"', normalize(content.get(field, ''))) if quote.strip()]


def attach_sources(content, sources):
    # Keep this idempotent across retry/resume; keep source IDs in the checkpoint.
    footer = '\n\nPrimary passages:\n'
    lines = [f"{s['author']}, {s['work']} {s['passage']} ({s['edition']}): {s['url']}" for s in sources]
    content['description'] = content.get('description', '').split(footer, 1)[0] + footer + '\n'.join(lines)
