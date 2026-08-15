#!/usr/bin/env bash
# auth_autoscaler_smoke.sh -- focused live smoke for auth-service autoscalers
#
# Intended for post-patch validation before rerunning the full auth H3/K1 blocks:
# - Applies H3 or K1 to auth-service from the repo manifests
# - Runs the in-cluster auth k6 workload against the selected pattern
# - Samples HPA / KEDA / pods during the run
# - Cleans back to the 1-replica baseline afterward
#
# Usage:
#   ./scripts/auth_autoscaler_smoke.sh h3
#   ./scripts/auth_autoscaler_smoke.sh k1
#   LOAD_PATTERN=oscillating ./scripts/auth_autoscaler_smoke.sh h3

set -euo pipefail

MODE="${1:?usage: auth_autoscaler_smoke.sh <h3|k1>}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE="${NAMESPACE:-ecommerce}"
DEPLOYMENT="${DEPLOYMENT:-auth-service}"
LOAD_PATTERN="${LOAD_PATTERN:-spike}"
JOB_NAME="auth-${MODE}-${LOAD_PATTERN}-smoke"
BASE_VUS="${AUTH_BASE_VUS:-2}"
PEAK_VUS="${AUTH_PEAK_VUS:-12}"
AUTH_ME_PERCENT="${AUTH_ME_PERCENT:-70}"
AUTH_LOGIN_PERCENT="${AUTH_LOGIN_PERCENT:-30}"
NUM_TEST_USERS="${NUM_TEST_USERS:-120}"
SAMPLES="${SMOKE_SAMPLES:-12}"
SLEEP_SECONDS="${SMOKE_SAMPLE_SLEEP:-20}"

case "${MODE}" in
  h3)
    APPLY_FILE="${ROOT_DIR}/infrastructure/kubernetes/experiments/auth-service/h3-hpa-custom-metric.yaml"
    HPA_NAME="auth-service-hpa-custom"
    SCALEDOBJECT_NAME=""
    ;;
  k1)
    APPLY_FILE="${ROOT_DIR}/infrastructure/kubernetes/experiments/auth-service/k1-keda.yaml"
    HPA_NAME="keda-hpa-auth-service-keda"
    SCALEDOBJECT_NAME="auth-service-keda"
    ;;
  *)
    echo "Unsupported mode: ${MODE}. Use h3 or k1." >&2
    exit 1
    ;;
esac

case "${LOAD_PATTERN}" in
  gradual|spike|oscillating)
    ;;
  *)
    echo "Unsupported LOAD_PATTERN: ${LOAD_PATTERN}. Use gradual, spike, or oscillating." >&2
    exit 1
    ;;
esac

SCRIPT_CONFIGMAP="k6-auth-script-${LOAD_PATTERN}"
TARGET_URL="http://auth-service.ecommerce.svc.cluster.local:8001"

cleanup() {
  kubectl delete job "${JOB_NAME}" -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
  kubectl delete hpa auth-service-hpa-custom -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
  kubectl delete hpa keda-hpa-auth-service-keda -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
  kubectl delete scaledobject auth-service-keda -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
  kubectl apply -f "${ROOT_DIR}/infrastructure/kubernetes/experiments/auth-service/b1-underprovisioned.yaml" -n "${NAMESPACE}" >/dev/null 2>&1 || true
  kubectl rollout status deployment/"${DEPLOYMENT}" -n "${NAMESPACE}" --timeout=180s >/dev/null 2>&1 || true
}

trap cleanup EXIT

kubectl get configmap "${SCRIPT_CONFIGMAP}" -n "${NAMESPACE}" >/dev/null

cleanup
kubectl apply -f "${ROOT_DIR}/infrastructure/kubernetes/experiments/auth-service/b1-underprovisioned.yaml" -n "${NAMESPACE}" >/dev/null
kubectl rollout status deployment/"${DEPLOYMENT}" -n "${NAMESPACE}" --timeout=180s >/dev/null
kubectl apply -f "${APPLY_FILE}" -n "${NAMESPACE}" >/dev/null

cat <<YAML | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB_NAME}
  namespace: ${NAMESPACE}
spec:
  backoffLimit: 0
  template:
    metadata:
      labels:
        app: k6
        target: auth-service
    spec:
      restartPolicy: Never
      containers:
        - name: k6
          image: grafana/k6:latest
          command: ["k6", "run", "--out", "json=/results/results.json", "/scripts/load-test.js"]
          env:
            - name: TARGET_URL
              value: "${TARGET_URL}"
            - name: BASE_VUS
              value: "${BASE_VUS}"
            - name: PEAK_VUS
              value: "${PEAK_VUS}"
            - name: AUTH_ME_PERCENT
              value: "${AUTH_ME_PERCENT}"
            - name: AUTH_LOGIN_PERCENT
              value: "${AUTH_LOGIN_PERCENT}"
            - name: NUM_TEST_USERS
              value: "${NUM_TEST_USERS}"
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
YAML

echo "=== ${MODE} auth smoke start ==="
echo "pattern=${LOAD_PATTERN} base_vus=${BASE_VUS} peak_vus=${PEAK_VUS} me=${AUTH_ME_PERCENT}% login=${AUTH_LOGIN_PERCENT}% users=${NUM_TEST_USERS}"

for sample in $(seq 1 "${SAMPLES}"); do
  echo "=== ${MODE} sample ${sample}/${SAMPLES} ==="
  kubectl get deployment "${DEPLOYMENT}" -n "${NAMESPACE}"
  if [[ -n "${SCALEDOBJECT_NAME}" ]]; then
    kubectl get scaledobject "${SCALEDOBJECT_NAME}" -n "${NAMESPACE}" || true
  fi
  kubectl get hpa "${HPA_NAME}" -n "${NAMESPACE}" || true
  kubectl top pod -l app="${DEPLOYMENT}" -n "${NAMESPACE}" --no-headers 2>/dev/null || true
  sleep "${SLEEP_SECONDS}"
done

echo "=== ${MODE} final job status ==="
kubectl get job "${JOB_NAME}" -n "${NAMESPACE}" || true
kubectl get pods -n "${NAMESPACE}" -l job-name="${JOB_NAME}" || true
