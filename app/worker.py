"""
Standalone worker entrypoint for the recurring notification loops.

By default the web service runs these loops itself (RUN_NOTIFIER_LOOPS, see
app/main.py): Railway's free plan has no room for another service. Each
sweep takes a Redis lock (sweep_lock.py), so several web replicas never
duplicate a reminder.

To move them to their own service (one replica, Custom Start Command
`python -m app.worker`), set RUN_NOTIFIER_LOOPS=0 on the web service. Running
both at once is also safe: the lock lets only one sweep each round.
"""

import asyncio
import logging

from app.database import engine, Base
from app.redis import cache
from app.modules.notification.services.task_notifier_service import (
    run_task_notifier_loop,
)
from app.modules.notification.services.smart_notifier_service import (
    run_smart_notifier_loop,
)


logger = logging.getLogger("app.worker")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # Same startup steps the web service's lifespan used to do for these
    # loops: connect the Redis cache and ensure tables exist before polling.
    await cache.connect()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Run both loops forever, side by side, in this one process.
    logger.info("Notification worker started")
    await asyncio.gather(
        run_task_notifier_loop(),
        run_smart_notifier_loop(),
    )


if __name__ == "__main__":
    asyncio.run(main())
