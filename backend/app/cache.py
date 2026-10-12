import json
from time import monotonic

from redis.asyncio import Redis

from .config import Settings


class Cache:
    def __init__(self, settings: Settings):
        self.memory: dict[str, tuple[float, dict]] = {}
        self.redis = Redis.from_url(settings.redis_url, decode_responses=True) if settings.cache_backend == 'redis' else None

    async def start(self):
        if self.redis:
            await self.redis.ping()

    async def get(self, key: str):
        if self.redis:
            value = await self.redis.get('industrial:' + key)
            return json.loads(value) if value else None
        record = self.memory.get(key)
        return record[1] if record and record[0] > monotonic() else None

    async def put(self, key: str, value: dict, ttl=10):
        if self.redis:
            await self.redis.set('industrial:' + key, json.dumps(value, ensure_ascii=False), ex=ttl)
        else:
            self.memory[key] = (monotonic() + ttl, value)

    async def invalidate(self):
        self.memory.clear()
        if self.redis:
            await self.redis.delete('industrial:overview')

    async def close(self):
        if self.redis:
            await self.redis.aclose()
