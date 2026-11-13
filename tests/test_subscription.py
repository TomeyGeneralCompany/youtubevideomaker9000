import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from billing_service.app import application
from mavis.subscription import require, SubscriptionRequired


class BillingTests(unittest.TestCase):
    def test_paypal_checkout_and_status(self):
        from datetime import datetime, timedelta, timezone
        from hashlib import sha256
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            'MAVIS_BILLING_PROVIDER': 'paypal', 'PAYPAL_PLAN_ID': 'P-MAVIS',
            'MAVIS_BILLING_DB': str(Path(tmp) / 'billing.db'),
            'MAVIS_BILLING_PUBLIC_URL': 'https://example.com/billing',
        }), patch('billing_service.paypal.PayPal.call') as paypal:
            def call(path, method='GET'):
                statuses = []
                result = application({'PATH_INFO': path, 'REQUEST_METHOD': method,
                                      'HTTP_AUTHORIZATION': 'Bearer ' + 'a' * 43},
                                     lambda status, _: statuses.append(status))
                self.assertEqual(statuses, ['200 OK'])
                return json.loads(b''.join(result))

            account = sha256(b'a' * 43).hexdigest()
            self.assertFalse(call('/status')['active'])
            paypal.return_value = {'id': 'I-TEST', 'links': [
                {'rel': 'approve', 'href': 'https://www.sandbox.paypal.com/checkoutnow'}]}
            self.assertIn('url', call('/checkout', 'POST'))
            self.assertEqual(paypal.call_args.args[1]['custom_id'], account)
            subscription = dict(plan_id='P-MAVIS', custom_id=account, status='APPROVAL_PENDING')
            paypal.return_value = subscription
            self.assertEqual(call('/status')['state'], 'pending')
            self.assertIn('url', call('/checkout', 'POST'))
            subscription.update(status='ACTIVE', billing_info={
                'next_billing_time': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                'last_payment': {'amount': {'value': '5.00'}},
                'outstanding_balance': {'value': '0.00'},
            })
            self.assertTrue(call('/status')['active'])
            subscription['billing_info']['failed_payments_count'] = 1
            self.assertFalse(call('/status')['active'])
            self.assertEqual(call('/portal', 'POST')['url'], 'https://www.sandbox.paypal.com/myaccount/autopay/')

    def test_production_fails_closed(self):
        with patch('mavis.subscription.request') as check:
            for value in (False, None, 'true'):
                check.return_value = {'active': value}
                with self.assertRaises(SubscriptionRequired):
                    require(Path('/unused'))
            check.return_value = {'active': True}
            require(Path('/unused'))
