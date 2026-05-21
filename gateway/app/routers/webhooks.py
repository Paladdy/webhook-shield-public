import json

from fastapi import APIRouter, Depends, Header, Request, Response

from app.dependencies import get_webhook_service
from app.schemas.webhook import DuplicateWebhookResult, WebhookForwardResult
from app.services.webhook_service import WebhookService

router = APIRouter(prefix="/webhook", tags=["webhooks"])


@router.post("/google-sheet")
async def google_sheet_webhook(
    request: Request,
    x_signature: str | None = Header(default=None, alias="X-Signature"),
    service: WebhookService = Depends(get_webhook_service),
) -> Response:
    raw_body = await request.body()
    result = await service.ingest_google_sheet(raw_body, x_signature)

    match result:
        case DuplicateWebhookResult(idempotency_key=key):
            return Response(
                content=json.dumps(
                    {
                        "status": "duplicate",
                        "idempotency_key": key,
                    }
                ),
                media_type="application/json",
                status_code=200,
            )
        case WebhookForwardResult() as forwarded:
            return Response(
                content=forwarded.content,
                status_code=forwarded.status_code,
                media_type=forwarded.content_type,
            )
