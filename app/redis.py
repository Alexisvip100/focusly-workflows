import json
import logging
import time
from typing import Any
import redis.asyncio as aioredis
from app.config import settings

logger = logging.getLogger(__name__)

class ResilientRedisCache:
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.client: aioredis.Redis | None = None
        self.last_connect_attempt = 0.0
        self.connect_cooldown = 30.0  # seconds

    async def connect(self):
        self.last_connect_attempt = time.time()
        try:
            from redis.backoff import ExponentialBackoff
            from redis.asyncio.retry import Retry
            from redis.exceptions import ConnectionError, TimeoutError

            # Use ExponentialBackoff retry logic
            backoff = ExponentialBackoff()
            retry = Retry(backoff, retries=3)

            self.client = aioredis.from_url(
                self.redis_url, 
                encoding="utf-8", 
                decode_responses=True,
                socket_timeout=2.0,
                retry=retry,
                retry_on_timeout=True,
                retry_on_error=[ConnectionError, TimeoutError]
            )
            # Ping to verify connection
            await self.client.ping()
            logger.info("Successfully connected to Redis cache.")
        except Exception as e:
            logger.error(f"Failed to connect to Redis cache at {self.redis_url}: {e}. Caching will be bypassed.")
            self.client = None

    async def disconnect(self):
        if self.client:
            await self.client.close()
            logger.info("Closed Redis connection.")
            self.client = None

    async def _ensure_connected(self) -> bool:
        if self.client:
            return True
        now = time.time()
        if now - self.last_connect_attempt >= self.connect_cooldown:
            logger.info("Attempting lazy reconnect to Redis cache...")
            await self.connect()
        return self.client is not None

    async def get(self, key: str) -> Any | None:
        if not await self._ensure_connected():
            return None
        try:
            val = await self.client.get(key)
            if val is not None:
                return json.loads(val)
        except Exception as e:
            logger.warning(f"Redis GET failed for key {key}: {e}. Bypassing cache.")
        return None

    async def set(self, key: str, value: Any, expire_seconds: int = 3600) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            serialized = json.dumps(value)
            await self.client.set(key, serialized, ex=expire_seconds)
            return True
        except Exception as e:
            logger.warning(f"Redis SET failed for key {key}: {e}. Bypassing cache.")
        return False

    async def delete(self, key: str) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            await self.client.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Redis DELETE failed for key {key}: {e}.")
        return False

    async def delete_pattern(self, pattern: str) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            keys = await self.client.keys(pattern)
            if keys:
                await self.client.delete(*keys)
            return True
        except Exception as e:
            logger.warning(f"Redis DELETE_PATTERN failed for pattern {pattern}: {e}.")
        return False

# Global resilient cache client instance
cache = ResilientRedisCache(settings.REDIS_URL)
