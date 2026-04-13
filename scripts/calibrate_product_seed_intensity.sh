#!/usr/bin/env bash
# calibrate_product_seed_intensity.sh — grow the product catalog in controlled
# steps and measure how the DB-backed workload changes.
#
# What it does per level:
# 1. Seeds the catalog up to PRODUCT_ITEMS_PER_CATEGORY=<level>
# 2. Prints row counts, table size, and search-hit counts
# 3. Runs EXPLAIN ANALYZE on the product count query and page query
# 4. Optionally runs a product autoscaler smoke (H1/H2/H3/K1)
#
# Usage:
#   ./scripts/calibrate_product_seed_intensity.sh 1000 5000 10000
#   ./scripts/calibrate_product_seed_intensity.sh --smoke h1 5000
#   ./scripts/calibrate_product_seed_intensity.sh --smoke h3 5000
#   ./scripts/calibrate_product_seed_intensity.sh --smoke k1 5000
#   CALIBRATION_SEARCH_TERM=Phone PRODUCT_PAGE_SIZE=50 \
#     ./scripts/calibrate_product_seed_intensity.sh --smoke h1 5000 10000
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
NAMESPACE="${NAMESPACE:-ecommerce}"
SEARCH_TERM="${CALIBRATION_SEARCH_TERM:-Laptop}"
PAGE_SIZE="${PRODUCT_PAGE_SIZE:-100}"
PRODUCT_MAX_PAGE="${PRODUCT_MAX_PAGE:-12}"
DESCRIPTION_REPEAT="${PRODUCT_DESCRIPTION_REPEAT:-8}"
SMOKE_MODE=""
LEVELS=()

if [[ -x "${ROOT_DIR}/scripts/seed_data.sh" ]]; then
  SEED_SCRIPT="${ROOT_DIR}/scripts/seed_data.sh"
  SMOKE_SCRIPT="${ROOT_DIR}/scripts/product_autoscaler_smoke.sh"
elif [[ -x "${SCRIPT_DIR}/seed_data.sh" ]]; then
  SEED_SCRIPT="${SCRIPT_DIR}/seed_data.sh"
  SMOKE_SCRIPT="${SCRIPT_DIR}/product_autoscaler_smoke.sh"
else
  echo "❌ Could not find seed_data.sh and product_autoscaler_smoke.sh next to the calibrator." >&2
  exit 1
fi

usage() {
  cat <<'EOF'
Usage: ./scripts/calibrate_product_seed_intensity.sh [--smoke h1|h2|h3|k1] <items_per_category>...

Examples:
  ./scripts/calibrate_product_seed_intensity.sh 1000 5000 10000
  ./scripts/calibrate_product_seed_intensity.sh --smoke h1 5000
  ./scripts/calibrate_product_seed_intensity.sh --smoke h3 5000
  ./scripts/calibrate_product_seed_intensity.sh --smoke k1 5000
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --smoke)
      if [[ $# -lt 2 ]]; then
        echo "❌ --smoke requires h1, h2, h3, or k1" >&2
        usage
        exit 1
      fi
      SMOKE_MODE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      LEVELS+=("$1")
      shift
      ;;
  esac
done

if [[ "${#LEVELS[@]}" -eq 0 ]]; then
  echo "❌ Provide at least one PRODUCT_ITEMS_PER_CATEGORY level." >&2
  usage
  exit 1
fi

if [[ -n "${SMOKE_MODE}" && "${SMOKE_MODE}" != "h1" && "${SMOKE_MODE}" != "h2" && "${SMOKE_MODE}" != "h3" && "${SMOKE_MODE}" != "k1" ]]; then
  echo "❌ --smoke must be h1, h2, h3, or k1, got: ${SMOKE_MODE}" >&2
  exit 1
fi

for level in "${LEVELS[@]}"; do
  if ! [[ "${level}" =~ ^[1-9][0-9]*$ ]]; then
    echo "❌ Invalid level: ${level}. Use positive integers." >&2
    exit 1
  fi
done

run_psql() {
  if kubectl get pod product-db-0 -n "${NAMESPACE}" >/dev/null 2>&1; then
    kubectl exec -i product-db-0 -n "${NAMESPACE}" -- psql -P pager=off -U product_user -d product_db
  else
    docker compose exec -T product-db psql -P pager=off -U "${PRODUCT_DB_USER:-product_user}" -d "${PRODUCT_DB_NAME:-product_db}"
  fi
}

probe_database() {
  local level="$1"

  echo "=== Seed probe: ${level} items/category ==="
  run_psql <<SQL
\echo '-- catalog summary'
SELECT
  count(*) AS products_count,
  count(*) FILTER (WHERE is_deleted = false) AS active_products,
  pg_size_pretty(pg_total_relation_size('products')) AS products_table_size
FROM products;

\echo '-- search term hit counts'
SELECT
  COUNT(*) FILTER (WHERE name ILIKE '%${SEARCH_TERM}%') AS target_hits,
  COUNT(*) FILTER (WHERE name ILIKE '%Phone%') AS phone_hits,
  COUNT(*) FILTER (WHERE name ILIKE '%Camera%') AS camera_hits
FROM products
WHERE is_deleted = false;

\echo '-- count query plan'
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM products p
WHERE p.is_deleted = false
  AND p.name ILIKE '%${SEARCH_TERM}%';

\echo '-- page query plan (first run)'
EXPLAIN (ANALYZE, BUFFERS)
SELECT
  p.id, p.name, p.description, p.price, p.stock, p.image_url,
  p.category_id, p.is_deleted, p.created_at, p.updated_at,
  c.id, c.name, c.description, c.created_at
FROM products p
LEFT OUTER JOIN categories c ON c.id = p.category_id
WHERE p.is_deleted = false
  AND p.name ILIKE '%${SEARCH_TERM}%'
ORDER BY p.created_at DESC
LIMIT ${PAGE_SIZE} OFFSET 0;

\echo '-- page query plan (warm cache)'
EXPLAIN (ANALYZE, BUFFERS)
SELECT
  p.id, p.name, p.description, p.price, p.stock, p.image_url,
  p.category_id, p.is_deleted, p.created_at, p.updated_at,
  c.id, c.name, c.description, c.created_at
FROM products p
LEFT OUTER JOIN categories c ON c.id = p.category_id
WHERE p.is_deleted = false
  AND p.name ILIKE '%${SEARCH_TERM}%'
ORDER BY p.created_at DESC
LIMIT ${PAGE_SIZE} OFFSET 0;
SQL
}

for level in "${LEVELS[@]}"; do
  echo ""
  echo "============================================================"
  echo "Calibrating product seed intensity: ${level} items/category"
  echo "============================================================"

  PRODUCT_ITEMS_PER_CATEGORY="${level}" \
  PRODUCT_DESCRIPTION_REPEAT="${DESCRIPTION_REPEAT}" \
    "${SEED_SCRIPT}"

  probe_database "${level}"

  if [[ -n "${SMOKE_MODE}" ]]; then
    PRODUCT_PAGE_SIZE="${PAGE_SIZE}" \
    PRODUCT_MAX_PAGE="${PRODUCT_MAX_PAGE}" \
      "${SMOKE_SCRIPT}" "${SMOKE_MODE}"
  fi
done
