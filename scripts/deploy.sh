#!/usr/bin/env bash
# deploy.sh — Deploy all services to Kubernetes
set -euo pipefail

NAMESPACE="${K8S_NAMESPACE:-ecommerce}"
K8S_DIR="./infrastructure/kubernetes"

echo "🚀 Deploying to Kubernetes namespace: $NAMESPACE"

# Create namespace if it doesn't exist
kubectl apply -f "$K8S_DIR/namespace.yaml"

# Deploy infrastructure first
echo "  📦 Deploying databases..."
kubectl apply -f "$K8S_DIR/postgres/" -n "$NAMESPACE"
kubectl apply -f "$K8S_DIR/redis/" -n "$NAMESPACE"

echo "  ⏳ Waiting for databases to be ready..."
kubectl wait --for=condition=ready pod -l app=auth-db -n "$NAMESPACE" --timeout=120s || true
kubectl wait --for=condition=ready pod -l app=product-db -n "$NAMESPACE" --timeout=120s || true
kubectl wait --for=condition=ready pod -l app=order-db -n "$NAMESPACE" --timeout=120s || true
kubectl wait --for=condition=ready pod -l app=redis -n "$NAMESPACE" --timeout=120s || true

# Deploy application services
echo "  🔧 Deploying application services..."
for svc in auth product cart order payment; do
    kubectl apply -f "$K8S_DIR/$svc/" -n "$NAMESPACE"
done

# Deploy gateway
echo "  🌐 Deploying API gateway..."
kubectl apply -f "$K8S_DIR/gateway/" -n "$NAMESPACE"

# Deploy ingress
echo "  🔗 Deploying ingress..."
kubectl apply -f "$K8S_DIR/ingress/" -n "$NAMESPACE"

echo ""
echo "✅ Deployment complete!"
echo "  kubectl get pods -n $NAMESPACE"
