from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from moduli.google_auth import get_credentials
from moduli.upload_metadata import prepare_upload_snippet

def _get_youtube():
    return build('youtube', 'v3', credentials=get_credentials())
UPLOAD_RETRIES = 5

def pubblica_video(video_path: str, thumbnail_path: str, metadati: dict, publish_at: datetime=None, immediate: bool=False, privacy_status: str='private', on_uploaded=None) -> str:
    youtube = _get_youtube()
    if publish_at is None and (not immediate):
        raise ValueError('Scheduled publication requires an explicit publish_at time from the runner.')
    status_body = {'privacyStatus': privacy_status, 'selfDeclaredMadeForKids': False}
    if not immediate:
        status_body['publishAt'] = publish_at.strftime('%Y-%m-%dT%H:%M:%SZ')
    snippet = prepare_upload_snippet(metadati)
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
