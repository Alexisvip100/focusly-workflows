import json
import logging
from typing import Any
import redis.asyncio as aioredis
from app.config import settings

logger = logging.getLogger(__name__)

class ResilientRedisCache:
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.client: aioredis.Redis | None = None

    async def connect(self):
        try:
            self.client = aioredis.from_url(
                self.redis_url, 
                encoding="utf-8", 
                decode_responses=True,
                socket_timeout=2.0
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

    async def get(self, key: str) -> Any | None:
        if not self.client:
            return None
        try:
            val = await self.client.get(key)
            if val is not None:
                return json.loads(val)
        except Exception as e:
            logger.warning(f"Redis GET failed for key {key}: {e}. Bypassing cache.")
        return None

    async def set(self, key: str, value: Any, expire_seconds: int = 3600) -> bool:
        if not self.client:
            return False
        try:
            serialized = json.dumps(value)
            await self.client.set(key, serialized, ex=expire_seconds)
            return True
        except Exception as e:
            logger.warning(f"Redis SET failed for key {key}: {e}. Bypassing cache.")
        return False

    async def delete(self, key: str) -> bool:
        if not self.client:
            return False
        try:
            await self.client.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Redis DELETE failed for key {key}: {e}.")
        return False

    async def delete_pattern(self, pattern: str) -> bool:
        if not self.client:
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
