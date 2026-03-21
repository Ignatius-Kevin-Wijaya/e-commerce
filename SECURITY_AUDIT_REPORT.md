# Security Audit Report - E-Commerce Microservices Project

**Date:** 2026-03-21
**Auditor:** Security Review
**Project:** E-Commerce Microservices Platform

---

## Executive Summary

This report identifies security vulnerabilities across the e-commerce microservices architecture. The issues range from **Critical** to **Low** severity and cover authentication, authorization, data exposure, API security, infrastructure, and frontend concerns.

**Total Issues Found:** 25

| Severity | Count |
|----------|-------|
| 🔴 Critical | 5 |
| 🟠 High | 5 |
| 🟡 Medium | 8 |
| 🔵 Low | 7 |

---

## 🔴 CRITICAL Severity Issues

### 1. Missing Admin Authorization on Product/Category Endpoints

**Location:** `backend/services/product-service/internal/handler/product_handler.py`

**Problem:** All write operations on products and categories have **no authorization checks**:
- `POST /products` - Any user can create products
- `PUT /products/{id}` - Any user can modify products
- `DELETE /products/{id}` - Any user can delete products
- `POST /categories` - Any user can create categories
- `PATCH /products/{id}/stock/*` - Any user can manipulate stock

**Impact:** Attackers can modify prices, create fake products, manipulate inventory, and destroy business data.

**Recommendation:**
```python
# Add admin check middleware or dependency
from fastapi import Depends, HTTPException

async def require_admin(x_user_id: str = Header(..., alias="X-User-ID")):
    # Fetch user and verify is_admin claim from JWT or database
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
```

---

### 2. Missing Order Status Authorization

**Location:** `backend/services/order-service/internal/handler/order_handler.py:125-141`

**Problem:** The `PATCH /orders/{order_id}/status` endpoint has **no authorization check**:
```python
@router.patch("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: UUID,
    body: UpdateStatusRequest,
    service: OrderService = Depends(get_order_service),
):
    # No check for admin role!
    new_status = OrderStatus(body.status)
    ...
```

**Impact:** Any authenticated user can change order status (mark orders as delivered without payment, cancel orders, etc.).

**Recommendation:** Restrict this endpoint to admin users only via an admin role check.

---

### 3. No Authorization on Payment Endpoints (IDOR Vulnerability)

**Location:** `backend/services/payment-service/internal/handler/payment_handler.py`

**Problem:** Multiple endpoints lack ownership verification:
- `GET /payments/{payment_id}` - No check if user owns the payment
- `GET /payments/order/{order_id}` - No check if user owns the order

**Impact:** Users can view payment details of other users' orders (Insecure Direct Object Reference - IDOR).

**Recommendation:** Add user ownership verification:
```python
@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: UUID,
    x_user_id: str = Header(..., alias="X-User-ID"),
    service: PaymentService = Depends(get_payment_service),
):
    payment = await service.get_payment(payment_id)
    # Verify ownership
    if str(payment.user_id) != x_user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return payment_to_response(payment)
```

---

### 4. Missing Rate Limiting on Authentication Endpoints

**Location:** `backend/api-gateway/routes.py:33`

**Problem:** Auth endpoints have `requires_auth=False`, meaning:
- `/auth/login` - **No rate limiting** (brute force attacks possible)
- `/auth/register` - **No rate limiting** (account creation spam)

**Impact:** Attackers can brute-force passwords, create spam accounts, and perform credential stuffing attacks.

**Recommendation:**
- Implement rate limiting specifically on auth endpoints
- Suggested limits:
  - Login: 5 attempts per minute per IP
  - Register: 3 registrations per hour per IP
- Consider implementing account lockout after failed attempts

---

### 5. X-User-ID Header Trust Issue (Service-to-Service Security)

**Location:** All backend services (`cart_handler.py`, `order_handler.py`, `payment_handler.py`)

**Problem:** Backend services blindly trust the `X-User-ID` header:
```python
x_user_id: str = Header(..., alias="X-User-ID")
```

**Impact:** If an attacker bypasses the gateway or if a service is exposed directly, they can impersonate any user by setting this header.

**Recommendation:**
1. Add internal network restrictions (services should only accept traffic from gateway)
2. Consider implementing service-to-service authentication (mTLS)
3. Use Kubernetes NetworkPolicies to restrict pod-to-pod communication
4. Validate at the service layer that requests come from trusted sources

---

## 🟠 HIGH Severity Issues

### 6. Hardcoded/Weak Default Secrets

**Location:** Multiple files

| File | Line | Issue |
|------|------|-------|
| `backend/api-gateway/middleware/auth_middleware.py` | 16 | `JWT_SECRET_KEY = "super_secret_dev_key"` |
| `backend/services/auth-service/internal/utils/jwt.py` | 19 | `SECRET_KEY = "dev-secret-change-me"` |
| `infrastructure/kind/dev-secrets.yaml` | 15 | `jwt-secret: "super_secret_dev_key_change_me"` |
| `docker-compose.yaml` | 74, 169 | Default passwords in environment variables |

**Impact:** Attackers can forge JWT tokens, decrypt sensitive data, and access services.

**Recommendation:**
1. Use strong, randomly generated secrets (256+ bits)
2. Use external secret management:
   - HashiCorp Vault
   - AWS Secrets Manager / Parameter Store
   - Kubernetes Secrets with encryption at rest
3. Enforce secret validation at startup (reject weak/placeholder values in production):
```python
import os
import sys

JWT_SECRET = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET or len(JWT_SECRET) < 32:
    if os.getenv("ENVIRONMENT") == "production":
        sys.exit("FATAL: JWT_SECRET_KEY must be at least 32 characters in production")
```

---

### 7. Potential SQL Injection (Unverified Parameterized Queries)

**Location:** All repository files, especially search functionality

**Problem:** While SQLAlchemy ORM provides protection, the search parameter flows directly to queries without explicit sanitization verification.

**Impact:** Potential SQL injection if raw queries are used.

**Recommendation:**
- Ensure all search/filter operations use SQLAlchemy's safe query building
- Never use f-strings or string concatenation for SQL
- Add parameterized query validation in code review process

---

### 8. No Input Validation on Cart Data (Price Manipulation)

**Location:** `backend/services/cart-service/internal/handler/cart_handler.py:82-97`

**Problem:** Cart accepts arbitrary product data from client:
```python
class AddToCartRequest(BaseModel):
    product_id: str
    product_name: str = ""  # Client provides this
    price: float = 0.0      # Client provides this!
```

**Impact:** Price manipulation - users could add items with arbitrary prices.

**Recommendation:**
1. Fetch product price from the product service at checkout time
2. Never trust client-provided prices
3. Validate product exists and get current price server-side:
```python
# In order service, before creating order
product = await product_client.get_product(item.product_id)
if product.price != item.price:
    raise OrderServiceError("Price mismatch - please refresh cart")
```

---

### 9. Webhook Endpoint Security Issues

**Location:** `backend/services/payment-service/internal/handler/webhook_handler.py`

**Problems:**
1. Uses mock Stripe client (not real signature verification)
2. Returns minimal event handling (handlers are empty stubs)
3. No idempotency on webhook processing

**Impact:**
- In production, webhooks could be replayed
- Failed webhook handling could lead to inconsistent payment states

**Recommendation:**
1. Use real Stripe SDK for signature verification
2. Implement idempotent webhook processing:
```python
# Log and check for already processed events
async def stripe_webhook(request: Request):
    event = StripeClient.construct_event(payload)

    # Check idempotency
    if await payment_repo.is_event_processed(event["id"]):
        return {"received": True, "status": "already_processed"}

    # Process event...
    await payment_repo.mark_event_processed(event["id"])
```
3. Complete event handlers for payment status updates

---

### 10. Overly Permissive CORS Configuration

**Location:** `backend/api-gateway/gateway.py:41-47`

**Problem:**
```python
allow_origins=["http://localhost:3000", "http://ecommerce.local"],
allow_credentials=True,
allow_methods=["*"],
allow_headers=["*"],
```

**Issues:**
- Development origins hardcoded in code
- `allow_headers=["*"]` is overly permissive
- Not configurable via environment variables

**Impact:** Potential CORS-based attacks in misconfigured deployments.

**Recommendation:**
```python
import os

ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
)
```

---

## 🟡 MEDIUM Severity Issues

### 11. JWT Token Storage in localStorage (XSS Vulnerability)

**Location:** `frontend/lib/auth-context.tsx`

**Problem:**
```typescript
localStorage.setItem('access_token', tokens.access_token);
localStorage.setItem('refresh_token', tokens.refresh_token);
```

**Impact:** Vulnerable to XSS attacks. If the site has any XSS vulnerability, tokens can be stolen.

**Recommendation:**
1. Use HTTP-only cookies for refresh tokens (most secure)
2. Consider short-lived access tokens in memory with HTTP-only refresh
3. Implement Content Security Policy (CSP) headers to mitigate XSS
4. If keeping localStorage, ensure strict CSP and sanitize all user inputs

---

### 12. Missing HTTPS Enforcement

**Location:** `infrastructure/kubernetes/ingress/ingress.yaml:8`

**Problem:**
```yaml
nginx.ingress.kubernetes.io/ssl-redirect: "false"
```

**Impact:** Traffic can be intercepted over HTTP in production.

**Recommendation:** Enable SSL redirect in production:
```yaml
nginx.ingress.kubernetes.io/ssl-redirect: "true"
nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
```

---

### 13. No Refresh Token Reuse Detection

**Location:** `backend/services/auth-service/internal/service/auth_service.py`

**Problem:** When a refresh token is used, the old one is revoked and a new one issued, but there's **no detection** if a revoked token is used (which could indicate token theft).

**Impact:** Compromised refresh tokens could be used without detection.

**Recommendation:** Implement refresh token reuse detection:
```python
async def refresh_access_token(self, refresh_token: str) -> dict:
    session = await self.user_repo.find_session_by_token(refresh_token)

    # Detect potential token theft
    if session and session.is_revoked:
        # Token was already used - possible theft
        # Revoke ALL sessions for this user
        await self.user_repo.revoke_all_user_sessions(session.user_id)
        raise AuthServiceError("Security alert - please re-authenticate", 401)
```

---

### 14. Weak Password Complexity Requirements

**Location:** `backend/services/auth-service/internal/service/auth_service.py:56-58`

**Problem:**
```python
if len(password) < 8:
    raise AuthServiceError("Password must be at least 8 characters")
```

**Impact:** Weak passwords like "password123" or "qwerty123" are accepted.

**Recommendation:** Implement comprehensive password validation:
```python
import re

def validate_password(password: str) -> None:
    if len(password) < 12:
        raise AuthServiceError("Password must be at least 12 characters")
    if not re.search(r'[A-Z]', password):
        raise AuthServiceError("Password must contain uppercase letter")
    if not re.search(r'[a-z]', password):
        raise AuthServiceError("Password must contain lowercase letter")
    if not re.search(r'[0-9]', password):
        raise AuthServiceError("Password must contain a number")
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        raise AuthServiceError("Password must contain special character")
    # Consider using zxcvbn or haveibeenpwned API for breach check
```

---

### 15. Database Credentials in Docker Compose

**Location:** `docker-compose.yaml`

**Problem:** PostgreSQL credentials exposed in environment variables:
```yaml
POSTGRES_PASSWORD: ${AUTH_DB_PASSWORD:-change_me_auth}
```

**Impact:** Anyone with access to docker-compose can see credentials.

**Recommendation:**
1. Use Docker secrets for production
2. Use `.env` files that are gitignored
3. Never commit credentials to version control
4. Use Kubernetes Secrets in production

---

### 16. Redis Without Authentication

**Location:** `docker-compose.yaml:53-63`

**Problem:** Redis is deployed without password:
```yaml
redis:
  image: redis:7-alpine
  # No password configured!
```

**Impact:** If Redis is exposed, anyone can access cart data.

**Recommendation:** Configure Redis with authentication:
```yaml
redis:
  image: redis:7-alpine
  command: redis-server --requirepass ${REDIS_PASSWORD}
```

---

### 17. Missing Security Headers

**Location:** API Gateway and Frontend (missing)

**Problem:** Missing HTTP security headers:
- `Content-Security-Policy`
- `X-Frame-Options`
- `X-Content-Type-Options`
- `Strict-Transport-Security`
- `X-XSS-Protection`

**Impact:** Various browser-based attacks (clickjacking, XSS, MIME sniffing).

**Recommendation:** Add security headers middleware:
```python
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        return response

app.add_middleware(SecurityHeadersMiddleware)
```

---

### 18. No Account Lockout/Rate Limiting on Login Failures

**Location:** `backend/services/auth-service/internal/service/auth_service.py`

**Problem:** No tracking of failed login attempts. An attacker can make unlimited login attempts.

**Impact:** Brute force attacks are not mitigated at the account level.

**Recommendation:** Implement account lockout:
```python
# Track failed attempts in Redis or database
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 30

async def login(self, email: str, password: str, ...):
    # Check lockout
    if await self.is_account_locked(email):
        raise AuthServiceError("Account locked - try again later", 423)

    user = await self.user_repo.find_by_email(email)
    if not user or not verify_password(password, user.hashed_password):
        await self.record_failed_attempt(email)
        raise AuthServiceError("Invalid email or password", 401)

    # Reset failed attempts on success
    await self.clear_failed_attempts(email)
    ...
```

---

## 🔵 LOW Severity Issues

### 19. Verbose Error Messages

**Location:** Various endpoints

**Problem:** Errors like "Email already registered" and "Username already taken" can help attackers enumerate valid accounts.

**Recommendation:** Use generic messages in production:
```python
# Instead of:
raise AuthServiceError("Email already registered", 409)
# Use:
raise AuthServiceError("Registration failed. Please try different credentials.", 400)
```

---

### 20. SQL Query Logging in Development

**Location:** `backend/services/auth-service/cmd/main.py:34`

**Problem:**
```python
echo=(ENVIRONMENT == "development"),
```

**Impact:** SQL queries logged in development mode. Ensure this is disabled in production.

**Recommendation:** Verify `ENVIRONMENT` is set correctly in production deployments.

---

### 21. Missing Index on Sessions Table

**Location:** `backend/services/auth-service/migrations/002_create_sessions.sql`

**Problem:** The `refresh_token` column needs an index for fast lookups during token validation.

**Recommendation:** Add index:
```sql
CREATE INDEX IF NOT EXISTS idx_sessions_refresh_token ON sessions(ref_token);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
```

---

### 22. No Pagination Limits on Order Endpoints

**Location:** `backend/services/order-service/internal/handler/order_handler.py:101-108`

**Problem:** `GET /orders` returns all orders without pagination - potential DoS vector for users with many orders.

**Recommendation:** Add pagination with a reasonable default limit.

---

### 23. Container Ports Exposed in Docker Compose

**Location:** `docker-compose.yaml`

**Problem:** All service ports are mapped to host:
```yaml
ports:
  - "5433:5432"  # Exposes database!
  - "8001:8001"  # Exposes auth service directly!
```

**Impact:** Direct access to internal services bypasses gateway security.

**Recommendation:** In production, only expose the gateway:
```yaml
# Remove port mappings for internal services
# Only expose gateway and frontend
api-gateway:
  ports:
    - "8080:8080"
frontend:
  ports:
    - "3000:3000"
# All other services - no ports exposed
```

---

### 24. Health Endpoints Expose Infrastructure Info

**Location:** Health check endpoints across all services

**Problem:** Health endpoints are public and may leak infrastructure information.

**Impact:** Minor - information disclosure.

**Recommendation:** Keep health endpoints simple and don't include version/deployment info in production.

---

### 25. JWT Algorithm Confusion Risk

**Location:** JWT validation code in `auth_middleware.py` and `jwt.py`

**Problem:** The algorithm is configurable via `JWT_ALGORITHM` environment variable. If set to "none" or asymmetric algorithms are introduced insecurely, tokens could be forged.

**Recommendation:** Hardcode allowed algorithm:
```python
ALLOWED_ALGORITHMS = ["HS256"]
payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=ALLOWED_ALGORITHMS)
```

---

## Infrastructure Security Recommendations

### Kubernetes Security

| Area | Recommendation |
|------|----------------|
| Network Policies | Restrict pod-to-pod communication - services should only communicate with gateway and their dependencies |
| Pod Security Standards | Already running as non-root (✓) - add `runAsNonRoot: true` to pod spec |
| Secret Encryption | Enable Kubernetes secrets encryption at rest |
| RBAC | Implement proper role-based access control for Kubernetes resources |
| Service Mesh | Consider Istio/Linkerd for mTLS between services |

### Monitoring & Observability

| Area | Recommendation |
|------|----------------|
| Audit Logging | Log all authentication events, order changes, payment operations |
| Security Alerts | Configure alerts for suspicious patterns (multiple failed logins, unusual order volumes) |
| Log Sanitization | Ensure no sensitive data (passwords, tokens) is logged |
| SIEM Integration | Consider integrating with security information and event management |

---

## Priority Fixes Roadmap

### Immediate (P0)
1. Add admin authorization checks to product/order endpoints
2. Add rate limiting to auth endpoints
3. Fix hardcoded secrets with proper secret management

### High Priority (P1)
4. Validate cart prices server-side
5. Add payment ownership verification
6. Implement proper webhook signature verification

### Medium Priority (P2)
7. Move tokens to HTTP-only cookies
8. Implement password complexity requirements
9. Add security headers
10. Enable HTTPS redirect

### Low Priority (P3)
11. Implement verbose error message fixes
12. Add pagination to order endpoints
13. Remove exposed ports from docker-compose

---

## Conclusion

This security audit identified **25 issues** across the e-commerce microservices architecture. The most critical issues involve **missing authorization checks** on administrative endpoints and **missing rate limiting** on authentication endpoints, which could allow attackers to manipulate business data or perform brute-force attacks.

Immediate attention should be given to:
1. Adding proper authorization to product management and order status endpoints
2. Implementing rate limiting on authentication endpoints
3. Replacing hardcoded secrets with proper secret management

Implementing these fixes along with the medium and low priority items will significantly improve the security posture of the application.

---

*End of Security Audit Report*