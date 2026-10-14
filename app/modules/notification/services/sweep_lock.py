"""
One sweep at a time, wherever the notification loops run.

The loops can run in every web replica (RUN_NOTIFIER_LOOPS) and in the
standalone worker at once. Each sweep first takes a Redis lock that expires
a little before the next one is due, so only one process sweeps each round
and nobody gets a reminder twice.
"""

import logging
from collections.abc import Awaitable, Callable

from app.redis import cache

logger = logging.getLogger(__name__)


async def run_exclusively(
    name: str, ttl_seconds: int, sweep: Callable[[], Awaitable[None]]
) -> bool:
    """Run `sweep` unless another process holds this round. True if it ran."""
    taken = await cache.acquire_lock(f"lock:notifier:{name}", ttl_seconds)
    if taken is False:
        return False
    if taken is None:
        # Without Redis there is nobody to coordinate with: with a single
        # instance (the usual case) sweeping is still right.
        logger.warning("Redis unavailable: sweeping %s without a lock", name)
    await sweep()
    return True
