class WebhookError(Exception):
    """Domain error mapped to HTTP response by exception handler."""

    status_code: int = 500
    detail: str = "Internal error"

    def __init__(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class InvalidJsonError(WebhookError):
    status_code = 400
    detail = "Invalid JSON body"


class InvalidPayloadError(WebhookError):
    status_code = 400
    detail = "JSON body must be an object"


class InvalidSignatureError(WebhookError):
    status_code = 401
    detail = "Invalid signature"


class MissingIdempotencyKeyError(WebhookError):
    status_code = 400
    detail = "Missing idempotency_key"


class UpstreamUnavailableError(WebhookError):
    status_code = 502
    detail = "Upstream n8n unavailable"
