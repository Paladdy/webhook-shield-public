import redis

from app.core.config import Settings


class RedisIdempotencyClient:
    """Redis client for gateway-level idempotency keys (SET NX EX)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

    def close(self) -> None:
        self._client.close()

    def ping(self) -> bool:
        return bool(self._client.ping())

    def register(self, idempotency_key: str) -> bool:
        """Return True on first sighting, False if key already exists."""
        key = f"{self._settings.idempotency_key_prefix}{idempotency_key}"
        return self._client.set(
            key,
            "1",
            nx=True,
            ex=self._settings.idempotency_ttl_seconds,
        )
