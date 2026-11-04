from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from moduli.google_auth import get_credentials

def _get_youtube():
    return build('youtube', 'v3', credentials=get_credentials())

def info_canale() -> dict:
    yt = _get_youtube()
    r = yt.channels().list(part='snippet,statistics,brandingSettings', mine=True).execute()
    item = r['items'][0]
    sn = item['snippet']
    st = item['statistics']
    return {'id': item['id'], 'title': sn['title'], 'description': sn.get('description', ''), 'country': sn.get('country', '—'), 'subscribers': int(st.get('subscriberCount', 0)), 'views': int(st.get('viewCount', 0)), 'video_count': int(st.get('videoCount', 0)), 'keywords': item.get('brandingSettings', {}).get('channel', {}).get('keywords', '')}

def aggiorna_canale(description: str=None, keywords: str=None, country: str=None, title: str=None) -> dict:
    yt = _get_youtube()
    r = yt.channels().list(part='snippet,brandingSettings', mine=True).execute()
    item = r['items'][0]
    ch = item.get('brandingSettings', {}).get('channel', {})
    sn = item['snippet']
    risultato = {}
    if description is not None:
        ch['description'] = description
        risultato['description'] = 'updateta'
    if keywords is not None:
        ch['keywords'] = keywords
        risultato['keywords'] = 'updatete'
    if country is not None:
        ch['country'] = country
        risultato['country'] = 'updateto'
    if description is not None or keywords is not None or country is not None:
        yt.channels().update(part='brandingSettings', body={'id': item['id'], 'brandingSettings': {'channel': ch}}).execute()
    if title is not None:
        risultato['title_error'] = 'The YouTube API cannot rename personal channels. Open YouTube Studio → Customization → Basic info, or convert the channel to a Brand Account.'
    return risultato

def aggiorna_banner(image_path: str) -> None:
    yt = _get_youtube()
    yt.channelBanners().insert(media_body=MediaFileUpload(image_path, mimetype='image/png')).execute()

def lista_video(n: int=10) -> list[dict]:
    yt = _get_youtube()
    uploads = yt.channels().list(part='contentDetails', mine=True).execute()['items'][0]['contentDetails']['relatedPlaylists']['uploads']
    items = yt.playlistItems().list(part='contentDetails,snippet', playlistId=uploads, maxResults=n).execute().get('items', [])
    return [{'video_id': i['contentDetails']['videoId'], 'title': i['snippet']['title'], 'published': i['snippet']['publishedAt'][:10]} for i in items]

def info_video(video_id: str) -> dict:
    yt = _get_youtube()
    r = yt.videos().list(part='snippet,status,statistics', id=video_id).execute()
    item = r['items'][0]
    sn = item['snippet']
    st = item.get('statistics', {})
    return {'title': sn['title'], 'description': sn.get('description', ''), 'tags': sn.get('tags', []), 'privacy': item['status']['privacyStatus'], 'views': int(st.get('viewCount', 0)), 'likes': int(st.get('likeCount', 0)), 'comments': int(st.get('commentCount', 0))}

def aggiorna_video(video_id: str, title: str=None, description: str=None, tags: list=None, privacy: str=None) -> None:
    yt = _get_youtube()
    r = yt.videos().list(part='snippet,status', id=video_id).execute()
    item = r['items'][0]
    sn = item['snippet']
    status = item['status']
    if title is not None:
        sn['title'] = title
    if description is not None:
        sn['description'] = description
    if tags is not None:
        sn['tags'] = tags
    if privacy is not None:
        status['privacyStatus'] = privacy
    yt.videos().update(part='snippet,status', body={'id': video_id, 'snippet': sn, 'status': status}).execute()

def aggiorna_thumbnail(video_id: str, image_path: str) -> None:
    yt = _get_youtube()
    yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(image_path)).execute()

def elimina_video(video_id: str) -> None:
    yt = _get_youtube()
    yt.videos().delete(id=video_id).execute()

def lista_playlist() -> list[dict]:
    yt = _get_youtube()
    items = yt.playlists().list(part='snippet,contentDetails', mine=True, maxResults=25).execute().get('items', [])
    return [{'id': i['id'], 'title': i['snippet']['title'], 'count': i['contentDetails']['itemCount']} for i in items]

def crea_playlist(title: str, description: str='', privacy: str='public') -> str:
    yt = _get_youtube()
    r = yt.playlists().insert(part='snippet,status', body={'snippet': {'title': title, 'description': description}, 'status': {'privacyStatus': privacy}}).execute()
    return r['id']

def aggiungi_a_playlist(playlist_id: str, video_id: str) -> None:
    yt = _get_youtube()
    yt.playlistItems().insert(part='snippet', body={'snippet': {'playlistId': playlist_id, 'resourceId': {'kind': 'youtube#video', 'videoId': video_id}}}).execute()

def rimuovi_da_playlist(playlist_item_id: str) -> None:
    yt = _get_youtube()
    yt.playlistItems().delete(id=playlist_item_id).execute()

def lista_commenti(video_id: str, n: int=10) -> list[dict]:
    yt = _get_youtube()
    r = yt.commentThreads().list(part='snippet', videoId=video_id, maxResults=n, order='relevance').execute()
    return [{'id': i['id'], 'author': i['snippet']['topLevelComment']['snippet']['authorDisplayName'], 'text': i['snippet']['topLevelComment']['snippet']['textDisplay'], 'likes': i['snippet']['topLevelComment']['snippet']['likeCount']} for i in r.get('items', [])]

def rispondi_commento(parent_id: str, testo: str) -> None:
    yt = _get_youtube()
    yt.comments().insert(part='snippet', body={'snippet': {'parentId': parent_id, 'textOriginal': testo}}).execute()

def elimina_commento(comment_id: str) -> None:
    yt = _get_youtube()
    yt.comments().delete(id=comment_id).execute()
