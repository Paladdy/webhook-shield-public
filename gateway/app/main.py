import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import UpstreamUnavailableError, WebhookError
from app.core.lifespan import lifespan
from app.core.metrics import WEBHOOK_UPSTREAM_ERRORS
from app.middleware.metrics import MetricsMiddleware
from app.routers import health_router, metrics_router, webhooks_router

logger = logging.getLogger("gateway")


def create_app() -> FastAPI:
    app = FastAPI(
        title="webhook-shield gateway",
        version="0.2.0",
        lifespan=lifespan,
    )

    app.add_middleware(MetricsMiddleware)

    @app.exception_handler(WebhookError)
    async def webhook_error_handler(
        _request: Request,
        exc: WebhookError,
    ) -> JSONResponse:
        if isinstance(exc, UpstreamUnavailableError):
            WEBHOOK_UPSTREAM_ERRORS.labels(route="n8n").inc()
            logger.exception("n8n forward failed")
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(webhooks_router)
    return app


app = create_app()
