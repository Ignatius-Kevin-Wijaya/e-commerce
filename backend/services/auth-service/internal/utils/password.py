"""
Password hashing utilities using bcrypt.

LEARNING NOTES:
- NEVER store passwords in plaintext!
- bcrypt automatically handles salting (random data mixed into the hash).
- The "rounds" parameter controls how slow hashing is — slower = harder to brute-force.
- We use native bcrypt directly instead of passlib to avoid compatibility bugs.
"""

import bcrypt


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password. Returns a bcrypt hash string."""
    # rounds=6 gives ~8ms hash time, perfect for generating 65% CPU load at test target RPS
    salt = bcrypt.gensalt(rounds=6)
    hashed_bytes = bcrypt.hashpw(plain_password.encode('utf-8'), salt)
    return hashed_bytes.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check if a plaintext password matches a stored hash."""
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )
