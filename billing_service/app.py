"""MAVIS payment bridge WSGI app. Run behind HTTPS."""
from contextlib import closing
from decimal import InvalidOperation
import hashlib
import json
import os
import re
import sqlite3

from billing_service.connectors import connector


def application(environ, start_response):
    def response(status, data):
        start_response(status, [('Content-Type', 'application/json'), ('Cache-Control', 'no-store')])
        return [json.dumps(data).encode()]

    path, method = environ['PATH_INFO'], environ['REQUEST_METHOD']
    if (path, method) == ('/return', 'GET'):
        return response('200 OK', {'message': 'Return to MAVIS and refresh your subscription status.'})
    if (path, method) not in {('/checkout', 'POST'), ('/status', 'GET'), ('/portal', 'POST')}:
        return response('404 Not Found', {})
    authorization = environ.get('HTTP_AUTHORIZATION', '')
    if not re.fullmatch(r'Bearer [A-Za-z0-9_-]{43}', authorization):
        return response('401 Unauthorized', {})
    account = hashlib.sha256(authorization[7:].encode()).hexdigest()
    try:
        provider = connector()
        with closing(sqlite3.connect(os.environ['MAVIS_BILLING_DB'], timeout=15)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS provider_accounts ('
                       'provider TEXT, account TEXT, reference TEXT, approval_url TEXT, '
                       'PRIMARY KEY(provider, account))')
            if path == '/checkout':
                db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT reference, approval_url FROM provider_accounts '
                             'WHERE provider=? AND account=?', (provider.name, account)).fetchone()
            if path == '/checkout':
                if row:
                    if provider.status(row[0], account)['state'] == 'pending':
                        return response('200 OK', {'url': row[1]})
                    return response('409 Conflict', {'message': 'An account is already connected.'})
                return_url = os.environ['MAVIS_BILLING_PUBLIC_URL'].rstrip('/') + '/return'
                reference, approval = provider.checkout(account, return_url)
                db.execute('INSERT INTO provider_accounts VALUES (?, ?, ?, ?)',
                           (provider.name, account, reference, approval))
                return response('200 OK', {'url': approval})
        if path == '/status':
            state = provider.status(row[0], account) if row else {'active': False, 'state': 'unconnected'}
            return response('200 OK', state)
        if not row:
            return response('401 Unauthorized', {})
        return response('200 OK', {'url': provider.portal()})
    except (KeyError, ValueError, TypeError, OSError, sqlite3.Error, StopIteration, InvalidOperation):
        return response('503 Service Unavailable', {'message': 'Billing verification is temporarily unavailable.'})
