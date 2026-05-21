from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "gateway_http_requests_total",
    "Total HTTP requests processed by the gateway",
    ["method", "path", "status"],
)

HTTP_REQUEST_DURATION = Histogram(
    "gateway_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

WEBHOOK_DUPLICATES = Counter(
    "gateway_webhook_duplicates_total",
    "Webhook requests rejected as idempotency duplicates",
    ["route"],
)

WEBHOOK_UPSTREAM_REQUESTS = Counter(
    "gateway_webhook_upstream_requests_total",
    "Requests forwarded to n8n",
    ["route", "status"],
)

WEBHOOK_UPSTREAM_ERRORS = Counter(
    "gateway_webhook_upstream_errors_total",
    "Upstream transport failures when forwarding to n8n",
    ["route"],
)
