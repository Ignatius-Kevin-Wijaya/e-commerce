#!/usr/bin/env bash
# build.sh — Build all Docker images for the e-commerce platform
set -euo pipefail

REGISTRY="${DOCKER_REGISTRY:-localhost:5000}"
TAG="${IMAGE_TAG:-latest}"

SERVICES=("auth-service" "product-service" "cart-service" "order-service" "payment-service" "api-gateway")

echo "🔨 Building all service images..."

for svc in "${SERVICES[@]}"; do
    if [ "$svc" = "api-gateway" ]; then
        context="./backend/api-gateway"
    else
        context="./backend/services/$svc"
    fi

    image_name="$REGISTRY/ecommerce-$svc:$TAG"
    echo "  Building $image_name"
    docker build -t "$image_name" "$context"
done

echo "✅ All images built successfully!"
echo ""
echo "To push images, run:"
echo "  DOCKER_REGISTRY=your-registry IMAGE_TAG=v1.0 bash scripts/push.sh"
