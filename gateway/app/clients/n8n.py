import httpx

from app.core.config import Settings
from app.core.exceptions import UpstreamUnavailableError


class N8nClient:
    """HTTP client for forwarding webhooks to n8n (shared connection pool)."""

    def __init__(self, settings: Settings) -> None:
        self._webhook_url = settings.n8n_webhook_url
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def forward_webhook(
        self,
        raw_body: bytes,
        *,
        signature: str | None,
    ) -> httpx.Response:
        if self._client is None:
            raise RuntimeError("N8nClient is not started")

        headers = {"Content-Type": "application/json"}
        if signature:
            headers["X-Signature"] = signature

        try:
            return await self._client.post(
                self._webhook_url,
                content=raw_body,
                headers=headers,
            )
        except httpx.RequestError as exc:
            raise UpstreamUnavailableError() from exc
