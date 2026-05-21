import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    webhook_hmac_secret: str
    n8n_webhook_url: str
    redis_url: str
    idempotency_ttl_seconds: int
    idempotency_key_prefix: str


def get_settings() -> Settings:
    return Settings(
        webhook_hmac_secret=os.getenv("WEBHOOK_HMAC_SECRET", "super_test_secret_123"),
        n8n_webhook_url=os.getenv(
            "N8N_WEBHOOK_URL",
            "http://n8n:5678/webhook/google-sheet",
        ),
        redis_url=os.getenv("REDIS_URL", "redis://redis:6379/0"),
        idempotency_ttl_seconds=int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "86400")),
        idempotency_key_prefix=os.getenv(
            "IDEMPOTENCY_KEY_PREFIX",
            "gateway:idempotency:",
        ),
    )
