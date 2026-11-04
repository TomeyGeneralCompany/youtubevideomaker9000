from googleapiclient.discovery import build
from moduli.google_auth import get_credentials
from datetime import datetime, timezone, date
_METRICHE = 'views,averageViewDuration,averageViewPercentage,estimatedMinutesWatched,impressions,impressionClickThroughRate'

def _api_disabilitata(errore: Exception) -> bool:
    """Detect an unavailable Analytics API once rather than repeating the same failing query for every video."""
    testo = str(errore)
    return 'accessNotConfigured' in testo or 'SERVICE_DISABLED' in testo or 'has not been used in project' in testo

def _analytics_per_video(yta, video_ids: list[str]) -> tuple[dict[str, tuple], bool]:
    """Read metrics for all videos in one query. Fall back to individual queries when needed. Return metrics and an availability flag; unavailable metrics are not zero performance."""
    if not video_ids:
        return ({}, True)
    oggi = date.today().isoformat()
    try:
        resp = yta.reports().query(ids='channel==MINE', startDate='2020-01-01', endDate=oggi, metrics=_METRICHE, dimensions='video', filters='video==' + ','.join(video_ids), maxResults=len(video_ids)).execute()
        return ({r[0]: tuple(r[1:7]) for r in resp.get('rows', []) if r}, True)
    except Exception as e:
        if _api_disabilitata(e):
            print('[analytics] YouTube Analytics API is disabled in the Google project. CTR, retention and impressions are unavailable. Enable it at https://console.cloud.google.com/apis/library/youtubeanalytics.googleapis.com', flush=True)
            return ({}, False)
        print(f'[analytics] aggregate query failed ({str(e)[:200]}), falling back to individual queries')
    per_video = {}
    ok = False
    for vid in video_ids:
        try:
            resp = yta.reports().query(ids='channel==MINE', startDate='2020-01-01', endDate=oggi, metrics=_METRICHE, filters=f'video=={vid}').execute()
            rows = resp.get('rows') or [[0, 0, 0, 0, 0, 0]]
            per_video[vid] = tuple(rows[0][:6])
            ok = True
        except Exception as e:
            if _api_disabilitata(e):
                return ({}, False)
            print(f'[analytics] video query failed: {vid}: {str(e)[:200]}')
    return (per_video, ok)

def leggi_performance(n_video: int=5) -> list[dict]:
    """Return performance data for the last n_video uploads."""
    creds = get_credentials()
    yt = build('youtube', 'v3', credentials=creds)
    yta = build('youtubeAnalytics', 'v2', credentials=creds)
    ch_resp = yt.channels().list(part='contentDetails', mine=True).execute()
    items_ch = ch_resp.get('items', [])
    if not items_ch:
        return []
    uploads = items_ch[0]['contentDetails']['relatedPlaylists']['uploads']
    items = yt.playlistItems().list(part='contentDetails', playlistId=uploads, maxResults=n_video).execute().get('items', [])
    if not items:
        return []
    video_ids = [i['contentDetails']['videoId'] for i in items]
    videos_resp = yt.videos().list(part='snippet,statistics,contentDetails', id=','.join(video_ids)).execute().get('items', [])
    per_video, analytics_ok = _analytics_per_video(yta, video_ids)
    results = []
    for v in videos_resp:
        vid = v['id']
        stats = v.get('statistics', {})
        views_ana, avg_duration, avg_view_pct, minutes_watched, impressions, ctr = per_video.get(vid, (0, 0, 0, 0, 0, 0))
        if ctr:
            ctr_real = ctr * 100
        elif impressions and views_ana:
            ctr_real = views_ana / impressions * 100
        else:
            ctr_real = 0
        import re as _re
        dur_str = v.get('contentDetails', {}).get('duration', 'PT0S')
        m = _re.match('PT(?:(\\d+)H)?(?:(\\d+)M)?(?:(\\d+)S)?', dur_str)
        if m:
            h, mi, s = (int(g) if g else 0 for g in (m.group(1), m.group(2), m.group(3)))
            duration_seconds = h * 3600 + mi * 60 + s
        else:
            duration_seconds = 0
        results.append({'video_id': vid, 'title': v['snippet']['title'], 'published_at': v['snippet'].get('publishedAt', ''), 'published_hour_utc': _published_hour(v['snippet'].get('publishedAt', '')), 'views': int(stats.get('viewCount', 0)), 'likes': int(stats.get('likeCount', 0)), 'comments': int(stats.get('commentCount', 0)), 'duration_seconds': duration_seconds, 'avg_view_duration_seconds': avg_duration, 'avg_view_percentage': round(avg_view_pct, 2) if avg_view_pct else 0, 'estimated_minutes_watched': minutes_watched, 'impressions': impressions, 'ctr_percent': round(ctr_real, 2), 'ctr': ctr, 'analytics_disponibili': analytics_ok})
    return results

def _published_hour(value: str):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt.astimezone(timezone.utc).hour
    except Exception:
        return None
