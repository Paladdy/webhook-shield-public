from dataclasses import dataclass


@dataclass(frozen=True)
class WebhookForwardResult:
    status_code: int
    content: bytes
    content_type: str


@dataclass(frozen=True)
class DuplicateWebhookResult:
    idempotency_key: str
