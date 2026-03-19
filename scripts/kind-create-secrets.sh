#!/usr/bin/env bash
# kind-create-secrets.sh — Idempotently create all K8s secrets for the
#                          local KIND cluster from .env.kind (or safe defaults).
#
# Usage:
#   bash scripts/kind-create-secrets.sh
#   make kind-secrets
#
# The script uses `kubectl create secret --dry-run=client -o yaml | kubectl apply -f -`
# so it is fully idempotent — safe to run on a fresh cluster or to update
# existing secrets in-place without deleting them first.
set -euo pipefail

NAMESPACE="ecommerce"
ENV_FILE=".env.kind"

# ─── Load .env.kind if present, otherwise use safe defaults ──────────────────
if [[ -f "$ENV_FILE" ]]; then
  echo "  📄 Loading secrets from $ENV_FILE"
  # Export every non-comment, non-blank line as an env var
  set -o allexport
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +o allexport
else
  echo "  ⚠️  $ENV_FILE not found — using built-in dev defaults."
  echo "     Copy .env.kind.example to .env.kind to customise values."
fi

# ─── Defaults (applied when the variable is unset or empty) ──────────────────
AUTH_DB_USER="${AUTH_DB_USER:-auth_user}"
AUTH_DB_PASSWORD="${AUTH_DB_PASSWORD:-change_me_auth}"
AUTH_DB_NAME="${AUTH_DB_NAME:-auth_db}"

PRODUCT_DB_USER="${PRODUCT_DB_USER:-product_user}"
PRODUCT_DB_PASSWORD="${PRODUCT_DB_PASSWORD:-change_me_product}"
PRODUCT_DB_NAME="${PRODUCT_DB_NAME:-product_db}"

ORDER_DB_USER="${ORDER_DB_USER:-order_user}"
ORDER_DB_PASSWORD="${ORDER_DB_PASSWORD:-change_me_order}"
ORDER_DB_NAME="${ORDER_DB_NAME:-order_db}"

JWT_SECRET_KEY="${JWT_SECRET_KEY:-super_secret_dev_key_change_me}"

STRIPE_SECRET_KEY="${STRIPE_SECRET_KEY:-sk_test_fake_key}"
STRIPE_WEBHOOK_SECRET="${STRIPE_WEBHOOK_SECRET:-whsec_fake_secret}"

# ─── Helper: create or update a secret idempotently ──────────────────────────
apply_secret() {
  # Pass all args straight to `kubectl create secret generic`; pipe through apply.
  kubectl create secret generic "$@" \
    --namespace "$NAMESPACE" \
    --dry-run=client -o yaml \
  | kubectl apply -f - --namespace "$NAMESPACE"
}

echo "  🔑 Creating / updating secrets in namespace '$NAMESPACE'..."

# ── 1. auth-secrets (used by auth-service + api-gateway) ─────────────────────
apply_secret auth-secrets \
  --from-literal=database-url="postgresql+asyncpg://${AUTH_DB_USER}:${AUTH_DB_PASSWORD}@auth-db:5432/${AUTH_DB_NAME}" \
  --from-literal=jwt-secret="${JWT_SECRET_KEY}"
echo "     ✓ auth-secrets"

# ── 2. auth-db-secrets (used by the auth Postgres StatefulSet) ───────────────
apply_secret auth-db-secrets \
  --from-literal=username="${AUTH_DB_USER}" \
  --from-literal=password="${AUTH_DB_PASSWORD}"
echo "     ✓ auth-db-secrets"

# ── 3. product-secrets (used by product-service) ─────────────────────────────
apply_secret product-secrets \
  --from-literal=database-url="postgresql+asyncpg://${PRODUCT_DB_USER}:${PRODUCT_DB_PASSWORD}@product-db:5432/${PRODUCT_DB_NAME}"
echo "     ✓ product-secrets"

# ── 4. product-db-secrets (used by the product Postgres StatefulSet) ─────────
apply_secret product-db-secrets \
  --from-literal=username="${PRODUCT_DB_USER}" \
  --from-literal=password="${PRODUCT_DB_PASSWORD}"
echo "     ✓ product-db-secrets"

# ── 5. cart-secrets (used by cart-service) ───────────────────────────────────
apply_secret cart-secrets \
  --from-literal=redis-url="redis://redis:6379/0"
echo "     ✓ cart-secrets"

# ── 6. order-secrets (used by order-service) ─────────────────────────────────
apply_secret order-secrets \
  --from-literal=database-url="postgresql+asyncpg://${ORDER_DB_USER}:${ORDER_DB_PASSWORD}@order-db:5432/${ORDER_DB_NAME}"
echo "     ✓ order-secrets"

# ── 7. order-db-secrets (used by the order Postgres StatefulSet) ─────────────
apply_secret order-db-secrets \
  --from-literal=username="${ORDER_DB_USER}" \
  --from-literal=password="${ORDER_DB_PASSWORD}"
echo "     ✓ order-db-secrets"

# ── 8. payment-secrets (used by payment-service) ─────────────────────────────
apply_secret payment-secrets \
  --from-literal=database-url="postgresql+asyncpg://${ORDER_DB_USER}:${ORDER_DB_PASSWORD}@order-db:5432/${ORDER_DB_NAME}" \
  --from-literal=stripe-secret-key="${STRIPE_SECRET_KEY}" \
  --from-literal=stripe-webhook-secret="${STRIPE_WEBHOOK_SECRET}"
echo "     ✓ payment-secrets"

echo "  ✅ All secrets applied successfully."
