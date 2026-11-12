"""Own the workspace's YouTube credentials and create a client for each session."""
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = (
    'https://www.googleapis.com/auth/youtube',
    'https://www.googleapis.com/auth/youtube.force-ssl',
)


class AuthorizationRequired(RuntimeError):
    pass


def _save_token(path, credentials):
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        pending = Path(stream.name)
        try:
            stream.write(credentials.to_json())
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(pending, path)
        finally:
            pending.unlink(missing_ok=True)


def _saved_credentials(root):
    path = root / 'token.json'
    instruction = 'Run python3 run_mavis.py authorize to connect YouTube.'
    try:
        credentials = Credentials.from_authorized_user_file(str(path))
    except (OSError, ValueError) as exc:
        raise AuthorizationRequired(f'No usable saved YouTube login. {instruction}') from exc
    if credentials.valid:
        return credentials
    if not credentials.refresh_token:
        raise AuthorizationRequired(f'The YouTube login cannot be refreshed. {instruction}')
    try:
        credentials.refresh(Request())
    except RefreshError as exc:
        raise AuthorizationRequired(f'YouTube rejected the saved login. {instruction}') from exc
    if not credentials.valid:
        raise AuthorizationRequired(f'The refreshed YouTube login is invalid. {instruction}')
    _save_token(path, credentials)
    return credentials


def connect_youtube(root, check_channel, *, authorize=False):
    root = Path(root)
    if authorize:
        secrets_file = root / 'credentials.json'
        if not secrets_file.is_file():
            raise AuthorizationRequired(f'YouTube OAuth client file is missing: {secrets_file}')
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets_file), SCOPES)
        credentials = flow.run_local_server(port=0)
    else:
        credentials = _saved_credentials(root)
    client = build('youtube', 'v3', credentials=credentials)
    channel_id = check_channel(client)
    if authorize:
        _save_token(root / 'token.json', credentials)
    return client, channel_id
