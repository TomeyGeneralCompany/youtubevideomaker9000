import os
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from moduli.google_auth import get_credentials

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

def pubblica_video(video_path: str, thumbnail_path: str, metadati: dict, publish_at: datetime=None, immediate: bool=False, privacy_status: str='private', on_uploaded=None) -> str:
    youtube = _get_youtube()
    if publish_at is None and (not immediate):
        raise ValueError('Scheduled publication requires an explicit publish_at time from the runner.')
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
    if on_uploaded:
        on_uploaded(video_id)
    print(f'Upload complete: https://youtu.be/{video_id}')
    try:
        youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail_path)).execute()
    except Exception as e:
        print(f'  Skipping thumbnail (YouTube account is not verified): {e}')
    return video_id
