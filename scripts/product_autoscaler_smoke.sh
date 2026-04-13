#!/usr/bin/env bash
# product_autoscaler_smoke.sh — quick live smoke for product-service autoscalers
#
# Intended for calibration work before the full thesis pilot:
# - Applies H1, H2, H3, or K1 to product-service
# - Runs the in-cluster product k6 workload against /products
# - Samples deployment/HPA/pod CPU during the spike
# - Cleans up back to 1 replica afterward
#
# Usage:
#   ./scripts/product_autoscaler_smoke.sh h1
#   ./scripts/product_autoscaler_smoke.sh h3
#   ./scripts/product_autoscaler_smoke.sh k1
#   LOAD_PATTERN=gradual PRODUCT_BASE_RPS=20 PRODUCT_PEAK_RPS=200 \
#     ./scripts/product_autoscaler_smoke.sh h2
set -euo pipefail

MODE="${1:?usage: product_autoscaler_smoke.sh <h1|h2|h3|k1>}"
NAMESPACE="${NAMESPACE:-ecommerce}"
DEPLOYMENT="${DEPLOYMENT:-product-service}"
LOAD_PATTERN="${LOAD_PATTERN:-spike}"
SCRIPT_CONFIGMAP="k6-script-${LOAD_PATTERN}"
JOB_NAME="product-${MODE}-smoke"
BASE_RPS="${PRODUCT_BASE_RPS:-20}"
PEAK_RPS="${PRODUCT_PEAK_RPS:-200}"
PAGE_SIZE="${PRODUCT_PAGE_SIZE:-100}"
MAX_PAGE="${PRODUCT_MAX_PAGE:-12}"
SEARCH_TERMS="${PRODUCT_SEARCH_TERMS:-Laptop,Phone,Camera,Headphones,Keyboard,Monitor,Speaker,Charger}"
REQUEST_RATE_THRESHOLD="${PRODUCT_REQUEST_RATE_THRESHOLD:-50}"
SAMPLES="${SMOKE_SAMPLES:-15}"
SLEEP_SECONDS="${SMOKE_SAMPLE_SLEEP:-20}"

case "${MODE}" in
  h1)
    HPA_NAME="product-service-hpa-default"
    ;;
  h2)
    HPA_NAME="product-service-hpa-tuned"
    ;;
  h3)
    HPA_NAME="product-service-hpa-custom"
    ;;
  k1)
    HPA_NAME="keda-hpa-product-service-keda"
    ;;
  *)
    echo "❌ Unsupported mode: ${MODE}. Use h1, h2, h3, or k1." >&2
    exit 1
    ;;
esac

cleanup() {
  kubectl delete job "${JOB_NAME}" -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
  kubectl delete hpa "${HPA_NAME}" -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
  kubectl delete scaledobject product-service-keda -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
  kubectl scale deployment/"${DEPLOYMENT}" --replicas=1 -n "${NAMESPACE}" >/dev/null 2>&1 || true
  kubectl rollout status deployment/"${DEPLOYMENT}" -n "${NAMESPACE}" --timeout=180s >/dev/null 2>&1 || true
}

trap cleanup EXIT

kubectl get configmap "${SCRIPT_CONFIGMAP}" -n "${NAMESPACE}" >/dev/null

cleanup

if [[ "${MODE}" == "h1" ]]; then
  cat <<YAML | kubectl apply -f -
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: product-service-hpa-default
  namespace: ${NAMESPACE}
  labels:
    experiment: h1-hpa-default
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: product-service
  minReplicas: 1
  maxReplicas: 5
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
YAML
elif [[ "${MODE}" == "h2" ]]; then
  cat <<YAML | kubectl apply -f -
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: product-service-hpa-tuned
  namespace: ${NAMESPACE}
  labels:
    experiment: h2-hpa-tuned
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: product-service
  minReplicas: 1
  maxReplicas: 5
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 50
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Pods
          value: 5
          periodSeconds: 15
    scaleDown:
      stabilizationWindowSeconds: 30
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
YAML
elif [[ "${MODE}" == "h3" ]]; then
  cat <<YAML | kubectl apply -f -
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: product-service-hpa-custom
  namespace: ${NAMESPACE}
  labels:
    experiment: h3-hpa-custom-metric
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: product-service
  minReplicas: 1
  maxReplicas: 5
  metrics:
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "${REQUEST_RATE_THRESHOLD}"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Pods
          value: 5
          periodSeconds: 15
    scaleDown:
      stabilizationWindowSeconds: 30
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
YAML
else
  cat <<YAML | kubectl apply -f -
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: product-service-keda
  namespace: ${NAMESPACE}
  labels:
    experiment: k1-keda
spec:
  scaleTargetRef:
    name: product-service
  minReplicaCount: 1
  maxReplicaCount: 5
  cooldownPeriod: 30
  pollingInterval: 15
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus.monitoring.svc.cluster.local:9090
        metricName: http_requests_per_second
        query: |
          sum(rate(http_requests_total{job="product-service"}[1m]))
        threshold: "${REQUEST_RATE_THRESHOLD}"
YAML
fi

cat <<YAML | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB_NAME}
  namespace: ${NAMESPACE}
spec:
  template:
    metadata:
      labels:
        app: k6
        target: product-service
    spec:
      restartPolicy: Never
      containers:
        - name: k6
          image: grafana/k6:latest
          command: ["k6", "run", "--out", "json=/results/results.json", "/scripts/load-test.js"]
          env:
            - name: TARGET_URL
              value: "http://product-service.ecommerce.svc.cluster.local:8002"
            - name: TARGET_ENDPOINT
              value: "/products"
            - name: BASE_RPS
              value: "${BASE_RPS}"
            - name: PEAK_RPS
              value: "${PEAK_RPS}"
            - name: PRODUCT_PAGE_SIZE
              value: "${PAGE_SIZE}"
            - name: PRODUCT_MAX_PAGE
              value: "${MAX_PAGE}"
            - name: PRODUCT_SEARCH_TERMS
              value: "${SEARCH_TERMS}"
            - name: INTERNAL_GATEWAY_SECRET
              valueFrom:
                secretKeyRef:
                  name: gateway-secrets
                  key: internal-gateway-secret
          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "1500m"
              memory: "1Gi"
          volumeMounts:
            - name: k6-script
              mountPath: /scripts
            - name: k6-results
              mountPath: /results
      volumes:
        - name: k6-script
          configMap:
            name: ${SCRIPT_CONFIGMAP}
        - name: k6-results
          emptyDir: {}
  backoffLimit: 0
YAML

echo "=== ${MODE} smoke start ==="
echo "pattern=${LOAD_PATTERN} base_rps=${BASE_RPS} peak_rps=${PEAK_RPS} page_size=${PAGE_SIZE} max_page=${MAX_PAGE}"

for sample in $(seq 1 "${SAMPLES}"); do
  echo "=== ${MODE} sample ${sample}/${SAMPLES} ==="
  kubectl get deployment "${DEPLOYMENT}" -n "${NAMESPACE}"
  if [[ "${MODE}" == "k1" ]]; then
    kubectl get scaledobject product-service-keda -n "${NAMESPACE}" || true
  fi
  kubectl get hpa "${HPA_NAME}" -n "${NAMESPACE}" || true
  kubectl top pod -l app="${DEPLOYMENT}" -n "${NAMESPACE}" --no-headers 2>/dev/null || true
  sleep "${SLEEP_SECONDS}"
done

echo "=== ${MODE} final job status ==="
kubectl get job "${JOB_NAME}" -n "${NAMESPACE}" || true
kubectl get pods -n "${NAMESPACE}" -l job-name="${JOB_NAME}" || true
