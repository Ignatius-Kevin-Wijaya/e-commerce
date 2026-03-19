#!/usr/bin/env bash
# cleanup.sh — Full cleanup: stop containers, remove volumes & images
set -euo pipefail

echo "🧹 Cleaning up e-commerce project..."

echo "  Stopping containers..."
docker compose down -v --remove-orphans 2>/dev/null || true

echo "  Removing built images..."
docker images --filter "reference=*ecommerce*" -q | xargs -r docker rmi -f 2>/dev/null || true

echo "  Pruning dangling images..."
docker image prune -f 2>/dev/null || true

echo "✅ Cleanup complete!"
