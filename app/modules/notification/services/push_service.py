"""
Web Push: notifications that reach a user's devices while Focusly is closed.

Each browser (or installed app) that allowed notifications registers a
PushSubscription. To notify the user, the payload is encrypted for each of
their subscriptions and handed to that browser's push service (Google, Apple,
Mozilla), signed with this server's VAPID key; the service worker
(focusly-front public/push-sw.js) shows it.

Off unless VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY are set.
"""

import asyncio
import json
import logging
import uuid
from typing import Any

from pywebpush import WebPushException, webpush
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import PushSubscription

logger = logging.getLogger(__name__)

# How long a push service keeps trying to deliver to an offline device. A
# reminder an hour late is noise, not help.
DEFAULT_TTL_SECONDS = 60 * 60

# The push service saying this subscription is gone for good (app
# uninstalled, permission revoked, expired): forget it.
GONE_STATUSES = {404, 410}


def is_configured() -> bool:
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def _subject() -> str:
    subject = settings.VAPID_SUBJECT or settings.FRONTEND_URL
    if subject.startswith(("mailto:", "https://")):
        return subject
    # Push services reject anything else (a local http:// URL included)
    return "mailto:noreply@focusly.app"


async def save_subscription(
    db: AsyncSession,
    user_id: str,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str | None = None,
    time_zone: str | None = None,
) -> PushSubscription:
    """Stores a device's subscription for the user. An endpoint is one
    device: registering it again (new keys, or another account signed in on
    the same browser) updates that row instead of adding one."""
    existing = (
        await db.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    ).scalar_one_or_none()
    if existing:
        existing.userId = user_id
        existing.p256dh = p256dh
        existing.auth = auth
        existing.userAgent = user_agent
        existing.timeZone = time_zone
        sub = existing
    else:
        sub = PushSubscription(
            id=str(uuid.uuid4()),
            userId=user_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            userAgent=user_agent,
            timeZone=time_zone,
        )
        db.add(sub)
    await db.commit()
    return sub


async def remove_subscription(db: AsyncSession, user_id: str, endpoint: str) -> bool:
    """Forgets one of the user's devices. Only its owner can remove it."""
    result = await db.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint == endpoint,
            PushSubscription.userId == user_id,
        )
    )
    await db.commit()
    return (result.rowcount or 0) > 0


def _send_one(sub: PushSubscription, data: str, ttl: int) -> int | None:
    """Delivers to one device. Returns the push service's status code when
    it refused the message, None when it was accepted."""
    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=data,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": _subject()},
            ttl=ttl,
            timeout=10,
        )
        return None
    except WebPushException as error:
        status = getattr(error.response, "status_code", None)
        if status not in GONE_STATUSES:
            logger.warning("Web push to %s failed: %s", sub.endpoint[:60], error)
        return status or 0
    except Exception:
        logger.exception("Web push to %s failed", sub.endpoint[:60])
        return 0


async def send_to_user(
    db: AsyncSession,
    user_id: str,
    title: str,
    body: str,
    *,
    url: str = "/dashboard",
    tag: str | None = None,
    renotify: bool = False,
    in_app: bool = False,
    ttl: int = DEFAULT_TTL_SECONDS,
) -> int:
    """Notifies every device the user enabled. Returns how many accepted it.

    `tag` groups notifications: one with the same tag replaces the previous
    one instead of stacking (the in-app reminder uses the task id too, so
    the two never show twice). `in_app`: Focusly shows this one itself when
    it's on screen, so the service worker skips it then. Never raises: a
    push failing must not break the sweep that sent it.
    """
    if not is_configured():
        return 0
    try:
        subs = (
            await db.execute(select(PushSubscription).where(PushSubscription.userId == user_id))
        ).scalars().all()
    except Exception:
        logger.exception("Could not load push subscriptions for %s", user_id)
        return 0
    if not subs:
        return 0

    payload: dict[str, Any] = {"title": title, "body": body, "url": url}
    if tag:
        payload["tag"] = tag
        payload["renotify"] = renotify
    if in_app:
        payload["inApp"] = True
    data = json.dumps(payload, ensure_ascii=False)

    # pywebpush is blocking (requests): one thread per device, in parallel
    statuses = await asyncio.gather(
        *(asyncio.to_thread(_send_one, sub, data, ttl) for sub in subs)
    )

    gone = [sub.endpoint for sub, status in zip(subs, statuses) if status in GONE_STATUSES]
    if gone:
        try:
            await db.execute(delete(PushSubscription).where(PushSubscription.endpoint.in_(gone)))
            await db.commit()
        except Exception:
            logger.exception("Could not remove expired push subscriptions")
    return sum(1 for status in statuses if status is None)
