"""Limiter configuration for defense-in-depth rate limiting."""
from slowapi import Limiter
from slowapi.util import get_remote_address

import os

RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "false").lower() == "true"
limiter = Limiter(key_func=get_remote_address, enabled=RATE_LIMIT_ENABLED)
