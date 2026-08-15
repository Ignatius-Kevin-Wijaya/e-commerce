#!/usr/bin/env bash
# Auth vus calibration driver (TEMPORARY).
# Sweeps a PEAK_VUS ladder against a fixed-replica config (b1 or b2) and reports
# steady-state p95 + error rate, to locate the B1/B2 validity gate before the
# full ramping-vus migration.
#
# Usage: scripts/calibrate-auth-vus.sh <b1|b2> "80 120 160 200"
set -euo pipefail

NS="ecommerce"
CONFIG="${1:?usage: calibrate-auth-vus.sh <b1|b2> \"VUS LIST\"}"
VUS_LIST="${2:?usage: calibrate-auth-vus.sh <b1|b2> \"VUS LIST\"}"
HOLD="${HOLD_DURATION:-3m}"
CONFIG_DIR="infrastructure/kubernetes/experiments/auth-service"

case "${CONFIG}" in
  b1) CFG_FILE="b1-underprovisioned.yaml"; EXPECT=1 ;;
  b2) CFG_FILE="b2-overprovisioned.yaml";  EXPECT=5 ;;
  *) echo "config must be b1 or b2"; exit 1 ;;
esac

echo "=== Calibrating auth ${CONFIG} (expect ${EXPECT} replicas), HOLD=${HOLD} ==="

# Ensure no autoscalers linger from a prior config
kubectl delete hpa --all -n "${NS}" --ignore-not-found >/dev/null 2>&1 || true
kubectl delete scaledobject --all -n "${NS}" --ignore-not-found >/dev/null 2>&1 || true

# Apply fixed-replica config
kubectl apply -f "${CONFIG_DIR}/${CFG_FILE}" -n "${NS}" >/dev/null
kubectl rollout status deployment/auth-service -n "${NS}" --timeout=180s >/dev/null
echo "auth-service scaled to ${EXPECT} replica(s); waiting 20s to settle..."
sleep 20

# Ensure calib ConfigMap is present
kubectl apply -f infrastructure/kubernetes/load-testing/k6-auth-calib.yaml -n "${NS}" >/dev/null

printf '\n%-8s %-10s %-12s %-10s %-10s\n' "CONFIG" "PEAK_VUS" "p95" "err%" "reqs"
printf '%-8s %-10s %-12s %-10s %-10s\n' "------" "--------" "---" "----" "----"

for VUS in ${VUS_LIST}; do
  JOB="k6-auth-calib-${CONFIG}-${VUS}"
  kubectl delete job "${JOB}" -n "${NS}" --ignore-not-found >/dev/null 2>&1 || true
  sleep 2

  # Clone the calib Job template with patched name + PEAK_VUS env
  kubectl get job k6-auth-calib -n "${NS}" -o json 2>/dev/null \
    | node -e '
      const fs=require("fs");
      const j=JSON.parse(fs.readFileSync(0,"utf8"));
      const name=process.argv[1], vus=process.argv[2], hold=process.argv[3];
      delete j.metadata.resourceVersion; delete j.metadata.uid; delete j.metadata.creationTimestamp;
      delete j.status; delete j.spec.selector;
      if(j.spec.template.metadata) delete j.spec.template.metadata.labels["controller-uid"];
      delete j.spec.template.metadata.labels["batch.kubernetes.io/controller-uid"];
      delete j.spec.template.metadata.labels["job-name"];
      delete j.spec.template.metadata.labels["batch.kubernetes.io/job-name"];
      j.metadata.name=name;
      j.spec.suspend=false; // clones actually run (template is suspended)
      const env=j.spec.template.spec.containers[0].env;
      for(const e of env){ if(e.name==="PEAK_VUS") e.value=String(vus); if(e.name==="HOLD_DURATION") e.value=hold; }
      console.log(JSON.stringify(j));
    ' "${JOB}" "${VUS}" "${HOLD}" \
    | kubectl apply -f - -n "${NS}" >/dev/null

  # Wait for completion (setup + 30s ramp + HOLD + buffer)
  deadline=$(( $(date +%s) + 600 ))
  state="timeout"
  while (( $(date +%s) < deadline )); do
    conds=$(kubectl get job "${JOB}" -n "${NS}" -o jsonpath='{range .status.conditions[*]}{.type}={.status}{" "}{end}' 2>/dev/null || true)
    [[ "${conds}" == *"Complete=True"* ]] && { state="complete"; break; }
    [[ "${conds}" == *"Failed=True"* ]] && { state="failed"; break; }
    sleep 5
  done

  POD=$(kubectl get pods -n "${NS}" -l "job-name=${JOB}" --no-headers -o custom-columns=":metadata.name" | head -1)
  LOG=$(kubectl logs "${POD}" -n "${NS}" 2>/dev/null || true)
  mkdir -p calib-logs
  printf '%s' "${LOG}" > "calib-logs/${CONFIG}-${VUS}.log"

  P95=$(printf '%s' "${LOG}" | grep -E 'http_req_duration' | grep -oE 'p\(95\)=[^ ]+' | head -1 | cut -d= -f2)
  ERR=$(printf '%s' "${LOG}" | grep -E 'http_req_failed' | grep -oE '[0-9]+\.[0-9]+%' | head -1)
  REQS=$(printf '%s' "${LOG}" | grep -E 'http_reqs' | grep -oE ':[ ]*[0-9]+' | head -1 | tr -dc '0-9')

  printf '%-8s %-10s %-12s %-10s %-10s\n' "${CONFIG}" "${VUS}" "${P95:-?(${state})}" "${ERR:-?}" "${REQS:-?}"

  kubectl delete job "${JOB}" -n "${NS}" --ignore-not-found >/dev/null 2>&1 || true
done

echo "=== ${CONFIG} ladder done ==="
