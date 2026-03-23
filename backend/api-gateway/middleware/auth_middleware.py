"""
Auth middleware — validates JWT tokens on protected routes.

LEARNING NOTES:
- The gateway validates the JWT itself (it knows the secret key).
- If valid, it extracts the user_id AND is_admin claim, forwarding both
  as X-User-ID and X-Is-Admin headers to backend services.
- Backend services trust these headers because only the gateway can set
  them (they are on an internal network in Kubernetes).
- This is the "edge authentication" pattern — auth happens at the edge.

SECURITY NOTES:
- We HARDCODE the allowed algorithm to ["HS256"] instead of reading it
  from an env var. Why? Because if an attacker can set JWT_ALGORITHM="none",
  the jose library would accept tokens with NO signature, allowing anyone to
  forge tokens for any user. This is the JWT Algorithm Confusion attack.
- We validate the secret key strength at startup to catch misconfigurations
  before they reach production.
"""

import logging
import os
import sys
from typing import Optional
from jose import JWTError, jwt

logger = logging.getLogger("gateway.auth")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "super_secret_dev_key")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# 🔒 SECURITY: Algorithm is HARDCODED — never read from env var.
# Reading from env would allow the "none" algorithm confusion attack.
ALLOWED_ALGORITHMS = ["HS256"]

# Fail fast in production if the secret is too weak (< 32 characters).
if len(JWT_SECRET_KEY) < 32 and ENVIRONMENT == "production":
    logger.critical(
        "FATAL: JWT_SECRET_KEY must be at least 32 characters in production. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
    sys.exit(1)


def validate_token(authorization: Optional[str]) -> Optional[dict]:
    """
    Validate a Bearer token and return the payload.
    Returns None if invalid or missing.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.replace("Bearer ", "")
    try:
        # 🔒 SECURITY: Use ALLOWED_ALGORITHMS (hardcoded list), not a variable.
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=ALLOWED_ALGORITHMS)
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


def extract_user_id(payload: dict) -> Optional[str]:
    """Extract user_id from the decoded JWT payload."""
    return payload.get("sub")


def extract_is_admin(payload: dict) -> bool:
    """
    Extract the is_admin flag from the decoded JWT payload.

    LEARNING NOTE:
    The is_admin claim is embedded in the JWT at login time by the auth
    service. Because the JWT is signed with our secret key, the gateway
    can trust this value without making a DB call. This is the key benefit
    of putting authorization claims directly in the token.
    """
    return bool(payload.get("is_admin", False))
