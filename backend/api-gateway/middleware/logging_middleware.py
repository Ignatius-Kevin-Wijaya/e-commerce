"""
Logging middleware — structured JSON logging with correlation IDs.

LEARNING NOTES:
- A correlation ID (X-Correlation-ID) is a unique string that follows a request
  across all services. It lets you trace a single user request through logs
  from gateway → auth → product → order services.
- Structured JSON logs are machine-parseable — tools like Loki/ELK can search them.
"""

import logging
import time
import uuid

logger = logging.getLogger("gateway")


def generate_correlation_id() -> str:
    """Generate a unique correlation ID for request tracing."""
    return str(uuid.uuid4())


def log_request(method: str, path: str, correlation_id: str, status_code: int, duration_ms: float):
    """Log a structured request entry."""
    logger.info(
        "request",
        extra={
            "method": method,
            "path": path,
            "correlation_id": correlation_id,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 2),
        },
    )
