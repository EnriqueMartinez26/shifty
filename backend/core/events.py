import json
from typing import Any, Callable
from redis.asyncio import Redis
from core.redis import get_redis


class EventBus:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def publish(self, event: str, payload: dict[str, Any]):
        """Publica un evento en Redis Pub/Sub."""
        message = json.dumps(payload)
        await self.redis.publish(f"events:{event}", message)

    async def subscribe(self, event: str, handler: Callable[[dict[str, Any]], Any]):
        """Suscribe un handler a un evento."""
        async with self.redis.pubsub() as ps:
            await ps.subscribe(f"events:{event}")
            async for message in ps.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    await handler(data)


async def get_event_bus():
    """Dependency para FastAPI"""
    redis = await get_redis()
    return EventBus(redis)
