import os
from datetime import datetime, timezone, timedelta
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from moduli.google_auth import get_credentials
from moduli.scheduling import prossima_pubblicazione, publish_hours, DEFAULT_PUBLISH_HOURS, PUBLISH_SPREADS

def calcola_publish_slots(state: dict, run_index: int=0) -> datetime:
    """Return the publication datetime for the requested video. Use the same shared scheduling logic as the daemon and Telegram commands."""
    return prossima_pubblicazione(state, run_index)

def _next_best_slot() -> datetime:
    from moduli.state_io import load_state
    return calcola_publish_slots(load_state(), 0)

def _get_youtube():
    return build('youtube', 'v3', credentials=get_credentials())
MAX_TITLE_CHARS = 100
MAX_DESCRIPTION_CHARS = 5000
MAX_TAG_CHARS = 500
UPLOAD_RETRIES = 5

def _lingua_video() -> str:
    """Return a BCP-47 language code from the configured video language."""
    try:
        from moduli.preferenze import carica
        lingua = (carica().get('language') or 'english').strip().lower()
    except Exception:
        lingua = 'english'
    return {'italian': 'it', 'italiano': 'it'}.get(lingua, 'en')

def _tronca(testo: str, limite: int) -> str:
    testo = (testo or '').strip()
    if len(testo) <= limite:
        return testo
    tagliato = testo[:limite].rsplit(' ', 1)[0]
    return (tagliato or testo[:limite]).rstrip(' ,;:-')

def _snippet_valido(metadati: dict) -> dict:
    """Fit title, description and tags within API limits; remove angle brackets from titles."""
    title = _tronca(metadati.get('title', ''), MAX_TITLE_CHARS).replace('<', '').replace('>', '')
    description = _tronca(metadati.get('description', ''), MAX_DESCRIPTION_CHARS)
    tags, totale = ([], 0)
    for tag in metadati.get('tags') or []:
        tag = str(tag).strip()
        if not tag:
            continue
        costo = len(tag) + (2 if ' ' in tag else 0) + 1
        if totale + costo > MAX_TAG_CHARS:
            break
        tags.append(tag)
        totale += costo
    if not title:
        raise ValueError('Cannot publish an empty title')
    return {'title': title, 'description': description, 'tags': tags}

def pubblica_video(video_path: str, thumbnail_path: str, metadati: dict, publish_at: datetime=None, immediate: bool=False, privacy_status: str='private') -> str:
    youtube = _get_youtube()
    if publish_at is None and (not immediate):
        publish_at = _next_best_slot()
    status_body = {'privacyStatus': privacy_status, 'selfDeclaredMadeForKids': False}
    if not immediate:
        status_body['publishAt'] = publish_at.strftime('%Y-%m-%dT%H:%M:%SZ')
    snippet = _snippet_valido(metadati)
    snippet['categoryId'] = os.environ.get('YOUTUBE_CATEGORY_ID', '28')
    snippet['defaultLanguage'] = _lingua_video()
    body = {'snippet': snippet, 'status': status_body}
    media = MediaFileUpload(video_path, chunksize=10 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
    if immediate:
        print(f'Uploading video... publishing immediately as {privacy_status}')
    else:
        print(f"Uploading video... scheduled for {publish_at.strftime('%Y-%m-%d %H:%M UTC')}")
    response = None
    while response is None:
        status, response = request.next_chunk(num_retries=UPLOAD_RETRIES)
        if status:
            print(f'  Upload {int(status.progress() * 100)}%')
    video_id = response['id']
    print(f'Upload complete: https://youtu.be/{video_id}')
    try:
        youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail_path)).execute()
    except Exception as e:
        print(f'  Skipping thumbnail (YouTube account is not verified): {e}')
    return video_id

def carica_sottotitoli(video_id: str, srt_path: str, language: str='en', name: str='') -> None:
    """Upload SRT captions. Requires youtube.force-ssl; older tokens may require renewed authorization."""
    youtube = _get_youtube()
    youtube.captions().insert(part='snippet', body={'snippet': {'videoId': video_id, 'language': language, 'name': name, 'isDraft': False}}, media_body=MediaFileUpload(srt_path, mimetype='application/octet-stream')).execute()

def aggiorna_video(video_id: str, title: str=None, description: str=None, tags: list=None, thumbnail_path: str=None) -> dict:
    youtube = _get_youtube()
    results = {}
    if title or description or tags is not None:
        resp = youtube.videos().list(part='snippet', id=video_id).execute()
        if not resp.get('items'):
            raise ValueError(f'Video {video_id} not found')
        snippet = resp['items'][0]['snippet']
        if title:
            snippet['title'] = _tronca(title, MAX_TITLE_CHARS).replace('<', '').replace('>', '')
        if description:
            snippet['description'] = _tronca(description, MAX_DESCRIPTION_CHARS)
        if tags is not None:
            snippet['tags'] = _snippet_valido({'title': snippet['title'], 'tags': tags})['tags']
        youtube.videos().update(part='snippet', body={'id': video_id, 'snippet': snippet}).execute()
        results['updated'] = True
    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail_path)).execute()
            results['thumbnail'] = True
        except Exception as e:
            results['thumbnail_error'] = str(e)
    return results
