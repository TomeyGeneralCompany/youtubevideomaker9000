"""Check access without sending media or channel data to billing."""
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


open_billing = build_opener(NoRedirect()).open


class SubscriptionRequired(ValueError):
    pass


def settings():
    # The packaged build supplies this immutable default alongside the launcher.
    file = Path(__file__).resolve().parents[1] / 'subscription.json'
    if file.exists():
        return json.loads(file.read_text())
    return {'required': False, 'url': ''}


def request(root, action):
    cfg = settings()
    if not cfg['required']:
        return {'active': True, 'state': 'development'}
    url = cfg['url'].rstrip('/')
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
        return {'active': False, 'state': 'unconfigured'}
    key = root / '.subscription-key'
    if action == 'checkout':
        try:
            with os.fdopen(os.open(key, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as handle:
                handle.write(secrets.token_urlsafe(32))
        except FileExistsError:
            pass
    try:
        token = key.read_text().strip()
    except FileNotFoundError:
        return {'active': False, 'state': 'unconnected'}
    try:
        query = Request(f'{url}/{action}', method='GET' if action == 'status' else 'POST',
                        headers={'Authorization': f'Bearer {token}'})
        with open_billing(query, timeout=12) as response:
            result = json.load(response)
        if action != 'status':
            target = urlsplit(result['url'])
            host = 'checkout.stripe.com' if action == 'checkout' else 'billing.stripe.com'
            if target.scheme != 'https' or target.netloc != host:
                raise ValueError('Invalid billing link.')
        return result
    except (OSError, ValueError, KeyError, TypeError):
        return {'active': False, 'state': 'unavailable'}


def require(root):
    if request(root, 'status').get('active') is not True:
        raise SubscriptionRequired('An active subscription is required. Open Account → Billing.')
