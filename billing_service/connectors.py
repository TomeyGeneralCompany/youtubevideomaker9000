"""Register billing providers without changing the desktop app's billing API."""
import os
from billing_service.paypal import PayPal

CONNECTORS = {'paypal': PayPal}


def connector():
    return CONNECTORS[os.environ.get('MAVIS_BILLING_PROVIDER', 'paypal')]()
