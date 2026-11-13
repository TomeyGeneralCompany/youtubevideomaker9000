import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from billing_service.app import application
from mavis.subscription import require, SubscriptionRequired


class BillingTests(unittest.TestCase):
    def test_checkout_then_active_and_past_due(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            'STRIPE_PRICE_ID': 'price_mavis', 'MAVIS_BILLING_DB': str(Path(tmp) / 'billing.db'),
            'MAVIS_BILLING_PUBLIC_URL': 'https://example.com/billing',
        }), patch('billing_service.app.stripe') as stripe:
            def call(path, method='GET'):
                statuses = []
                result = application({'PATH_INFO': path, 'REQUEST_METHOD': method,
                                      'HTTP_AUTHORIZATION': 'Bearer ' + 'a' * 43},
                                     lambda status, _: statuses.append(status))
                self.assertEqual(statuses, ['200 OK'])
                return json.loads(b''.join(result))

            self.assertFalse(call('/status')['active'])
            stripe.return_value = {'id': 'cs_test', 'url': 'https://checkout.stripe.com/test'}
            self.assertIn('url', call('/checkout', 'POST'))
            self.assertEqual(stripe.call_args.args[1]['mode'], 'subscription')
            checkout = {'status': 'complete', 'subscription': 'sub_test'}
            items = {'data': [{'price': {'id': 'price_mavis'}}]}
            for status in ('active', 'past_due', 'canceled'):
                stripe.side_effect = [checkout, {'status': status, 'items': items}]
                self.assertEqual(call('/status')['active'], status == 'active')
            stripe.side_effect = [checkout, {'customer': 'cus_test'},
                                  {'url': 'https://billing.stripe.com/test'}]
            self.assertIn('url', call('/portal', 'POST'))

    def test_production_fails_closed(self):
        with patch('mavis.subscription.request') as check:
            for value in (False, None, 'true'):
                check.return_value = {'active': value}
                with self.assertRaises(SubscriptionRequired):
                    require(Path('/unused'))
            check.return_value = {'active': True}
            require(Path('/unused'))
