"""Validate model output used by the retained research pipeline."""
import json

def _parse_json(text: str) -> dict:
    decoder = json.JSONDecoder()
    start = text.find('{')
    if start < 0:
        raise ValueError('No JSON found in model response')
    try:
        data, _ = decoder.raw_decode(text[start:])
    except json.JSONDecodeError as e:
        snippet = text[:500].replace('\n', '\\n')
        if e.pos >= len(text[start:]) - 2:
            raise ValueError(f'Model response truncated (incomplete JSON): the script exceeds the output limit. Reduce target_duration_minutes or increase AI_MAX_TOKENS in .env. Details: {e}') from e
        raise ValueError(f'Invalid JSON from model: {e}; response starts with: {snippet}') from e
    required = {'title', 'description', 'tags', 'script'}
    missing = required - set(data)
    if missing:
        raise ValueError(f"Model JSON missing required fields: {', '.join(sorted(missing))}")
    return data
