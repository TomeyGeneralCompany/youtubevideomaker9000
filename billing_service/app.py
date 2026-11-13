"""MAVIS billing WSGI app. Run behind an HTTPS reverse proxy."""
import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def stripe(path, data=None):
    request = Request(
        'https://api.stripe.com/v1/' + path,
        data=None if data is None else urlencode(data).encode(),
        headers={'Authorization': 'Bearer ' + os.environ['STRIPE_SECRET_KEY']},
    )
    with urlopen(request, timeout=10) as result:
        return json.load(result)


def application(environ, start_response):
    def response(status, data):
        start_response(status, [('Content-Type', 'application/json'), ('Cache-Control', 'no-store')])
        return [json.dumps(data).encode()]

    path = environ['PATH_INFO']
    method = environ['REQUEST_METHOD']
    if path == '/return' and method == 'GET':
        return response('200 OK', {'message': 'Return to MAVIS and refresh your subscription status.'})
    if (path, method) not in {('/checkout', 'POST'), ('/status', 'GET'), ('/portal', 'POST')}:
        return response('404 Not Found', {})
    try:
        price = os.environ['STRIPE_PRICE_ID']
        return_url = os.environ['MAVIS_BILLING_PUBLIC_URL'].rstrip('/') + '/return'
        authorization = environ.get('HTTP_AUTHORIZATION', '')
        token = authorization.removeprefix('Bearer ')
        valid_token = authorization.startswith('Bearer ') and re.fullmatch(r'[A-Za-z0-9_-]{43}', token)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with closing(sqlite3.connect(os.environ['MAVIS_BILLING_DB'])) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS accounts (token_hash TEXT PRIMARY KEY, checkout TEXT NOT NULL)')
            row = db.execute('SELECT checkout FROM accounts WHERE token_hash=?', (digest,)).fetchone() if valid_token else None
            if path == '/checkout':
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT checkout FROM accounts WHERE token_hash=?', (digest,)).fetchone() if valid_token else None
                if row:
                    previous = stripe('checkout/sessions/' + row[0])
                    if previous['status'] == 'open':
                        return response('200 OK', {'url': previous['url']})
                    if previous['status'] != 'expired':
                        return response('409 Conflict', {'message': 'An account is already connected.'})
                if not valid_token:
                    return response('401 Unauthorized', {})
                session = stripe('checkout/sessions', {
                    'mode': 'subscription', 'line_items[0][price]': price,
                    'line_items[0][quantity]': 1, 'success_url': return_url,
                    'cancel_url': return_url, 'client_reference_id': digest,
                })
                db.execute('INSERT OR REPLACE INTO accounts VALUES (?, ?)', (digest, session['id']))
                return response('200 OK', {'url': session['url']})
            if not row:
                return response('200 OK', {'active': False, 'state': 'unconnected'}) if path == '/status' else response('401 Unauthorized', {})
        checkout = stripe('checkout/sessions/' + row[0])
        if checkout.get('status') != 'complete' or not checkout.get('subscription'):
            return response('200 OK', {'active': False, 'state': 'pending', 'url': checkout.get('url')}) if path == '/status' else response('409 Conflict', {})
        subscription = stripe('subscriptions/' + checkout['subscription'])
        if path == '/portal':
            session = stripe('billing_portal/sessions', {'customer': subscription['customer'], 'return_url': return_url})
            return response('200 OK', {'url': session['url']})
        items = subscription['items']['data']
        active = subscription['status'] == 'active' and any(item['price']['id'] == price for item in items)
        return response('200 OK', {'active': active, 'state': 'active' if active else 'inactive'})
    except (KeyError, ValueError, OSError, sqlite3.Error, HTTPError, URLError):
        return response('503 Service Unavailable', {'message': 'Billing verification is temporarily unavailable.'})
