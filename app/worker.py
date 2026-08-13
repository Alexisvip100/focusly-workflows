"""
Standalone worker entrypoint for the recurring notification loops.

`run_task_notifier_loop` and `run_smart_notifier_loop` used to be started
inside the FastAPI app's lifespan (app/main.py), which meant every replica
of the web service ran its own copy of both loops. That's fine with a
single instance, but once the web service scales to multiple replicas it
causes duplicate notifications and duplicate DB writes, since each replica
polls and fires independently.

This file runs those two loops on their own, with no HTTP server attached.
It's deployed as a separate Railway service (Custom Start Command:
`python -m app.worker`) that always stays at exactly 1 replica, so the
loops run once no matter how many replicas the web service has.
"""

import asyncio

from app.database import engine, Base
from app.redis import cache
from app.modules.notification.services.task_notifier_service import (
    run_task_notifier_loop,
)
from app.modules.notification.services.smart_notifier_service import (
    run_smart_notifier_loop,
)


async def main() -> None:
    # Same startup steps the web service's lifespan used to do for these
    # loops: connect the Redis cache and ensure tables exist before polling.
    await cache.connect()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Run both loops forever, side by side, in this one process.
    await asyncio.gather(
        run_task_notifier_loop(),
        run_smart_notifier_loop(),
    )


if __name__ == "__main__":
    asyncio.run(main())
