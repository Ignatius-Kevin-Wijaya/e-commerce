"""
Admission control — cap the requests in flight per pod and shed the excess.

Off unless MAX_INFLIGHT_REQUESTS > 0, so the closed-loop experiments run the
service unchanged.

Why: under open-loop overload an unprotected single-worker pod keeps accepting
work it can never finish. Goodput falls to zero, /metrics and the probes stop
answering, and the request-rate autoscalers lose their signal (open-loop pilot,
2026-10-05). With a cap the pod keeps serving at capacity and answers the
excess immediately with 503, like a load-shedding gateway would.

Register it LAST (app.add_middleware after every other middleware): Starlette
makes the last-added middleware the outermost, so a shed request skips the
gateway check, the DB session and the instrumentation. Rejecting must be cheap:
when shedding ran inside those layers, a shipping pod still collapsed above
~80 req/s because rejecting alone used its whole CPU limit (calibration,
2026-10-06). As a side effect http_requests_total keeps counting only served
requests, the same signal H3/K1 used in the closed-loop campaign; shed
requests are counted in http_requests_shed_total.
"""

import json
import os

try:
    from prometheus_client import Counter, Gauge
except ImportError:  # unit tests without the service dependencies
    Counter = Gauge = None

MAX_INFLIGHT_REQUESTS = int(os.getenv("MAX_INFLIGHT_REQUESTS", "0") or 0)

# Probes and scrapes must keep working while the pod is saturated.
EXEMPT_PREFIXES = ("/metrics", "/health", "/ready")

_SHED_TOTAL = (
    Counter("http_requests_shed_total", "Requests rejected with 503 by admission control")
    if Counter
    else None
)
_INFLIGHT = Gauge("http_requests_inflight", "Requests currently admitted") if Gauge else None

_SHED_BODY = json.dumps({"detail": "Service overloaded, retry later"}).encode()
_SHED_HEADERS = [
    (b"content-type", b"application/json"),
    (b"content-length", str(len(_SHED_BODY)).encode()),
    (b"retry-after", b"1"),
]


class AdmissionControlMiddleware:
    """Pure ASGI middleware: at most `max_inflight` concurrent HTTP requests."""

    def __init__(self, app, max_inflight: int = MAX_INFLIGHT_REQUESTS):
        self.app = app
        self.max_inflight = max_inflight
        self.inflight = 0

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or self.max_inflight <= 0
            or scope.get("path", "").startswith(EXEMPT_PREFIXES)
        ):
            await self.app(scope, receive, send)
            return

        if self.inflight >= self.max_inflight:
            if _SHED_TOTAL is not None:
                _SHED_TOTAL.inc()
            await send({"type": "http.response.start", "status": 503, "headers": _SHED_HEADERS})
            await send({"type": "http.response.body", "body": _SHED_BODY})
            return

        # Single event loop per worker: a plain counter is race-free.
        self.inflight += 1
        if _INFLIGHT is not None:
            _INFLIGHT.inc()
        try:
            await self.app(scope, receive, send)
        finally:
            self.inflight -= 1
            if _INFLIGHT is not None:
                _INFLIGHT.dec()
