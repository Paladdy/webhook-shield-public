import json
import logging
from typing import Any

from app.clients.n8n import N8nClient
from app.clients.redis_idempotency import RedisIdempotencyClient
from app.core.config import Settings
from app.core.exceptions import (
    InvalidJsonError,
    InvalidPayloadError,
    InvalidSignatureError,
    MissingIdempotencyKeyError,
)
from app.core.metrics import (
    WEBHOOK_DUPLICATES,
    WEBHOOK_UPSTREAM_REQUESTS,
)
from app.core.security import verify_hmac_signature
from app.schemas.webhook import DuplicateWebhookResult, WebhookForwardResult

logger = logging.getLogger("gateway")

GOOGLE_SHEET_ROUTE = "google-sheet"


class WebhookService:
    def __init__(
        self,
        settings: Settings,
        idempotency_client: RedisIdempotencyClient,
        n8n_client: N8nClient,
    ) -> None:
        self._settings = settings
        self._idempotency = idempotency_client
        self._n8n = n8n_client

    def parse_body(self, raw_body: bytes) -> dict[str, Any]:
        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise InvalidJsonError() from exc
        if not isinstance(parsed, dict):
            raise InvalidPayloadError()
        return parsed

    def verify_signature(
        self,
        raw_body: bytes,
        parsed: dict[str, Any],
        signature: str | None,
    ) -> None:
        if not verify_hmac_signature(
            self._settings.webhook_hmac_secret,
            raw_body,
            signature,
            parsed,
        ):
            raise InvalidSignatureError()

    def require_idempotency_key(self, parsed: dict[str, Any]) -> str:
        idempotency_key = parsed.get("idempotency_key")
        if not idempotency_key or not isinstance(idempotency_key, str):
            raise MissingIdempotencyKeyError()
        return idempotency_key

    async def ingest_google_sheet(
        self,
        raw_body: bytes,
        signature: str | None,
    ) -> WebhookForwardResult | DuplicateWebhookResult:
        parsed = self.parse_body(raw_body)
        self.verify_signature(raw_body, parsed, signature)
        idempotency_key = self.require_idempotency_key(parsed)

        if not self._idempotency.register(idempotency_key):
            WEBHOOK_DUPLICATES.labels(route=GOOGLE_SHEET_ROUTE).inc()
            logger.info("duplicate idempotency_key=%s", idempotency_key)
            return DuplicateWebhookResult(idempotency_key=idempotency_key)

        upstream = await self._n8n.forward_webhook(raw_body, signature=signature)
        WEBHOOK_UPSTREAM_REQUESTS.labels(
            route=GOOGLE_SHEET_ROUTE,
            status=str(upstream.status_code),
        ).inc()

        logger.info(
            "forwarded idempotency_key=%s upstream_status=%s",
            idempotency_key,
            upstream.status_code,
        )
        return WebhookForwardResult(
            status_code=upstream.status_code,
            content=upstream.content,
            content_type=upstream.headers.get("content-type", "application/json"),
        )
