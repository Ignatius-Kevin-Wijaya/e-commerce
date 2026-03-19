#!/usr/bin/env bash
# migrate.sh — Run SQL migrations against each service database via Docker or Kubernetes
set -euo pipefail

USE_KUBECTL=0
if command -v kubectl >/dev/null 2>&1 && kubectl get pod auth-db-0 -n ecommerce >/dev/null 2>&1; then
    USE_KUBECTL=1
    echo "☸️  Detected Kubernetes cluster, using kubectl exec..."
fi

run_migrations() {
    local container="$1"
    local db_name="$2"
    local db_user="$3"
    local migrations_dir="$4"

    echo "  Running migrations in $migrations_dir against $db_name..."

    for sql_file in "$migrations_dir"/*.sql; do
        if [ -f "$sql_file" ]; then
            echo "    → $(basename "$sql_file")"
            if [ "$USE_KUBECTL" -eq 1 ]; then
                kubectl exec -i "${container}-0" -n ecommerce -- psql -q -U "$db_user" -d "$db_name" < "$sql_file"
            else
                docker compose exec -T "$container" psql -q -U "$db_user" -d "$db_name" < "$sql_file"
            fi
        fi
    done
}

echo "🗄️  Running database migrations..."

# Auth DB
run_migrations \
    "auth-db" "${AUTH_DB_NAME:-auth_db}" "${AUTH_DB_USER:-auth_user}" \
    "./backend/services/auth-service/migrations"

# Product DB
run_migrations \
    "product-db" "${PRODUCT_DB_NAME:-product_db}" "${PRODUCT_DB_USER:-product_user}" \
    "./backend/services/product-service/migrations"

# Order DB (used by order + payment services)
run_migrations \
    "order-db" "${ORDER_DB_NAME:-order_db}" "${ORDER_DB_USER:-order_user}" \
    "./backend/services/order-service/migrations"

# Payment migrations (also in order DB)
run_migrations \
    "order-db" "${ORDER_DB_NAME:-order_db}" "${ORDER_DB_USER:-order_user}" \
    "./backend/services/payment-service/migrations"

echo "✅ All migrations complete!"
