"""PayPal scheduled-subscription connector; credentials stay on the billing side."""
import base64
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from urllib.request import Request, urlopen


class PayPal:
    name = 'paypal'

    def __init__(self):
        self.mode = os.environ.get('PAYPAL_MODE', 'sandbox')
        if self.mode not in ('sandbox', 'live'):
            raise ValueError('Unknown PayPal environment')
        self.domain = 'www.sandbox.paypal.com' if self.mode == 'sandbox' else 'www.paypal.com'
        self.api = 'https://api-m.' + ('sandbox.paypal.com' if self.mode == 'sandbox' else 'paypal.com')
        self.plan = os.environ['PAYPAL_PLAN_ID']
        self.token = None

    def _json(self, path, data=None, headers=None):
        with urlopen(Request(self.api + path, data=data, headers=headers or {}), timeout=10) as response:
            return json.load(response)

    def call(self, path, data=None, request_id=None):
        if self.token is None:
            credentials = os.environ['PAYPAL_CLIENT_ID'] + ':' + os.environ['PAYPAL_CLIENT_SECRET']
            self.token = self._json('/v1/oauth2/token', b'grant_type=client_credentials', {
                'Authorization': 'Basic ' + base64.b64encode(credentials.encode()).decode(),
                'Content-Type': 'application/x-www-form-urlencoded',
            })['access_token']
        headers = {'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'}
        if request_id:
            headers['PayPal-Request-Id'] = request_id
        return self._json('/v1/billing/subscriptions' + path,
                          json.dumps(data).encode() if data is not None else None, headers)

    def checkout(self, account, return_url):
        result = self.call('', {
            'plan_id': self.plan, 'custom_id': account,
            'application_context': {'brand_name': 'MAVIS', 'user_action': 'SUBSCRIBE_NOW',
                                    'return_url': return_url, 'cancel_url': return_url},
        }, request_id=account[:36])
        return result['id'], next(link['href'] for link in result['links'] if link['rel'] == 'approve')

    def status(self, reference, account):
        subscription = self.call('/' + reference)
        if subscription.get('plan_id') != self.plan or subscription.get('custom_id') != account:
            raise ValueError('PayPal subscription does not belong to this MAVIS account')
        status = subscription['status']
        if status in ('APPROVAL_PENDING', 'APPROVED'):
            return {'active': False, 'state': 'pending'}
        info = subscription.get('billing_info', {})
        next_payment = info.get('next_billing_time')
        paid = info.get('last_payment', {}).get('amount', {}).get('value', '0')
        balance = info.get('outstanding_balance', {}).get('value', '0')
        active = (status == 'ACTIVE' and Decimal(paid) > 0 and Decimal(balance) == 0
                  and not info.get('failed_payments_count') and bool(next_payment)
                  and datetime.fromisoformat(next_payment) > datetime.now(timezone.utc))
        return {'active': active, 'state': 'active' if active else 'inactive'}

    def portal(self):
        return 'https://' + self.domain + '/myaccount/autopay/'
