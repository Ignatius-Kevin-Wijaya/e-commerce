"""
Auth middleware — validates JWT tokens on protected routes.

LEARNING NOTES:
- The gateway validates the JWT itself (it knows the secret key).
- If valid, it extracts the user_id and adds it as X-User-ID header.
- Backend services trust this header because only the gateway can set it
  (they are on an internal network in Kubernetes).
- This is the "edge authentication" pattern — auth happens at the edge.
"""

import os
from typing import Optional
from jose import JWTError, jwt

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "super_secret_dev_key")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")


def validate_token(authorization: Optional[str]) -> Optional[dict]:
    """
    Validate a Bearer token and return the payload.
    Returns None if invalid or missing.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


def extract_user_id(payload: dict) -> Optional[str]:
    """Extract user_id from the decoded JWT payload."""
    return payload.get("sub")
