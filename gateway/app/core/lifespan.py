import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.clients.n8n import N8nClient
from app.clients.redis_idempotency import RedisIdempotencyClient
from app.core.config import get_settings
from app.services.webhook_service import WebhookService

logger = logging.getLogger("gateway")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    idempotency_client = RedisIdempotencyClient(settings)
    n8n_client = N8nClient(settings)

    await n8n_client.start()
    app.state.webhook_service = WebhookService(
        settings=settings,
        idempotency_client=idempotency_client,
        n8n_client=n8n_client,
    )
    app.state.idempotency_client = idempotency_client
    logger.info("gateway started n8n_url=%s", settings.n8n_webhook_url)

    try:
        yield
    finally:
        await n8n_client.close()
        idempotency_client.close()
        logger.info("gateway stopped")
