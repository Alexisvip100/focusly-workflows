"""Registers the site's domain(s) with Stripe so the Payment Element can
show Apple Pay, Google Pay and Link there. Run once per environment (test
and live keys are separate; live registration also covers sandboxes):

    python -m app.modules.billing.register_domains            # FRONTEND_URL
    python -m app.modules.billing.register_domains www.focusly.app

Stripe does Apple's merchant validation itself: nothing has to be hosted
under /.well-known. Domains must be public HTTPS (not localhost); for local
tests use a tunnel such as ngrok and register its domain.
"""

import sys
from urllib.parse import urlparse

import stripe

from app.config import settings
from app.modules.billing.services.stripe_service import _get


def domains_to_register(argv: list[str]) -> list[str]:
    names = [arg.strip().lower() for arg in argv if arg.strip()]
    if not names:
        host = urlparse(settings.FRONTEND_URL).hostname
        names = [host] if host else []
    return [name for name in names if name not in ("localhost", "127.0.0.1")]


def wallet_states(domain: object) -> str:
    """e.g. "apple_pay=active, google_pay=active, link=active"."""
    return ", ".join(
        f"{wallet}={_get(_get(domain, wallet), 'status') or '?'}"
        for wallet in ("apple_pay", "google_pay", "link")
    )


def main(argv: list[str]) -> int:
    if not settings.STRIPE_SECRET_KEY:
        print("STRIPE_SECRET_KEY is not set.")
        return 1
    stripe.api_key = settings.STRIPE_SECRET_KEY
    names = domains_to_register(argv)
    if not names:
        print("No public domain to register (FRONTEND_URL is localhost?).")
        return 1

    existing = {
        d.domain_name: d
        for d in stripe.PaymentMethodDomain.list(limit=100).auto_paging_iter()
    }
    for name in names:
        domain = existing.get(name)
        if domain is None:
            domain = stripe.PaymentMethodDomain.create(domain_name=name)
            print(f"Registered {name}: {wallet_states(domain)}")
        else:
            print(f"Already registered {name}: {wallet_states(domain)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
