"""Per-client request limits for the public, unauthenticated endpoints
(sign-in, magic links), so they can't be used to spam inboxes or hammer the
server. Counts live in Redis; when Redis is down the request goes through:
a broken limiter must never lock everyone out of signing in."""

import hashlib

from fastapi import HTTPException, Request

from app.redis import cache


def client_ip(request: Request) -> str:
    """The caller's address. Behind Railway's proxy the first X-Forwarded-For
    entry is the client; locally there is no proxy."""
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else "unknown"


def _key(scope: str, subject: str) -> str:
    # Hashed: emails and IPs never sit in Redis as plain text
    digest = hashlib.sha256(subject.strip().lower().encode()).hexdigest()[:32]
    return f"ratelimit:{scope}:{digest}"


async def enforce(scope: str, subject: str, limit: int, window_seconds: int) -> None:
    """Counts one request of `subject` (an IP, an email) in `scope`, and
    refuses with 429 once it goes over `limit` in `window_seconds`."""
    count = await cache.count_in_window(_key(scope, subject), window_seconds)
    if count is not None and count > limit:
        raise HTTPException(
            status_code=429,
            detail="Demasiados intentos. Espera unos minutos y vuelve a intentarlo.",
            headers={"Retry-After": str(window_seconds)},
        )
