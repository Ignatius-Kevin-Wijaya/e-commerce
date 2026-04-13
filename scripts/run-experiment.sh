#!/usr/bin/env bash
# ============================================================================
# Thesis Experiment Runner — Fully Automated
# ============================================================================
#
# Automates the 180-run experiment:
#   6 configs × 3 load patterns × 5 repetitions × 2 services = 180 runs
#
# Protocol per run (from thesis_blueprint.md Section 6):
#   1. Cluster state reset — delete autoscaler, set replicas=1, wait 60s
#   2. Apply configuration — deploy HPA/KEDA/fixed
#   3. Wait for stabilization — 30s for metrics to baseline
#   4. Run k6 load test — ~12 min (2 warm-up + 7 test + 3 cooldown)
#   5. Export data — k6 JSON + Prometheus metrics
#   6. Cleanup
#
# Usage:
#   chmod +x scripts/run-experiment.sh
#   ./scripts/run-experiment.sh                     # Run ALL 180 experiments
#   ./scripts/run-experiment.sh --service product   # Only product-service (90 runs)
#   ./scripts/run-experiment.sh --resume            # Resume from last completed run
#   ./scripts/run-experiment.sh --dry-run           # Print plan without executing
#
# ============================================================================

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────

NAMESPACE="ecommerce"
MONITORING_NS="monitoring"
RESULTS_BASE_DIR="$(pwd)/experiment-results"
LOG_FILE="${RESULTS_BASE_DIR}/experiment.log"
STATE_FILE="${RESULTS_BASE_DIR}/.experiment-state"
PROM_URL="http://prometheus.${MONITORING_NS}.svc.cluster.local:9090"

# Experiment matrix
SERVICES=("product-service" "auth-service")
CONFIGS=("b1" "b2" "h1" "h2" "h3" "k1")
PATTERNS=("gradual" "spike" "oscillating")
REPETITIONS=5

# Timing (seconds)
RESET_WAIT=120       # Wait after cleanup for stabilization
STABILIZE_WAIT=90    # Wait after config apply for metrics baseline
K6_TIMEOUT=900       # 15 min max per k6 job (12 min test + buffer)
EXPORT_WAIT=180       # Wait before data export (3 mins for cooldown capture)

# Load profile knobs (override via env for calibration ladders)
PRODUCT_BASE_RPS="${PRODUCT_BASE_RPS:-20}"
PRODUCT_PEAK_RPS="${PRODUCT_PEAK_RPS:-200}"
PRODUCT_PAGE_SIZE="${PRODUCT_PAGE_SIZE:-100}"
PRODUCT_MAX_PAGE="${PRODUCT_MAX_PAGE:-12}"
PRODUCT_SEARCH_TERMS="${PRODUCT_SEARCH_TERMS:-Laptop,Phone,Camera,Headphones,Keyboard,Monitor,Speaker,Charger}"

AUTH_BASE_RPS="${AUTH_BASE_RPS:-10}"
AUTH_PEAK_RPS="${AUTH_PEAK_RPS:-40}"
AUTH_ME_PERCENT="${AUTH_ME_PERCENT:-70}"
AUTH_LOGIN_PERCENT="${AUTH_LOGIN_PERCENT:-30}"
NUM_TEST_USERS="${NUM_TEST_USERS:-120}"

# ── Color Output ──────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ── Helper Functions ──────────────────────────────────────────────────────────

log() {
  local timestamp
  timestamp=$(date '+%Y-%m-%d %H:%M:%S')
  echo -e "${CYAN}[${timestamp}]${NC} $*" | tee -a "${LOG_FILE}" >&2
}

log_success() { log "${GREEN}✅ $*${NC}"; }
log_warn()    { log "${YELLOW}⚠️  $*${NC}"; }
log_error()   { log "${RED}❌ $*${NC}"; }
log_step()    { log "${BLUE}── $*${NC}"; }

# Get run ID: service_config_pattern_repN (e.g., product-service_h1_gradual_rep3)
run_id() {
  local service=$1 config=$2 pattern=$3 rep=$4
  echo "${service}_${config}_${pattern}_rep${rep}"
}

# Check if a run is already completed
is_completed() {
  local rid=$1
  [[ -f "${STATE_FILE}" ]] && grep -q "^DONE:${rid}$" "${STATE_FILE}"
}

# Mark run as completed
mark_completed() {
  local rid=$1
  echo "DONE:${rid}" >> "${STATE_FILE}"
}

# Get total and completed counts
get_progress() {
  local total=$1
  local completed=0
  [[ -f "${STATE_FILE}" ]] && completed=$(grep -c "^DONE:" "${STATE_FILE}" 2>/dev/null || echo 0)
  echo "${completed}/${total}"
}

# Calculate ETA
calc_eta() {
  local remaining=$1 avg_seconds=$2
  local total_seconds=$((remaining * avg_seconds))
  local hours=$((total_seconds / 3600))
  local minutes=$(((total_seconds % 3600) / 60))
  echo "${hours}h ${minutes}m"
}

# ── Experiment Config Paths ───────────────────────────────────────────────────

get_config_dir() {
  local service=$1
  echo "infrastructure/kubernetes/experiments/${service}"
}

get_k6_job_file() {
  local service=$1
  if [[ "${service}" == "product-service" ]]; then
    echo "infrastructure/kubernetes/load-testing/k6-job.yaml"
  else
    echo "infrastructure/kubernetes/load-testing/k6-auth-job.yaml"
  fi
}

# Create a k6 job by reading the local YAML template and patching the name
# plus per-service calibration env vars.
create_k6_job_from_yaml() {
  local yaml_file=$1 template_name=$2 new_name=$3 service=$4
  K6_YAML_FILE="${yaml_file}" \
  K6_TEMPLATE_NAME="${template_name}" \
  K6_NEW_NAME="${new_name}" \
  K6_SERVICE="${service}" \
  PRODUCT_BASE_RPS="${PRODUCT_BASE_RPS}" \
  PRODUCT_PEAK_RPS="${PRODUCT_PEAK_RPS}" \
  PRODUCT_PAGE_SIZE="${PRODUCT_PAGE_SIZE}" \
  PRODUCT_MAX_PAGE="${PRODUCT_MAX_PAGE}" \
  PRODUCT_SEARCH_TERMS="${PRODUCT_SEARCH_TERMS}" \
  AUTH_BASE_RPS="${AUTH_BASE_RPS}" \
  AUTH_PEAK_RPS="${AUTH_PEAK_RPS}" \
  AUTH_ME_PERCENT="${AUTH_ME_PERCENT}" \
  AUTH_LOGIN_PERCENT="${AUTH_LOGIN_PERCENT}" \
  NUM_TEST_USERS="${NUM_TEST_USERS}" \
  python3 - <<'PYEOF'
import os
import sys

try:
    import yaml
except ImportError:
    sys.exit(1)


def set_env(env_list, name, value):
    for item in env_list:
        if item.get("name") == name:
            item["value"] = str(value)
            item.pop("valueFrom", None)
            return
    env_list.append({"name": name, "value": str(value)})


yaml_file = os.environ["K6_YAML_FILE"]
template_name = os.environ["K6_TEMPLATE_NAME"]
new_name = os.environ["K6_NEW_NAME"]
service = os.environ["K6_SERVICE"]

with open(yaml_file) as f:
    docs = list(yaml.safe_load_all(f))

for doc in docs:
    if doc and doc.get("kind") == "Job" and doc.get("metadata", {}).get("name") == template_name:
        doc["metadata"]["name"] = new_name
        for field in ("resourceVersion", "uid", "creationTimestamp", "generation", "selfLink", "annotations"):
            doc["metadata"].pop(field, None)
        doc.pop("status", None)

        container = doc["spec"]["template"]["spec"]["containers"][0]
        env_list = container.setdefault("env", [])

        if service == "product-service":
            set_env(env_list, "BASE_RPS", os.environ["PRODUCT_BASE_RPS"])
            set_env(env_list, "PEAK_RPS", os.environ["PRODUCT_PEAK_RPS"])
            set_env(env_list, "PRODUCT_PAGE_SIZE", os.environ["PRODUCT_PAGE_SIZE"])
            set_env(env_list, "PRODUCT_MAX_PAGE", os.environ["PRODUCT_MAX_PAGE"])
            set_env(env_list, "PRODUCT_SEARCH_TERMS", os.environ["PRODUCT_SEARCH_TERMS"])
        else:
            set_env(env_list, "BASE_RPS", os.environ["AUTH_BASE_RPS"])
            set_env(env_list, "PEAK_RPS", os.environ["AUTH_PEAK_RPS"])
            set_env(env_list, "AUTH_ME_PERCENT", os.environ["AUTH_ME_PERCENT"])
            set_env(env_list, "AUTH_LOGIN_PERCENT", os.environ["AUTH_LOGIN_PERCENT"])
            set_env(env_list, "NUM_TEST_USERS", os.environ["NUM_TEST_USERS"])

        print(yaml.dump(doc, default_flow_style=False, sort_keys=False))
        sys.exit(0)

print(f"ERROR: Job template '{template_name}' not found in {yaml_file}", file=sys.stderr)
sys.exit(1)
PYEOF
}

get_k6_job_name() {
  local service=$1 pattern=$2
  if [[ "${service}" == "product-service" ]]; then
    echo "k6-load-test-${pattern}"
  else
    echo "k6-auth-test-${pattern}"
  fi
}

# Map config IDs to YAML filenames
config_file() {
  local config=$1
  case "${config}" in
    b1) echo "b1-underprovisioned.yaml" ;;
    b2) echo "b2-overprovisioned.yaml" ;;
    h1) echo "h1-hpa-default.yaml" ;;
    h2) echo "h2-hpa-tuned.yaml" ;;
    h3) echo "h3-hpa-custom-metric.yaml" ;;
    k1) echo "k1-keda.yaml" ;;
  esac
}

# Map config IDs to types for cleanup
config_type() {
  local config=$1
  case "${config}" in
    b1|b2) echo "deployment" ;;
    h1|h2|h3) echo "hpa" ;;
    k1) echo "keda" ;;
  esac
}

expected_replicas() {
  local config=$1
  if [[ "${config}" == "b2" ]]; then
    echo 5
  else
    echo 1
  fi
}

service_port() {
  local service=$1
  case "${service}" in
    auth-service) echo 8001 ;;
    product-service) echo 8002 ;;
    cart-service) echo 8003 ;;
    order-service) echo 8004 ;;
    payment-service) echo 8005 ;;
    api-gateway) echo 8080 ;;
    *)
      log_error "Unknown service port mapping for ${service}"
      return 1
      ;;
  esac
}

service_base_rps() {
  local service=$1
  if [[ "${service}" == "product-service" ]]; then
    echo "${PRODUCT_BASE_RPS}"
  else
    echo "${AUTH_BASE_RPS}"
  fi
}

service_peak_rps() {
  local service=$1
  if [[ "${service}" == "product-service" ]]; then
    echo "${PRODUCT_PEAK_RPS}"
  else
    echo "${AUTH_PEAK_RPS}"
  fi
}

wait_for_expected_replicas() {
  local service=$1 expected=$2 timeout=${3:-180} phase=${4:-"verification"}
  local deadline=$((SECONDS + timeout))

  while (( SECONDS < deadline )); do
    local spec_replicas ready_replicas available_replicas bad_pods
    spec_replicas=$(kubectl get deployment "${service}" -n "${NAMESPACE}" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo 0)
    ready_replicas=$(kubectl get deployment "${service}" -n "${NAMESPACE}" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo 0)
    available_replicas=$(kubectl get deployment "${service}" -n "${NAMESPACE}" -o jsonpath='{.status.availableReplicas}' 2>/dev/null || echo 0)
    bad_pods=$(kubectl get pods -n "${NAMESPACE}" -l "app=${service}" --no-headers 2>/dev/null | awk 'NF > 0 && $3 !~ /Running|Completed/ {count++} END {print count+0}')

    if [[ "${spec_replicas}" == "${expected}" && "${ready_replicas:-0}" == "${expected}" && "${available_replicas:-0}" == "${expected}" && "${bad_pods}" == "0" ]]; then
      log_success "${service} reached ${expected}/${expected} ready replicas during ${phase}"
      return 0
    fi

    sleep 5
  done

  log_error "${service} failed ${phase}: expected ${expected} ready replicas"
  kubectl get deployment "${service}" -n "${NAMESPACE}" -o wide >&2 || true
  kubectl get pods -n "${NAMESPACE}" -l "app=${service}" -o wide >&2 || true
  return 1
}

delete_k6_jobs() {
  log_step "Deleting leftover k6 jobs..."
  kubectl delete job -n "${NAMESPACE}" -l app=k6 --ignore-not-found &>/dev/null || true
  kubectl wait --for=delete job -n "${NAMESPACE}" -l app=k6 --timeout=120s &>/dev/null || true
}

apply_k6_configmaps() {
  log_step "Refreshing k6 ConfigMaps from local manifests..."

  local k6_files=(
    "infrastructure/kubernetes/load-testing/k6-job.yaml"
    "infrastructure/kubernetes/load-testing/k6-auth-job.yaml"
  )

  local k6_file
  for k6_file in "${k6_files[@]}"; do
    K6_YAML_FILE="${k6_file}" python3 - <<'PYEOF' | kubectl apply -f - -n "${NAMESPACE}" >&2
import os
from pathlib import Path

content = Path(os.environ["K6_YAML_FILE"]).read_text()
docs = [doc.strip() for doc in content.split("---") if doc.strip()]

for doc in docs:
    if "\nkind: ConfigMap" in f"\n{doc}\n":
        print("---")
        print(doc)
PYEOF
  done
}

# ── Cluster Reset ─────────────────────────────────────────────────────────────

cleanup_autoscalers() {
  local service=$1
  log_step "Cleaning up all autoscalers for ${service}..."

  local hpas=(
    "${service}-hpa-default"
    "${service}-hpa-tuned"
    "${service}-hpa-custom"
    "keda-hpa-${service}-keda"
  )
  local hpa
  for hpa in "${hpas[@]}"; do
    kubectl delete hpa "${hpa}" -n "${NAMESPACE}" --ignore-not-found &>/dev/null || true
    kubectl wait --for=delete "hpa/${hpa}" -n "${NAMESPACE}" --timeout=60s &>/dev/null || true
  done

  kubectl delete scaledobject "${service}-keda" -n "${NAMESPACE}" --ignore-not-found &>/dev/null || true
  kubectl wait --for=delete "scaledobject/${service}-keda" -n "${NAMESPACE}" --timeout=60s &>/dev/null || true

  # Reset deployment to 1 replica
  kubectl scale deployment "${service}" -n "${NAMESPACE}" --replicas=1 &>/dev/null || true

  log_step "Waiting for ${service} to return to the 1-replica baseline..."
  kubectl rollout status deployment/"${service}" -n "${NAMESPACE}" --timeout=180s &>/dev/null
  wait_for_expected_replicas "${service}" 1 180 "cleanup"
}

reset_cluster_state() {
  local service=$1
  log_step "Resetting cluster state for ${service}..."

  cleanup_autoscalers "${service}"
  delete_k6_jobs

  log_step "Waiting ${RESET_WAIT}s for cluster stabilization..."
  sleep "${RESET_WAIT}"

  wait_for_expected_replicas "${service}" 1 180 "post-reset stabilization"

  log_success "Cluster state reset complete for ${service}"
}

# ── Apply Experiment Configuration ────────────────────────────────────────────

apply_config() {
  local service=$1 config=$2
  local config_dir
  config_dir=$(get_config_dir "${service}")
  local config_filename
  config_filename=$(config_file "${config}")
  local config_path="${config_dir}/${config_filename}"
  local ctype
  ctype=$(config_type "${config}")
  local expected
  expected=$(expected_replicas "${config}")

  log_step "Applying configuration: ${config} (${config_filename}) for ${service}"

  case "${ctype}" in
    deployment)
      # B1/B2: Apply the deployment override (replicas:1 or replicas:5)
      kubectl apply -f "${config_path}" -n "${NAMESPACE}" &>/dev/null
      kubectl rollout status deployment/"${service}" -n "${NAMESPACE}" --timeout=180s &>/dev/null
      ;;
    hpa)
      # H1/H2/H3: First ensure replicas=1, then apply HPA
      local b1_path="${config_dir}/b1-underprovisioned.yaml"
      kubectl apply -f "${b1_path}" -n "${NAMESPACE}" &>/dev/null
      kubectl rollout status deployment/"${service}" -n "${NAMESPACE}" --timeout=180s &>/dev/null
      kubectl apply -f "${config_path}" -n "${NAMESPACE}" &>/dev/null
      ;;
    keda)
      # K1: First ensure replicas=1, then apply ScaledObject
      local b1_path="${config_dir}/b1-underprovisioned.yaml"
      kubectl apply -f "${b1_path}" -n "${NAMESPACE}" &>/dev/null
      kubectl rollout status deployment/"${service}" -n "${NAMESPACE}" --timeout=180s &>/dev/null
      kubectl apply -f "${config_path}" -n "${NAMESPACE}" &>/dev/null
      ;;
  esac

  wait_for_expected_replicas "${service}" "${expected}" 180 "config apply (${config})"

  log_step "Waiting ${STABILIZE_WAIT}s for metrics to baseline..."
  sleep "${STABILIZE_WAIT}"
  wait_for_expected_replicas "${service}" "${expected}" 180 "post-config stabilization (${config})"

  log_success "Configuration ${config} applied for ${service}"
}

# ── Pre-Flight Readiness Check ────────────────────────────────────────────────

verify_readiness() {
  local service=$1
  local port
  port=$(service_port "${service}")
  log_step "Pre-flight: verifying ${service} is ready on /ready..."

  kubectl rollout status deployment/"${service}" -n "${NAMESPACE}" --timeout=180s &>/dev/null

  local svc_healthy=false
  local retries=0
  local max_retries=12
  while [[ ${retries} -lt ${max_retries} ]]; do
    if kubectl exec -n "${NAMESPACE}" deploy/"${service}" -- \
        python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:${port}/ready', timeout=5)" &>/dev/null; then
      svc_healthy=true
      break
    fi
    retries=$((retries + 1))
    log_step "  ${service} /ready check attempt ${retries}/${max_retries}..."
    sleep 5
  done

  if ! ${svc_healthy}; then
    log_error "${service} failed /ready verification after ${max_retries} attempts"
    kubectl get pods -n "${NAMESPACE}" -l "app=${service}" -o wide >&2 || true
    return 1
  fi

  log_success "Pre-flight passed: ${service} is ready"
}

# ── Run k6 Load Test ──────────────────────────────────────────────────────────

run_k6_test() {
  local service=$1 pattern=$2 run_id=$3
  local job_base_name
  job_base_name=$(get_k6_job_name "${service}" "${pattern}")
  local job_run_name="${job_base_name}-${run_id}"

  # k6 job names must be DNS-compatible (lowercase, max 63 chars, only a-z0-9-)
  job_run_name=$(echo "${job_run_name}" | tr '_' '-' | cut -c1-63)

  log_step "Starting k6 load test: ${job_run_name} (pattern: ${pattern})"

  # Delete any previous run with same name
  kubectl delete job "${job_run_name}" -n "${NAMESPACE}" --ignore-not-found &>/dev/null || true
  sleep 2

  # Create the job by reading the local YAML template and patching the name.
  # This is more reliable than `kubectl create job --from=job/` which fails
  # when the source Job object has already completed.
  local k6_yaml_file
  k6_yaml_file=$(get_k6_job_file "${service}")
  local job_created=false

  if create_k6_job_from_yaml "${k6_yaml_file}" "${job_base_name}" "${job_run_name}" "${service}" \
      | kubectl apply -f - -n "${NAMESPACE}" >&2; then
    job_created=true
  else
    log_warn "python3+pyyaml not available, falling back to sed-based patching..."
    # Fallback: use sed to patch the name inline from the YAML file
    python3 -c "
import re, sys
with open('${k6_yaml_file}') as f: content = f.read()
docs = content.split('---')
for doc in docs:
    if 'kind: Job' in doc and 'name: ${job_base_name}' in doc:
        doc = re.sub(r'(name: )${job_base_name}', r'\\g<1>${job_run_name}', doc, count=1)
        print('---')
        print(doc)
        sys.exit(0)
" | kubectl apply -f - -n "${NAMESPACE}" >&2 && job_created=true
  fi

  if ! ${job_created}; then
    log_error "Failed to create k6 job ${job_run_name}. Skipping this run."
    CURRENT_JOB_NAME="${job_run_name}"
    return 1
  fi

  # Wait for job to complete
  log_step "Waiting for k6 job to complete (timeout: ${K6_TIMEOUT}s)..."
  local start_time
  start_time=$(date +%s)

  if kubectl wait --for=condition=complete job/"${job_run_name}" -n "${NAMESPACE}" --timeout="${K6_TIMEOUT}s" 2>/dev/null; then
    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))
    log_success "k6 job completed in ${duration}s"
  else
    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))
    log_warn "k6 job did not complete cleanly after ${duration}s (may have failed threshold checks — this is expected data)"
  fi

  CURRENT_JOB_NAME="${job_run_name}"
}

# ── Data Export ───────────────────────────────────────────────────────────────

export_k6_results() {
  local job_name=$1 results_dir=$2
  log_step "Exporting k6 results..."

  # Get the pod name for this job
  local pod_name
  pod_name=$(kubectl get pods -n "${NAMESPACE}" -l "job-name=${job_name}" --no-headers -o custom-columns=":metadata.name" | head -1)

  if [[ -n "${pod_name}" ]]; then
    # Copy results JSON from pod
    kubectl cp "${NAMESPACE}/${pod_name}:/results/results.json" "${results_dir}/k6-results.json" 2>/dev/null || log_warn "Could not copy k6 JSON results"

    # Also capture k6 pod logs (contains summary metrics)
    kubectl logs "${pod_name}" -n "${NAMESPACE}" > "${results_dir}/k6-output.log" 2>/dev/null || log_warn "Could not capture k6 logs"

    log_success "k6 results exported to ${results_dir}/"
  else
    log_warn "No k6 pod found for job ${job_name}"
  fi
}

export_prometheus_metrics() {
  local service=$1 results_dir=$2
  local prom_pod
  prom_pod=$(kubectl get pods -n "${MONITORING_NS}" -l app=prometheus --no-headers -o custom-columns=":metadata.name" | head -1)

  if [[ -z "${prom_pod}" ]]; then
    log_warn "Prometheus pod not found — skipping metric export"
    return
  fi

  log_step "Exporting Prometheus metrics..."

  local end_time
  end_time=$(date +%s)
  local start_time=$((end_time - 1200))  # 20 min window to capture pre-warmup and post-cooldown

  # Export key metrics via Prometheus API (using kubectl exec to avoid port-forward)
  local queries=(
    "rate(http_requests_total{job=\"${service}\"}[1m])|http_requests_rate"
    "histogram_quantile(0.95,rate(http_request_duration_seconds_bucket{job=\"${service}\"}[1m]))|p95_latency"
    "kube_deployment_status_replicas{deployment=\"${service}\"}|replica_count"
    "kube_deployment_status_replicas_ready{deployment=\"${service}\"}|replica_ready_count"
    "rate(container_cpu_usage_seconds_total{container=\"${service}\"}[1m])|cpu_usage"
  )

  for query_pair in "${queries[@]}"; do
    local query="${query_pair%%|*}"
    local name="${query_pair##*|}"
    local encoded_query
    encoded_query=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${query}'))" 2>/dev/null || echo "${query}")

    kubectl exec -n "${MONITORING_NS}" "${prom_pod}" -- \
      wget -q -O - "http://localhost:9090/api/v1/query_range?query=${encoded_query}&start=${start_time}&end=${end_time}&step=15" \
      > "${results_dir}/prom_${name}.json" 2>/dev/null || log_warn "Failed to export ${name}"
  done

  # Export scaling events (capture all namespace events to ensure HPA/KEDA objects are included)
  kubectl get events -n "${NAMESPACE}" --sort-by='.lastTimestamp' > "${results_dir}/k8s-events.txt" 2>/dev/null || true

  # Export HPA/KEDA status
  kubectl get hpa -n "${NAMESPACE}" -o yaml > "${results_dir}/hpa-status.yaml" 2>/dev/null || true
  kubectl get scaledobject -n "${NAMESPACE}" -o yaml > "${results_dir}/keda-status.yaml" 2>/dev/null || true

  # Export pod states
  kubectl get pods -n "${NAMESPACE}" -l "app=${service}" -o wide > "${results_dir}/pod-status.txt" 2>/dev/null || true

  log_success "Prometheus metrics exported to ${results_dir}/"
}

# ── Single Run ────────────────────────────────────────────────────────────────

execute_single_run() {
  local service=$1 config=$2 pattern=$3 rep=$4
  local rid
  rid=$(run_id "${service}" "${config}" "${pattern}" "${rep}")

  # Write to a temporary directory first so interrupted runs cannot corrupt
  # a previously valid result set for the same run id.
  local final_results_dir="${RESULTS_BASE_DIR}/${service}/${config}/${pattern}/rep${rep}"
  local temp_results_root="${RESULTS_BASE_DIR}/.tmp"
  local results_dir="${temp_results_root}/${rid}-$(date +%s)"
  mkdir -p "${results_dir}"

  # Record start time
  local run_start
  run_start=$(date +%s)
  date -Iseconds > "${results_dir}/start_time.txt"

  log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  log "  RUN: ${rid}"
  log "  Service: ${service} | Config: ${config} | Pattern: ${pattern} | Rep: ${rep}"
  log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  # Step 1: Reset cluster state
  reset_cluster_state "${service}"

  # Step 2: Apply experiment configuration
  apply_config "${service}" "${config}"

  # Step 2.5: Pre-flight readiness check
  verify_readiness "${service}"

  # Step 3: Run k6 load test
  run_k6_test "${service}" "${pattern}" "${rid}"
  local job_name="${CURRENT_JOB_NAME}"

  # Step 4: Wait for metrics to flush
  log_step "Waiting ${EXPORT_WAIT}s before data export..."
  sleep "${EXPORT_WAIT}"

  # Step 5: Export data
  export_k6_results "${job_name}" "${results_dir}"
  export_prometheus_metrics "${service}" "${results_dir}"

  # Step 6: Record metadata
  local run_end
  run_end=$(date +%s)
  local run_duration=$((run_end - run_start))
  date -Iseconds > "${results_dir}/end_time.txt"

  cat > "${results_dir}/metadata.json" <<EOF
{
  "run_id": "${rid}",
  "service": "${service}",
  "config": "${config}",
  "pattern": "${pattern}",
  "repetition": ${rep},
  "start_epoch": ${run_start},
  "end_epoch": ${run_end},
  "duration_seconds": ${run_duration},
  "k6_job_name": "${job_name}",
  "target_url": "http://${service}.${NAMESPACE}.svc.cluster.local:$(service_port "${service}")",
  "load_profile": {
    "version": "recovery-v2",
    "base_rps": $(service_base_rps "${service}"),
    "peak_rps": $(service_peak_rps "${service}")$(if [[ "${service}" == "product-service" ]]; then
      printf ',\n    "page_size": %s,\n    "max_page": %s,\n    "search_terms": "%s"' "${PRODUCT_PAGE_SIZE}" "${PRODUCT_MAX_PAGE}" "${PRODUCT_SEARCH_TERMS}"
    else
      printf ',\n    "auth_me_percent": %s,\n    "auth_login_percent": %s,\n    "num_test_users": %s' "${AUTH_ME_PERCENT}" "${AUTH_LOGIN_PERCENT}" "${NUM_TEST_USERS}"
    fi)
  },
  "timestamp": "$(date -Iseconds)"
}
EOF

  mkdir -p "$(dirname "${final_results_dir}")"
  rm -rf "${final_results_dir}"
  mv "${results_dir}" "${final_results_dir}"
  results_dir="${final_results_dir}"

  # Step 7: Cleanup k6 job
  kubectl delete job "${job_name}" -n "${NAMESPACE}" --ignore-not-found 2>/dev/null || true

  # Mark as completed
  mark_completed "${rid}"

  log_success "Run ${rid} completed in ${run_duration}s (~$((run_duration / 60))m)"
  RUN_DURATION="${run_duration}"
}

# ── Main Execution ────────────────────────────────────────────────────────────

main() {
  local filter_service=""
  local filter_config=""
  local filter_pattern=""
  local resume=false
  local dry_run=false

  # Parse arguments
  while [[ $# -gt 0 ]]; do
    case $1 in
      --service)    filter_service="$2"; shift 2 ;;
      --config)     filter_config="$2"; shift 2 ;;
      --pattern)    filter_pattern="$2"; shift 2 ;;
      --resume)     resume=true; shift ;;
      --first)      REPETITIONS=1; shift ;;
      --dry-run)    dry_run=true; shift ;;
      --help|-h)
        echo "Usage: $0 [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  --service NAME     Only run for specific service (product-service|auth-service)"
        echo "  --config  NAME     Only run specific config (b1|b2|h1|h2|h3|k1)"
        echo "  --pattern NAME     Only run specific pattern (gradual|spike|oscillating)"
        echo "  --resume           Resume from last completed run"
        echo "  --first            Run only the 1st repetition for everything (override)"
        echo "  --dry-run          Print execution plan without running"
        echo "  --help             Show this help"
        exit 0
        ;;
      *) echo "Unknown option: $1"; exit 1 ;;
    esac
  done

  # Setup
  mkdir -p "${RESULTS_BASE_DIR}"
  touch "${LOG_FILE}"

  log "================================================================"
  log "  THESIS EXPERIMENT RUNNER"
  log "  Started: $(date -Iseconds)"
  log "================================================================"

  # Build run list
  local runs=()
  local total_runs=0
  local skipped_runs=0

  for service in "${SERVICES[@]}"; do
    [[ -n "${filter_service}" && "${service}" != "${filter_service}" ]] && continue
    for config in "${CONFIGS[@]}"; do
      [[ -n "${filter_config}" && "${config}" != "${filter_config}" ]] && continue
      for pattern in "${PATTERNS[@]}"; do
        [[ -n "${filter_pattern}" && "${pattern}" != "${filter_pattern}" ]] && continue
        for ((rep=1; rep<=REPETITIONS; rep++)); do
          local rid
          rid=$(run_id "${service}" "${config}" "${pattern}" "${rep}")
          total_runs=$((total_runs + 1))

          if ${resume} && is_completed "${rid}"; then
            skipped_runs=$((skipped_runs + 1))
            continue
          fi

          runs+=("${service}|${config}|${pattern}|${rep}")
        done
      done
    done
  done

  local pending_runs=${#runs[@]}
  local est_time
  est_time=$(calc_eta "${pending_runs}" 900)  # ~15min per run

  log ""
  log "  Total runs:     ${total_runs}"
  log "  Already done:   ${skipped_runs}"
  log "  Pending:        ${pending_runs}"
  log "  Estimated time: ${est_time}"
  log "  Product load:   base=${PRODUCT_BASE_RPS} peak=${PRODUCT_PEAK_RPS} page_size=${PRODUCT_PAGE_SIZE} max_page=${PRODUCT_MAX_PAGE}"
  log "  Auth load:      base=${AUTH_BASE_RPS} peak=${AUTH_PEAK_RPS} me=${AUTH_ME_PERCENT}% login=${AUTH_LOGIN_PERCENT}% users=${NUM_TEST_USERS}"
  log ""

  if ${dry_run}; then
    log "${YELLOW}DRY RUN — Execution plan:${NC}"
    local run_num=0
    for run_spec in "${runs[@]}"; do
      run_num=$((run_num + 1))
      IFS='|' read -r service config pattern rep <<< "${run_spec}"
      local rid
      rid=$(run_id "${service}" "${config}" "${pattern}" "${rep}")
      echo "  ${run_num}. ${rid}"
    done
    log ""
    log "Run without --dry-run to execute."
    exit 0
  fi

  # Verify cluster connectivity
  log_step "Verifying cluster connectivity..."
  if ! kubectl get namespace "${NAMESPACE}" &>/dev/null; then
    log_error "Cannot reach namespace '${NAMESPACE}'. Is the cluster running?"
    log_error "Run: az aks get-credentials --resource-group ecommerce --name ecommerce-aks"
    exit 1
  fi

  delete_k6_jobs
  apply_k6_configmaps
  log_success "Cluster connectivity verified"

  # Execute runs
  local completed=0
  local total_elapsed=0

  for run_spec in "${runs[@]}"; do
    IFS='|' read -r service config pattern rep <<< "${run_spec}"
    completed=$((completed + 1))

    # Progress header
    local progress
    progress=$(get_progress "${total_runs}")
    local remaining=$((pending_runs - completed + 1))
    local avg_time=900
    [[ ${completed} -gt 1 && ${total_elapsed} -gt 0 ]] && avg_time=$((total_elapsed / (completed - 1)))
    local eta
    eta=$(calc_eta "${remaining}" "${avg_time}")

    log ""
    log "╔══════════════════════════════════════════════════════════════╗"
    log "║  Progress: ${completed}/${pending_runs} | ETA: ${eta} | Done: ${progress}"
    log "╚══════════════════════════════════════════════════════════════╝"

    # Execute the run (updates RUN_DURATION global variable)
    execute_single_run "${service}" "${config}" "${pattern}" "${rep}"
    total_elapsed=$((total_elapsed + RUN_DURATION))
  done

  # Final cleanup
  log ""
  log "================================================================"
  log "  EXPERIMENT COMPLETE"
  log "  Finished: $(date -Iseconds)"
  log "  Total elapsed: $((total_elapsed / 3600))h $(((total_elapsed % 3600) / 60))m"
  log "  Results saved to: ${RESULTS_BASE_DIR}/"
  log "================================================================"

  # Final cluster cleanup
  for service in "${SERVICES[@]}"; do
    [[ -n "${filter_service}" && "${service}" != "${filter_service}" ]] && continue
    cleanup_autoscalers "${service}"
  done

  log_success "All done! Don't forget: az aks stop --resource-group ecommerce --name ecommerce-aks"
}

main "$@"
