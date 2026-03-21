"""
API Gateway — main reverse proxy application.

LEARNING NOTES:
- The API Gateway is the single entry point for all external clients.
- It handles cross-cutting concerns: auth validation, rate limiting, logging, routing.
- It forwards requests to the correct backend service based on the URL path.
- Backend services NEVER receive requests directly from outside — only through the gateway.
"""

import logging
import os
import time

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from clients.auth_client import ServiceClient
from middleware.auth_middleware import extract_user_id, validate_token
from middleware.logging_middleware import generate_correlation_id, log_request
from routes import find_route

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("gateway")

app = FastAPI(
    title="E-Commerce API Gateway",
    description="Single entry point for all e-commerce microservices",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://ecommerce.local"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Instrumentator().instrument(app).expose(app)


@app.get("/health")
async def gateway_health():
    return {"status": "healthy", "service": "api-gateway"}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy(request: Request, path: str):
    """
    Catch-all reverse proxy handler.
    1. Find the matching route.
    2. Validate auth if required.
    3. Forward the request to the backend.
    4. Return the response to the client.
    """
    start_time = time.time()
    correlation_id = generate_correlation_id()

    full_path = f"/{path}"

    # Find matching route
    route = find_route(full_path)
    if not route:
        return JSONResponse(status_code=404, content={"detail": "Route not found"})

    # Auth check
    user_id = None
    if route.requires_auth:
        auth_header = request.headers.get("authorization")
        payload = validate_token(auth_header)
        if not payload:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
        user_id = extract_user_id(payload)

    # Build forwarding headers
    headers = dict(request.headers)
    headers["X-Correlation-ID"] = correlation_id
    if user_id:
        headers["X-User-ID"] = user_id

    # Read request body
    body = await request.body()

    # Forward to backend
    client = ServiceClient(route.upstream_url)
    try:
        upstream_response = await client.proxy_request(
            method=request.method,
            path=full_path,
            headers=headers,
            body=body if body else None,
            query_string=str(request.query_params),
        )
    except Exception as e:
        logger.error(f"Upstream error: {e}")
        return JSONResponse(status_code=502, content={"detail": "Service unavailable"})

    # Log the request
    duration_ms = (time.time() - start_time) * 1000
    log_request(request.method, full_path, correlation_id, upstream_response.status_code, duration_ms)

    # Return upstream response to client
    response_headers = {
        k: v for k, v in upstream_response.headers.items()
        if k.lower() not in ("transfer-encoding", "connection", "content-encoding", "content-length")
    }
    response_headers["X-Correlation-ID"] = correlation_id

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=response_headers,
        media_type=upstream_response.headers.get("content-type"),
    )
