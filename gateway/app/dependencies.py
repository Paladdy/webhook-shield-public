from fastapi import Request

from app.services.webhook_service import WebhookService


def get_webhook_service(request: Request) -> WebhookService:
    return request.app.state.webhook_service
