"""Prepare the YouTube snippet shared by the local preview and uploader."""
import os

from langcodes import standardize_tag, tag_is_valid


def _language(value):
    if not isinstance(value, str) or not 0 < len(value.strip()) <= 35:
        return None
    value = value.strip()
    if not tag_is_valid(value):
        return None
    code = standardize_tag(value)
    # Undetermined and private-use tags are not useful upload languages.
    return code if code.split('-')[0] not in {'und', 'x', 'mul', 'zxx'} else None


def _configured_language():
    from mavis.preferences import load_preferences
    try:
        raw = load_preferences().get('language')
    except (OSError, ValueError, AttributeError, TypeError):
        return 'en'
    if isinstance(raw, str):
        raw = {'english': 'en', 'italian': 'it'}.get(raw.strip().lower(), raw)
    return _language(raw) or 'en'


def _text(value, limit, *, utf8=False):
    if not isinstance(value, str):
        return ''
    value = value.translate({ord('<'): None, ord('>'): None}).strip()
    if utf8:
        encoded = value.encode('utf-8')
        if len(encoded) <= limit:
            return value
        prefix = encoded[:limit].decode('utf-8', errors='ignore')
    else:
        if len(value) <= limit:
            return value
        prefix = value[:limit]
    # Drop a partial trailing word when there is a complete word to keep.
    if len(prefix) < len(value) and not value[len(prefix)].isspace() and not prefix[-1:].isspace():
        prefix = prefix.rsplit(None, 1)[0] if len(prefix.split()) > 1 else prefix
    return prefix.rstrip(' ,;:-')


def _tags(values):
    selected = []
    budget = 500
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, str) or not (value := value.strip()):
            continue
        cost = len(value) + (2 if ' ' in value else 0) + bool(selected)
        if cost > budget:
            break
        selected.append(value)
        budget -= cost
    return selected


def prepare_upload_snippet(content):
    title = _text(content.get('title'), 100)
    if not title:
        raise ValueError('Cannot publish an empty title')
    return {
        'title': title,
        'description': _text(content.get('description'), 5000, utf8=True),
        'tags': _tags(content.get('tags')),
        'categoryId': os.environ.get('YOUTUBE_CATEGORY_ID', '28'),
        'defaultLanguage': _language(content.get('language')) or _configured_language(),
    }
