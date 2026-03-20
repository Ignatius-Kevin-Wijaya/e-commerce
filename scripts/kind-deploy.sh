#!/usr/bin/env bash
# kind-deploy.sh — Bootstrap a KIND cluster and deploy the full stack
set -euo pipefail

CLUSTER_NAME="ecommerce"
NAMESPACE="ecommerce"

echo "🚀 Bootstrapping KIND cluster '$CLUSTER_NAME'..."

# 1. Create cluster if it doesn't exist
if ! kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
    echo "  Creating KIND cluster..."
    kind create cluster --name "$CLUSTER_NAME" --config infrastructure/kind/kind-config.yaml
else
    echo "  KIND cluster '$CLUSTER_NAME' already exists."
fi

# 2. Install NGINX Ingress Controller (KIND specific)
echo "  🔗 Installing NGINX Ingress Controller..."
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
echo "  ⏳ Waiting for ingress controller to be ready..."
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=180s >/dev/null

# 3. Build & Load Docker Images
echo "  🐳 Building and loading Docker images into KIND..."
services=("auth" "product" "cart" "order" "payment")
for svc in "${services[@]}"; do
    echo "    Building ${svc}-service..."
    docker build -q -t "ghcr.io/your-org/ecommerce-${svc}-service:latest" "backend/services/${svc}-service" >/dev/null
    kind load docker-image "ghcr.io/your-org/ecommerce-${svc}-service:latest" --name "$CLUSTER_NAME"
done

echo "    Building api-gateway..."
docker build -q -t "ghcr.io/your-org/ecommerce-api-gateway:latest" "backend/api-gateway" >/dev/null
kind load docker-image "ghcr.io/your-org/ecommerce-api-gateway:latest" --name "$CLUSTER_NAME"

echo "    Building frontend..."
docker build -q -t "ghcr.io/your-org/ecommerce-frontend:latest" --build-arg NEXT_PUBLIC_API_URL=http://api.ecommerce.local frontend >/dev/null
kind load docker-image "ghcr.io/your-org/ecommerce-frontend:latest" --name "$CLUSTER_NAME"

# 4. Apply Base Infrastructure
echo "  📦 Deploying Base Infrastructure..."
kubectl apply -f infrastructure/kubernetes/namespace.yaml
bash scripts/kind-create-secrets.sh

kubectl apply -f infrastructure/kubernetes/postgres/ -n "$NAMESPACE"
kubectl apply -f infrastructure/kubernetes/redis/ -n "$NAMESPACE"

echo "  ⏳ Waiting for databases to be ready (this may take a minute)..."
kubectl wait --for=condition=ready pod -l app=auth-db -n "$NAMESPACE" --timeout=120s || true
kubectl wait --for=condition=ready pod -l app=product-db -n "$NAMESPACE" --timeout=120s || true
kubectl wait --for=condition=ready pod -l app=order-db -n "$NAMESPACE" --timeout=120s || true
kubectl wait --for=condition=ready pod -l app=redis -n "$NAMESPACE" --timeout=120s || true

# 5. Apply Application Services
echo "  🔧 Deploying Application Services..."
for svc in auth product cart order payment gateway frontend; do
    kubectl apply -f "infrastructure/kubernetes/$svc/" -n "$NAMESPACE"
done

kubectl apply -f infrastructure/kubernetes/ingress/ingress.yaml -n "$NAMESPACE"

# 6. Deploy Monitoring Stack
echo "  📊 Deploying Monitoring Stack..."
kubectl apply -f infrastructure/kind/monitoring/monitoring-namespace.yaml
kubectl apply -f infrastructure/kind/monitoring/prometheus.yaml
kubectl apply -f infrastructure/kind/monitoring/grafana-dashboard.yaml
kubectl apply -f infrastructure/kind/monitoring/grafana.yaml
kubectl apply -f infrastructure/kind/monitoring/loki.yaml
kubectl apply -f infrastructure/kind/monitoring/promtail.yaml

echo ""
echo "✅ KIND Deployment Complete!"
echo ""
echo "🌐 Frontend:     http://ecommerce.local (Add to /etc/hosts: 127.0.0.1 ecommerce.local)"
echo "🌐 API Gateway:  http://api.ecommerce.local (Add to /etc/hosts: 127.0.0.1 api.ecommerce.local)"
echo "📈 Grafana:      http://localhost:30030 (admin / admin)"
echo "🔎 Prometheus:   http://localhost:30090"
echo ""
echo "Run 'make kind-status' to check pod status."
