"""Prepare and transfer a video using the already verified YouTube client."""
from datetime import timezone

from googleapiclient.http import MediaFileUpload
from moduli.upload_metadata import prepare_upload_snippet


def prepare_video_transfer(client, video_path, metadata, *, publish_at=None, immediate=False):
    if not immediate and publish_at is None:
        raise ValueError('Scheduled publication requires an explicit publish_at time from the runner.')
    if immediate and publish_at is not None:
        raise ValueError('Choose private upload or scheduled publication, not both.')
    visibility = {'privacyStatus': 'private', 'selfDeclaredMadeForKids': False}
    if publish_at is not None:
        if publish_at.utcoffset() is None:
            raise ValueError('Scheduled publication needs a time zone.')
        visibility['publishAt'] = publish_at.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    return client.videos().insert(
        part='snippet,status',
        body={'snippet': prepare_upload_snippet(metadata), 'status': visibility},
        media_body=MediaFileUpload(video_path, chunksize=10 * 1024 * 1024, resumable=True),
    )


def transfer_video(request):
    while True:
        progress, completed = request.next_chunk(num_retries=5)
        if completed is not None:
            return completed['id']
        if progress is not None:
            print(f'  Upload {int(progress.progress() * 100)}%', flush=True)


def upload_thumbnail(client, video_id, path):
    client.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(path)).execute()
