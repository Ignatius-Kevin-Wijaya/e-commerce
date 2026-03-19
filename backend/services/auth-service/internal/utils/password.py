"""
Password hashing utilities using bcrypt.

LEARNING NOTES:
- NEVER store passwords in plaintext!
- bcrypt automatically handles salting (random data mixed into the hash).
- The "rounds" parameter controls how slow hashing is — slower = harder to brute-force.
- passlib wraps bcrypt and provides a clean verify API.
"""

from passlib.context import CryptContext

# schemes=["bcrypt"] means we use bcrypt for hashing
# deprecated="auto" means old schemes auto-upgrade on next login
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password. Returns a bcrypt hash string."""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check if a plaintext password matches a stored hash."""
    return pwd_context.verify(plain_password, hashed_password)
