#!/usr/bin/env bash
# ============================================================================
# Open-Loop Pilot Runner — ramping-arrival-rate pilot + calibration ladder
# ============================================================================
#
# Decides, with data, whether an open-loop (ramping-arrival-rate) generator is
# stable now that connection pinning, the auth 30 s window and the setup()
# failure injection are fixed. Only the load generator differs from the final
# campaign: autoscaler manifests, reset/stabilize/export timings and the
# readiness pre-flight are reused from run-experiment.sh (sourced below).
#
# Usage (from the repository root):
#   scripts/run-pilot-openloop.sh run    [--resume] [--dry-run] [--max-runs N]
#   scripts/run-pilot-openloop.sh ladder --service S --config b1|b2 --rates "2,4,6" \
#                                        [--step 2m] [--gap 30s] [--max-inflight N]
#   OPENLOOP_RESULTS_DIR=experiment-results-openloop scripts/run-pilot-openloop.sh ...
#
# Inputs (experiment-results-pilot-openloop/, or $OPENLOOP_RESULTS_DIR):
#   pilot-config.env  rates, SLOs, request timeout, VU factor, k6 resources, seed;
#                     v2 knobs: SERVICE_IMAGE_TAG, MAX_INFLIGHT_AUTH/_SHIPPING
#                     (admission control), PREAUTH_AUTH_TOKENS, LOAD_PROFILE_VERSION
#   runlist.txt       explicit run list, one "service config pattern rep" per line
# Outputs (same directory):
#   <service>/<config>/<pattern>/rep<N>/  one directory per pilot run
#   calibration/<service>_<config>_<ts>/  one directory per ladder
#   .pilot-plan (+ .meta)  frozen run order, shuffled within each rep block
#   .pilot-state           DONE:<run_id> lines, used by --resume
#   pilot.log
#
# Per run, on top of the closed-loop protocol:
#   - both core services are reset to 1 replica / no autoscaler (runs of the
#     two services are interleaved)
#   - a 5 s watcher records pod readiness and HPA status (pod-timeline.jsonl,
#     hpa-timeline.jsonl) so scale-up and Ready times are exact
#   - the k6 container stays alive after k6 exits until the gzipped per-request
#     JSON has been fetched and verified (md5 + gzip -t)
#   - Prometheus exports add per-pod request rate, pod readiness, scrape health
#     (up), k6 CPU / throttling / memory, carrier-mock CPU and, with admission
#     control, the shed rate and requests in flight
#   - v2: B1/B2 Deployments are rendered with SERVICE_IMAGE_TAG and the
#     admission-control cap; auth test users are pre-authenticated during the
#     reset (before RESET_WAIT) so the bcrypt burst never reaches the HPA
# A run is marked DONE only if the raw data was verified, k6 exited 0, every
# required Prometheus export is non-empty and (v2) setup() used the tokens.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=run-experiment.sh
source "${SCRIPT_DIR}/run-experiment.sh"

# ── Pilot configuration (overrides the sourced campaign defaults) ────────────

# OPENLOOP_RESULTS_DIR selects another campaign directory (same layout).
RESULTS_BASE_DIR="${OPENLOOP_RESULTS_DIR:-experiment-results-pilot-openloop}"
[[ "${RESULTS_BASE_DIR}" == /* ]] || RESULTS_BASE_DIR="$(pwd)/${RESULTS_BASE_DIR}"
LOG_FILE="${RESULTS_BASE_DIR}/pilot.log"
STATE_FILE="${RESULTS_BASE_DIR}/.pilot-state"
PLAN_FILE="${RESULTS_BASE_DIR}/.pilot-plan"
PLAN_META_FILE="${RESULTS_BASE_DIR}/.pilot-plan.meta"
CONFIG_FILE="${RESULTS_BASE_DIR}/pilot-config.env"
RUNLIST_FILE="${RESULTS_BASE_DIR}/runlist.txt"
PILOT_K6_FILE="infrastructure/kubernetes/load-testing/k6-openloop-pilot.yaml"
TOKENS_CM="k6-openloop-auth-tokens"
CORE_SERVICES=("auth-service" "shipping-rate-service")

WATCH_INTERVAL=5
K6_DONE_TIMEOUT=1500      # job start -> k6 finished: pull + VU init + setup + 12 m + margin
LADDER_SETTLE_WAIT=30     # after a ladder, let the last step's 1 m rate window get scraped
PILOT_RUN_SECONDS_EST=1260

WATCHER_PID=""

# ── Small utilities ──────────────────────────────────────────────────────────

# Git Bash rewrites POSIX-looking arguments (/results/...) into Windows paths
# before they reach kubectl.exe; in-pod paths must pass through untouched.
kexec() {
  MSYS_NO_PATHCONV=1 kubectl exec -n "${NAMESPACE}" "$@"
}

k6_template_for() {
  case "$1" in
    auth-service) echo "k6-openloop-auth" ;;
    shipping-rate-service) echo "k6-openloop-shipping" ;;
    *) log_error "No open-loop k6 template for $1"; return 1 ;;
  esac
}

k6_resources_for() {
  case "$1" in
    auth-service) echo "${K6_RESOURCES_AUTH}" ;;
    shipping-rate-service) echo "${K6_RESOURCES_SHIPPING}" ;;
  esac
}

service_base_rate() {
  case "$1" in
    auth-service) echo "${AUTH_BASE_RATE}" ;;
    shipping-rate-service) echo "${SHIPPING_BASE_RATE}" ;;
  esac
}

service_peak_rate() {
  case "$1" in
    auth-service) echo "${AUTH_PEAK_RATE}" ;;
    shipping-rate-service) echo "${SHIPPING_PEAK_RATE}" ;;
  esac
}

# Env overrides that keep the request mix / payload identical to the
# closed-loop campaign (same variables run-experiment.sh passes).
service_mix_env() {
  case "$1" in
    auth-service)
      echo "AUTH_ME_PERCENT=${AUTH_ME_PERCENT}" "AUTH_LOGIN_PERCENT=${AUTH_LOGIN_PERCENT}" "NUM_TEST_USERS=${NUM_TEST_USERS}"
      ;;
    shipping-rate-service)
      echo "SHIPPING_MAX_ITEMS=${SHIPPING_MAX_ITEMS}" "SHIPPING_MIN_WEIGHT_GRAMS=${SHIPPING_MIN_WEIGHT_GRAMS}" \
        "SHIPPING_MAX_WEIGHT_GRAMS=${SHIPPING_MAX_WEIGHT_GRAMS}" "SHIPPING_DESTINATION_ZONES=${SHIPPING_DESTINATION_ZONES}"
      ;;
  esac
}

timeout_seconds() {
  local text=$1
  if [[ ! "${text}" =~ ^([0-9]+)s$ ]]; then
    log_error "REQUEST_TIMEOUT must look like '5s' (got '${text}')"
    return 1
  fi
  echo "${BASH_REMATCH[1]}"
}

# ceil(VU_FACTOR x rate x timeout) — same formula as openloop-common.js vusFor().
vus_for_rate() {
  local rate=$1 timeout_s
  timeout_s=$(timeout_seconds "${REQUEST_TIMEOUT}")
  awk -v f="${VU_FACTOR}" -v r="${rate}" -v t="${timeout_s}" \
    'BEGIN { v = f * r * t; c = int(v); if (c < v) c++; if (c < 1) c = 1; printf "%d", c }'
}

dns_job_name() {
  local name
  name=$(echo "$1" | tr '_' '-' | tr '[:upper:]' '[:lower:]')
  if (( ${#name} > 63 )); then
    name="${name:0:54}-$(printf '%s' "${name}" | sha1sum | cut -c1-8)"
  fi
  echo "${name}"
}

k6_image() {
  awk '/name: k6-openloop-auth$/ { found = 1 } found && /image:/ { print $2; exit }' "${PILOT_K6_FILE}"
}

load_pilot_config() {
  if [[ ! -f "${CONFIG_FILE}" ]]; then
    log_error "Missing ${CONFIG_FILE}"
    exit 1
  fi
  # shellcheck disable=SC1090
  source "${CONFIG_FILE}"
  : "${REQUEST_TIMEOUT:=5s}" "${VU_FACTOR:=1.5}" "${PILOT_SEED:=20261005}"
  : "${K6_RESOURCES_AUTH:=1000m,1Gi,2000m,4Gi}" "${K6_RESOURCES_SHIPPING:=1000m,1Gi,2000m,4Gi}"
  : "${AUTH_BASE_RATE:=}" "${AUTH_PEAK_RATE:=}" "${SHIPPING_BASE_RATE:=}" "${SHIPPING_PEAK_RATE:=}"
  # v2 campaign knobs; the defaults reproduce the 2026-10-05 pilot exactly.
  : "${LOAD_PROFILE_VERSION:=open-loop-arr-v1}" "${SERVICE_IMAGE_TAG:=}"
  : "${MAX_INFLIGHT_AUTH:=0}" "${MAX_INFLIGHT_SHIPPING:=0}" "${PREAUTH_AUTH_TOKENS:=false}"
  : "${CODE_OVERLAY:=false}"
  OVERLAY_SHA=""
  timeout_seconds "${REQUEST_TIMEOUT}" >/dev/null
}

# Admission-control cap (MAX_INFLIGHT_REQUESTS) for the service; 0 = disabled.
max_inflight_for() {
  case "$1" in
    auth-service) echo "${MAX_INFLIGHT_AUTH}" ;;
    shipping-rate-service) echo "${MAX_INFLIGHT_SHIPPING}" ;;
    *) echo 0 ;;
  esac
}

# ── Code overlay ──────────────────────────────────────────────────────────────
# ACR Tasks are unavailable in Indonesia Central, so instead of rebuilding the
# image the admission-control code is mounted from a ConfigMap over the SAME
# :latest image the closed-loop campaign used (verified 2026-10-06: every
# app/internal .py file in both images equals repo HEAD). Only main.py and the
# new middleware differ; dependencies are untouched.
overlay_cm_for() { echo "openloop-overlay-$1"; }

# "KEY:in-container path" pairs. shipping's image has no internal/middleware
# package yet, so it also gets an (empty) __init__.py.
overlay_mounts_for() {
  echo "main.py:/app/app/main.py" "admission_control.py:/app/internal/middleware/admission_control.py"
  [[ "$1" == "shipping-rate-service" ]] && echo "middleware_init.py:/app/internal/middleware/__init__.py"
  return 0
}

# Create/refresh the overlay ConfigMap from the repo files; sets OVERLAY_SHA.
ensure_overlay_configmap() {
  local service=$1 src="backend/services/$1"
  local files=("${src}/app/main.py" "${src}/internal/middleware/admission_control.py")
  local pairs=("main.py=${files[0]}" "admission_control.py=${files[1]}")
  [[ "${service}" == "shipping-rate-service" ]] && pairs+=("middleware_init.py=")
  OVERLAY_SHA=$(cat "${files[@]}" | tr -d '\r' | sha1sum | cut -c1-12)
  node "${RUN_HELPER}" configmap-from-files "$(overlay_cm_for "${service}")" "${NAMESPACE}" "${pairs[@]}" \
    | kubectl apply -f - -n "${NAMESPACE}" >/dev/null
}

# The experiment's own b1/b2 Deployment manifest, with the campaign's image tag,
# code overlay and admission-control cap applied. Without any knob it is the
# file as-is.
render_deployment() {
  local service=$1 yaml=$2 cap args=() m
  if [[ "${CODE_OVERLAY}" == "true" ]]; then
    args+=("--volume-cm=$(overlay_cm_for "${service}")")
    for m in $(overlay_mounts_for "${service}"); do args+=("--mount=${m}"); done
    # Content hash in the pod template: changed code => new rollout.
    args+=("OPENLOOP_OVERLAY_SHA=${OVERLAY_SHA}")
  fi
  cap=$(max_inflight_for "${service}")
  [[ "${cap}" =~ ^[1-9][0-9]*$ ]] && args+=("MAX_INFLIGHT_REQUESTS=${cap}")
  node "${RUN_HELPER}" render-deployment "${yaml}" "${SERVICE_IMAGE_TAG}" "${args[@]}"
}

# run-experiment.sh's apply_config with the Deployment rendered as above;
# HPA/ScaledObject manifests are applied unchanged.
apply_config_openloop() {
  local service=$1 config=$2
  local config_dir config_path ctype expected deploy_yaml
  config_dir=$(get_config_dir "${service}")
  config_path="${config_dir}/$(config_file "${config}")"
  ctype=$(config_type "${config}")
  expected=$(expected_replicas "${config}")
  deploy_yaml="${config_path}"
  [[ "${ctype}" != "deployment" ]] && deploy_yaml="${config_dir}/b1-underprovisioned.yaml"

  OVERLAY_SHA=""
  [[ "${CODE_OVERLAY}" == "true" ]] && ensure_overlay_configmap "${service}"
  log_step "Applying configuration: ${config} for ${service} (image tag '${SERVICE_IMAGE_TAG:-from manifest}', code overlay ${OVERLAY_SHA:-off}, max in-flight $(max_inflight_for "${service}"))"
  render_deployment "${service}" "${deploy_yaml}" | kubectl apply -f - -n "${NAMESPACE}" &>/dev/null
  kubectl rollout status deployment/"${service}" -n "${NAMESPACE}" --timeout=180s &>/dev/null
  if [[ "${ctype}" != "deployment" ]]; then
    kubectl apply -f "${config_path}" -n "${NAMESPACE}" &>/dev/null
  fi

  wait_for_expected_replicas "${service}" "${expected}" 180 "config apply (${config})"
  log_step "Waiting ${STABILIZE_WAIT}s for metrics to baseline..."
  sleep "${STABILIZE_WAIT}"
  wait_for_expected_replicas "${service}" "${expected}" 180 "post-config stabilization (${config})"
  log_success "Configuration ${config} applied for ${service}"
}

# Log the auth test users in now — no autoscaler exists yet and RESET_WAIT has
# not started — so the ~28 s bcrypt burst is long gone from the CPU window when
# H1/H2 are applied. Tokens go to a ConfigMap the load job mounts; they are
# kept on local disk only for the moment it takes to create it.
preauth_auth_tokens() {
  local job="k6-ol-auth-preauth" conds="" pod count tmp
  kubectl delete job "${job}" -n "${NAMESPACE}" --ignore-not-found &>/dev/null || true
  log_step "Pre-authenticating ${NUM_TEST_USERS} auth test users (before any autoscaler exists)..."
  node "${RUN_HELPER}" clone-job-env "${PILOT_K6_FILE}" k6-openloop-auth-preauth "${job}" \
      "NUM_TEST_USERS=${NUM_TEST_USERS}" \
    | kubectl apply -f - -n "${NAMESPACE}" >&2

  local deadline=$((SECONDS + 300))
  while (( SECONDS < deadline )); do
    conds=$(job_conditions "${job}")
    [[ "${conds}" == *"Complete=True"* || "${conds}" == *"Failed=True"* ]] && break
    sleep 3
  done

  tmp=$(mktemp)
  pod=$(k6_pod_for_job "${job}")
  kubectl logs "${pod}" -n "${NAMESPACE}" 2>/dev/null | grep -m1 '^PREAUTH_TOKENS ' | sed 's/^PREAUTH_TOKENS //' > "${tmp}" || true
  kubectl delete job "${job}" -n "${NAMESPACE}" --ignore-not-found &>/dev/null || true
  count=$(node -e 'try { const t = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8")); console.log(Array.isArray(t) ? t.length : 0); } catch (e) { console.log(0); }' "${tmp}")
  if [[ "${count}" -lt 1 ]]; then
    rm -f "${tmp}"
    log_error "Pre-authentication produced no tokens (job conditions: ${conds:-none})"
    return 1
  fi
  node "${RUN_HELPER}" configmap-from-file "${TOKENS_CM}" "${NAMESPACE}" tokens.json "${tmp}" \
    | kubectl apply -f - -n "${NAMESPACE}" >/dev/null
  rm -f "${tmp}"
  PREAUTH_COUNT="${count}"
  PREAUTH_EPOCH=$(date +%s)
  log_success "Pre-authenticated ${count} users; tokens stored in ConfigMap ${TOKENS_CM}"
}

# run-experiment.sh's reset_cluster_state plus the auth pre-authentication,
# which must happen before RESET_WAIT so its CPU burst cannot reach the HPA.
pilot_reset_cluster_state() {
  local service=$1
  log_step "Resetting cluster state for ${service}..."
  cleanup_autoscalers "${service}"
  delete_k6_jobs
  if [[ "${service}" == "auth-service" ]]; then
    # Never let a run pick up tokens from an earlier run.
    kubectl delete configmap "${TOKENS_CM}" -n "${NAMESPACE}" --ignore-not-found &>/dev/null || true
    if [[ "${PREAUTH_AUTH_TOKENS}" == "true" ]]; then
      preauth_auth_tokens
    fi
  fi
  log_step "Waiting ${RESET_WAIT}s for cluster stabilization..."
  sleep "${RESET_WAIT}"
  wait_for_expected_replicas "${service}" 1 180 "post-reset stabilization"
  log_success "Cluster state reset complete for ${service}"
}

require_rates() {
  local service=$1 base peak
  base=$(service_base_rate "${service}")
  peak=$(service_peak_rate "${service}")
  if [[ ! "${base}" =~ ^[0-9]+$ || ! "${peak}" =~ ^[0-9]+$ || "${base}" -lt 1 || "${peak}" -lt "${base}" ]]; then
    log_error "Rates for ${service} are not set in ${CONFIG_FILE} (base='${base}', peak='${peak}')"
    log_error "They are fixed after the Phase 4 calibration ladder."
    exit 1
  fi
  # The SLO is part of the frozen plan, so it must exist before the first run.
  local slo_var="AUTH_SLO_MS"
  [[ "${service}" == "shipping-rate-service" ]] && slo_var="SHIPPING_SLO_MS"
  if [[ ! "${!slo_var:-}" =~ ^[0-9]+$ ]]; then
    log_error "${slo_var} is not set in ${CONFIG_FILE}; the SLO must be fixed before the pilot starts."
    exit 1
  fi
}

apply_pilot_configmaps() {
  log_step "Refreshing open-loop k6 ConfigMaps..."
  node "${RUN_HELPER}" print-configmaps "${PILOT_K6_FILE}" | kubectl apply -f - -n "${NAMESPACE}" >&2
}

# Every core service back to 1 replica with no autoscaler. The closed-loop
# runner ran the services in separate blocks; the pilot interleaves them.
reset_other_services() {
  local service=$1 other
  for other in "${CORE_SERVICES[@]}"; do
    [[ "${other}" == "${service}" ]] && continue
    cleanup_autoscalers "${other}"
  done
}

# ── Background watcher: pod readiness + HPA status every WATCH_INTERVAL s ────

start_watcher() {
  local service=$1 out_dir=$2
  (
    set +e
    while true; do
      kubectl get pods -n "${NAMESPACE}" -l "app=${service}" -o json 2>/dev/null \
        | node "${RUN_HELPER}" pod-snapshot >> "${out_dir}/pod-timeline.jsonl" 2>/dev/null
      kubectl get hpa -n "${NAMESPACE}" -o json 2>/dev/null \
        | node "${RUN_HELPER}" hpa-snapshot >> "${out_dir}/hpa-timeline.jsonl" 2>/dev/null
      sleep "${WATCH_INTERVAL}"
    done
  ) &
  WATCHER_PID=$!
}

stop_watcher() {
  if [[ -n "${WATCHER_PID}" ]]; then
    kill "${WATCHER_PID}" 2>/dev/null || true
    wait "${WATCHER_PID}" 2>/dev/null || true
    WATCHER_PID=""
  fi
}

trap stop_watcher EXIT

# ── k6 job lifecycle ─────────────────────────────────────────────────────────

create_openloop_job() {
  local service=$1 job_name=$2
  shift 2
  local template resources
  template=$(k6_template_for "${service}")
  resources=$(k6_resources_for "${service}")

  kubectl delete job "${job_name}" -n "${NAMESPACE}" --ignore-not-found &>/dev/null || true
  # shellcheck disable=SC2046
  node "${RUN_HELPER}" clone-job-env "${PILOT_K6_FILE}" "${template}" "${job_name}" \
      "--resources=${resources}" "REQUEST_TIMEOUT=${REQUEST_TIMEOUT}" "VU_FACTOR=${VU_FACTOR}" \
      $(service_mix_env "${service}") "$@" \
    | kubectl apply -f - -n "${NAMESPACE}" >&2
}

k6_pod_for_job() {
  kubectl get pods -n "${NAMESPACE}" -l "job-name=$1" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true
}

job_conditions() {
  kubectl get job "$1" -n "${NAMESPACE}" \
    -o jsonpath='{range .status.conditions[*]}{.type}={.status}{" "}{end}' 2>/dev/null || true
}

# Wait until the wrapper signals that k6 has exited (/results/.k6-done).
# Sets K6_POD. Returns 1 if the pod ends or the deadline passes first.
wait_for_k6_done() {
  local job_name=$1 timeout=$2
  local deadline=$((SECONDS + timeout))
  K6_POD=""
  log_step "Waiting for k6 to finish (deadline ${timeout}s)..."
  while (( SECONDS < deadline )); do
    [[ -z "${K6_POD}" ]] && K6_POD=$(k6_pod_for_job "${job_name}")
    if [[ -n "${K6_POD}" ]]; then
      local phase
      phase=$(kubectl get pod "${K6_POD}" -n "${NAMESPACE}" -o jsonpath='{.status.phase}' 2>/dev/null || true)
      case "${phase}" in
        Running)
          if kexec "${K6_POD}" -c k6 -- sh -c 'test -f /results/.k6-done' &>/dev/null; then
            log_success "k6 finished in pod ${K6_POD}"
            return 0
          fi
          ;;
        Succeeded|Failed)
          log_error "k6 pod ${K6_POD} ended (${phase}) before the raw results were fetched"
          return 1
          ;;
      esac
    fi
    if [[ "$(job_conditions "${job_name}")" == *"Failed=True"* ]]; then
      log_error "k6 job ${job_name} failed before finishing"
      return 1
    fi
    sleep 10
  done
  log_error "k6 did not finish within ${timeout}s"
  return 1
}

# Copy the gzipped per-request JSON out of the still-running container, verify
# it, then release the container. Sets RAW_OK, RAW_MD5, RAW_BYTES, K6_EXIT_CODE.
fetch_raw_results() {
  local pod=$1 out_dir=$2
  local raw="${out_dir}/k6-results.json.gz"
  RAW_OK=false RAW_MD5="" RAW_BYTES=0 K6_EXIT_CODE=""

  local attempt remote_md5 local_md5
  for attempt in 1 2 3; do
    kexec "${pod}" -c k6 -- cat /results/results.json.gz > "${raw}" 2>/dev/null || true
    remote_md5=$(kexec "${pod}" -c k6 -- cat /results/results.json.gz.md5 2>/dev/null | awk '{print $1}' || true)
    local_md5=$(md5sum "${raw}" 2>/dev/null | awk '{print $1}')
    if [[ -n "${remote_md5}" && "${remote_md5}" == "${local_md5}" ]] && gzip -t "${raw}" 2>/dev/null; then
      RAW_OK=true
      RAW_MD5="${local_md5}"
      RAW_BYTES=$(wc -c < "${raw}" | tr -d ' ')
      break
    fi
    log_warn "Raw results fetch attempt ${attempt} failed verification (remote md5='${remote_md5}', local md5='${local_md5}')"
    sleep 5
  done

  K6_EXIT_CODE=$(kexec "${pod}" -c k6 -- cat /results/k6-exit-code 2>/dev/null | tr -dc '0-9' || true)
  # Release the wrapper so the container exits and the Job completes.
  kexec "${pod}" -c k6 -- sh -c 'touch /results/.fetched' &>/dev/null || true

  if ${RAW_OK}; then
    log_success "Raw per-request data fetched: ${RAW_BYTES} bytes, md5 ${RAW_MD5}, k6 exit code ${K6_EXIT_CODE:-?}"
  else
    log_error "Could not fetch verified raw per-request data from ${pod}"
  fi
}

finish_k6_job() {
  local job_name=$1 pod=$2 out_dir=$3
  local deadline=$((SECONDS + 120))
  while (( SECONDS < deadline )); do
    local conds
    conds=$(job_conditions "${job_name}")
    [[ "${conds}" == *"Complete=True"* || "${conds}" == *"Failed=True"* ]] && break
    sleep 3
  done
  kubectl logs "${pod}" -n "${NAMESPACE}" -c k6 > "${out_dir}/k6-output.log" 2>/dev/null || true
  if [[ ! -s "${out_dir}/k6-output.log" ]]; then
    log_error "Could not capture k6 logs for job ${job_name}"
    return 1
  fi
}

scenario_start_ms() {
  grep -oE 'SCENARIO_START name=[^ ]+ start_ms=[0-9]+' "$1" 2>/dev/null | head -1 | sed -E 's/.*start_ms=//' || true
}

# ── Prometheus export (explicit window) ──────────────────────────────────────

prom_query_range() {
  local prom_pod=$1 query=$2 start=$3 end=$4 out_file=$5
  local encoded
  encoded=$(node "${RUN_HELPER}" urlencode "${query}")
  timeout "${PROM_EXPORT_TIMEOUT}" kubectl exec -n "${MONITORING_NS}" "${prom_pod}" -- \
    wget -q -O - "http://localhost:9090/api/v1/query_range?query=${encoded}&start=${start}&end=${end}&step=15" \
    > "${out_file}" 2>/dev/null || return 1
  [[ -s "${out_file}" ]] || return 1
  ! grep -q '"result":\[\]' "${out_file}"
}

export_pilot_metrics() {
  local service=$1 config=$2 job_name=$3 out_dir=$4 window_start=$5
  local prom_pod end_time
  prom_pod=$(kubectl get pods -n "${MONITORING_NS}" -l app=prometheus --no-headers -o custom-columns=":metadata.name" | head -1)
  if [[ -z "${prom_pod}" ]]; then
    log_error "Prometheus pod not found — cannot export metrics"
    return 1
  fi
  end_time=$(date +%s)
  log_step "Exporting Prometheus metrics for ${window_start}..${end_time}..."

  local ns="${NAMESPACE}"
  # The first five are the closed-loop runner's queries (same file names); the
  # rest exist for the per-pod distribution check and the k6 resource check.
  local queries=(
    "sum by (handler,method) (rate(http_requests_total{job=\"${service}\"}[1m]))|http_requests_rate"
    "histogram_quantile(0.95,sum by (le,handler,method) (rate(http_request_duration_seconds_bucket{job=\"${service}\"}[1m])))|p95_latency"
    "kube_deployment_status_replicas{deployment=\"${service}\"}|replica_count"
    "kube_deployment_status_replicas_ready{deployment=\"${service}\"}|replica_ready_count"
    "rate(container_cpu_usage_seconds_total{container=\"${service}\"}[1m])|cpu_usage"
    "sum by (pod) (rate(http_requests_total{job=\"${service}\"}[1m]))|pod_request_rate"
    "kube_pod_status_ready{namespace=\"${ns}\",condition=\"true\",pod=~\"${service}-.*\"}|pod_ready"
    "sum by (pod) (rate(container_cpu_cfs_throttled_periods_total{namespace=\"${ns}\",container=\"${service}\"}[1m])) / sum by (pod) (rate(container_cpu_cfs_periods_total{namespace=\"${ns}\",container=\"${service}\"}[1m]))|cpu_throttled_ratio"
    "sum by (pod) (rate(container_cpu_usage_seconds_total{namespace=\"${ns}\",container=\"k6\"}[1m]))|k6_cpu"
    "sum by (pod) (rate(container_cpu_cfs_throttled_periods_total{namespace=\"${ns}\",container=\"k6\"}[1m])) / sum by (pod) (rate(container_cpu_cfs_periods_total{namespace=\"${ns}\",container=\"k6\"}[1m]))|k6_cpu_throttled_ratio"
    "max by (pod) (container_memory_working_set_bytes{namespace=\"${ns}\",container=\"k6\"})|k6_memory"
    "sum by (pod) (rate(container_cpu_usage_seconds_total{namespace=\"${ns}\",container=\"carrier-mock-service\"}[1m]))|carrier_cpu"
    # Scrape health per pod: 0 = Prometheus could not scrape a Ready pod.
    "up{job=\"${service}\"}|up"
    # Only exist when admission control is enabled (v2 campaign).
    "sum by (pod) (rate(http_requests_shed_total{job=\"${service}\"}[1m]))|shed_rate|optional"
    "max by (pod) (http_requests_inflight{job=\"${service}\"})|inflight|optional"
  )

  local export_failed=false query_pair query name flag
  for query_pair in "${queries[@]}"; do
    IFS='|' read -r query name flag <<< "${query_pair}"
    if ! prom_query_range "${prom_pod}" "${query}" "${window_start}" "${end_time}" "${out_dir}/prom_${name}.json"; then
      if [[ "${flag}" == "optional" ]]; then
        log_step "Prometheus export ${name} is empty (optional series)"
      else
        log_error "Prometheus export ${name} failed or returned an empty result set"
        export_failed=true
      fi
    fi
  done

  local hpa_name scaledobject_name
  hpa_name=$(hpa_name_for_config "${service}" "${config}")
  scaledobject_name=$(scaledobject_name_for_config "${service}" "${config}")
  timeout "${PROM_EXPORT_TIMEOUT}" kubectl get events -n "${NAMESPACE}" -o json 2>/dev/null | \
    node "${RUN_HELPER}" filter-events "${service}" "${job_name}" "${hpa_name}" "${scaledobject_name}" "${window_start}" \
    > "${out_dir}/k8s-events.txt" || true
  write_scoped_yaml "hpa" "${hpa_name}" "${out_dir}/hpa-status.yaml"
  write_scoped_yaml "scaledobject" "${scaledobject_name}" "${out_dir}/keda-status.yaml"
  kubectl get pods -n "${NAMESPACE}" -l "app=${service}" -o wide > "${out_dir}/pod-status.txt" 2>/dev/null || true

  if ${export_failed}; then
    return 1
  fi
  log_success "Prometheus metrics exported to ${out_dir}/"
}

# ── Metadata ─────────────────────────────────────────────────────────────────

write_metadata() {
  # All values arrive via the environment so no shell quoting can break the JSON.
  META_OUT="$1" node -e '
    const fs = require("fs");
    const e = process.env;
    const num = (v) => (v === undefined || v === "" ? null : Number(v));
    const meta = {
      run_id: e.M_RUN_ID,
      kind: e.M_KIND,
      service: e.M_SERVICE,
      config: e.M_CONFIG,
      pattern: e.M_PATTERN,
      repetition: num(e.M_REP),
      plan_position: num(e.M_PLAN_POS),
      start_epoch: num(e.M_START),
      end_epoch: num(e.M_END),
      duration_seconds: num(e.M_END) - num(e.M_START),
      k6_job_name: e.M_JOB,
      k6_pod_name: e.M_POD,
      k6_exit_code: num(e.M_K6_RC),
      k6_scenario_start_ms: num(e.M_SCEN_START),
      target_url: e.M_TARGET_URL,
      raw_results: {
        file: "k6-results.json.gz",
        verified: e.M_RAW_OK === "true",
        bytes: num(e.M_RAW_BYTES),
        md5: e.M_RAW_MD5 || null,
      },
      load_profile: {
        version: e.M_VERSION,
        executor: e.M_EXECUTOR,
        rate_unit: "req/s",
        base_rate: num(e.M_BASE_RATE),
        peak_rate: num(e.M_PEAK_RATE),
        ladder_rates: e.M_LADDER_RATES ? e.M_LADDER_RATES.split(",").map(Number) : null,
        ladder_step: e.M_LADDER_STEP || null,
        ladder_gap: e.M_LADDER_GAP || null,
        request_timeout: e.M_TIMEOUT,
        vu_factor: num(e.M_VU_FACTOR),
        pre_allocated_vus: num(e.M_PRE_VUS),
        max_vus: num(e.M_MAX_VUS),
        no_connection_reuse: true,
        k6_image: e.M_K6_IMAGE,
        k6_resources: e.M_K6_RESOURCES,
        request_mix: e.M_MIX,
      },
      service_overrides: {
        image_tag: e.M_IMAGE_TAG || null,
        code_overlay_sha: e.M_OVERLAY_SHA || null,
        max_inflight_requests: num(e.M_MAX_INFLIGHT) || 0,
      },
      preauth_tokens: {
        enabled: e.M_PREAUTH_ENABLED === "true",
        count: num(e.M_PREAUTH_COUNT),
        epoch: num(e.M_PREAUTH_EPOCH),
      },
      timings: {
        reset_wait: num(e.M_RESET_WAIT),
        stabilize_wait: num(e.M_STABILIZE_WAIT),
        export_wait: num(e.M_EXPORT_WAIT),
      },
      export_ok: e.M_EXPORT_OK === "true",
      timestamp: new Date().toISOString(),
    };
    fs.writeFileSync(process.env.META_OUT, JSON.stringify(meta, null, 2) + "\n");
  '
}

# ── One pilot run ────────────────────────────────────────────────────────────

execute_pilot_run() {
  local service=$1 config=$2 pattern=$3 rep=$4 plan_pos=$5
  local rid base peak vus
  rid=$(run_id "${service}" "${config}" "${pattern}" "${rep}")
  base=$(service_base_rate "${service}")
  peak=$(service_peak_rate "${service}")
  vus=$(vus_for_rate "${peak}")

  local final_dir="${RESULTS_BASE_DIR}/${service}/${config}/${pattern}/rep${rep}"
  local out_dir="${RESULTS_BASE_DIR}/.tmp/${rid}-$(date +%s)"
  mkdir -p "${out_dir}"

  local run_start
  run_start=$(date +%s)
  date -Iseconds > "${out_dir}/start_time.txt"

  log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  log "  PILOT RUN: ${rid}  (plan position ${plan_pos})"
  log "  open loop: ${base} -> ${peak} req/s, timeout ${REQUEST_TIMEOUT}, VUs ${vus}"
  log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  PREAUTH_COUNT="" PREAUTH_EPOCH=""
  reset_other_services "${service}"
  pilot_reset_cluster_state "${service}"
  apply_config_openloop "${service}" "${config}"
  verify_readiness "${service}"

  local job_name
  job_name=$(dns_job_name "k6-ol-${service}-${config}-${pattern}-rep${rep}")
  start_watcher "${service}" "${out_dir}"

  log_step "Starting open-loop k6 job ${job_name}"
  create_openloop_job "${service}" "${job_name}" \
    "PATTERN=${pattern}" "BASE_RATE=${base}" "PEAK_RATE=${peak}" "PRE_VUS=${vus}" "MAX_VUS=${vus}"

  RAW_OK=false RAW_MD5="" RAW_BYTES=0 K6_EXIT_CODE="" K6_POD=""
  local k6_ok=true
  if wait_for_k6_done "${job_name}" "${K6_DONE_TIMEOUT}"; then
    fetch_raw_results "${K6_POD}" "${out_dir}"
  else
    k6_ok=false
    K6_POD=$(k6_pod_for_job "${job_name}")
  fi
  if [[ -n "${K6_POD}" ]]; then
    finish_k6_job "${job_name}" "${K6_POD}" "${out_dir}" || k6_ok=false
  else
    k6_ok=false
  fi

  # Same cooldown capture as the closed-loop runner; the watcher keeps
  # recording scale-down meanwhile.
  log_step "Waiting ${EXPORT_WAIT}s before data export..."
  sleep "${EXPORT_WAIT}"
  stop_watcher

  local export_ok=true
  export_pilot_metrics "${service}" "${config}" "${job_name}" "${out_dir}" "${run_start}" || export_ok=false

  local run_end
  run_end=$(date +%s)
  date -Iseconds > "${out_dir}/end_time.txt"

  M_RUN_ID="${rid}" M_KIND="pilot" M_SERVICE="${service}" M_CONFIG="${config}" M_PATTERN="${pattern}" \
  M_REP="${rep}" M_PLAN_POS="${plan_pos}" M_START="${run_start}" M_END="${run_end}" \
  M_JOB="${job_name}" M_POD="${K6_POD}" M_K6_RC="${K6_EXIT_CODE}" \
  M_SCEN_START="$(scenario_start_ms "${out_dir}/k6-output.log")" \
  M_TARGET_URL="http://${service}.${NAMESPACE}.svc.cluster.local:$(service_port "${service}")" \
  M_RAW_OK="${RAW_OK}" M_RAW_BYTES="${RAW_BYTES}" M_RAW_MD5="${RAW_MD5}" \
  M_VERSION="${LOAD_PROFILE_VERSION}" M_EXECUTOR="ramping-arrival-rate" \
  M_BASE_RATE="${base}" M_PEAK_RATE="${peak}" M_TIMEOUT="${REQUEST_TIMEOUT}" M_VU_FACTOR="${VU_FACTOR}" \
  M_PRE_VUS="${vus}" M_MAX_VUS="${vus}" M_K6_IMAGE="$(k6_image)" M_K6_RESOURCES="$(k6_resources_for "${service}")" \
  M_MIX="$(service_mix_env "${service}")" \
  M_RESET_WAIT="${RESET_WAIT}" M_STABILIZE_WAIT="${STABILIZE_WAIT}" M_EXPORT_WAIT="${EXPORT_WAIT}" \
  M_IMAGE_TAG="${SERVICE_IMAGE_TAG}" M_MAX_INFLIGHT="$(max_inflight_for "${service}")" M_OVERLAY_SHA="${OVERLAY_SHA}" \
  M_PREAUTH_ENABLED="$([[ "${service}" == "auth-service" && "${PREAUTH_AUTH_TOKENS}" == "true" ]] && echo true || echo false)" \
  M_PREAUTH_COUNT="${PREAUTH_COUNT}" M_PREAUTH_EPOCH="${PREAUTH_EPOCH}" \
  M_EXPORT_OK="${export_ok}" \
    write_metadata "${out_dir}/metadata.json"

  # With pre-authentication on, setup() must have used the tokens instead of
  # logging in again (that login burst is what pre-authentication removes).
  local preauth_ok=true
  if [[ "${service}" == "auth-service" && "${PREAUTH_AUTH_TOKENS}" == "true" ]] \
      && ! grep -q 'PREAUTH_USED tokens=' "${out_dir}/k6-output.log" 2>/dev/null; then
    preauth_ok=false
  fi

  mkdir -p "$(dirname "${final_dir}")"
  rm -rf "${final_dir}"
  mv "${out_dir}" "${final_dir}"
  kubectl delete job "${job_name}" -n "${NAMESPACE}" --ignore-not-found &>/dev/null || true

  RUN_DURATION=$((run_end - run_start))
  if ${k6_ok} && ${RAW_OK} && [[ "${K6_EXIT_CODE}" == "0" ]] && ${export_ok} && ${preauth_ok}; then
    mark_completed "${rid}"
    log_success "Pilot run ${rid} completed in ${RUN_DURATION}s"
  else
    log_error "Pilot run ${rid} is NOT marked DONE (k6_ok=${k6_ok} raw_ok=${RAW_OK} k6_exit=${K6_EXIT_CODE:-?} export_ok=${export_ok} preauth_ok=${preauth_ok}) — --resume will repeat it"
  fi
}

# ── Plan: explicit run list, shuffled within each rep block, frozen ──────────

plan_fingerprint() {
  cat "${RUNLIST_FILE}" "${CONFIG_FILE}" | tr -d '\r' | sha1sum | cut -c1-40
}

ensure_plan() {
  if [[ ! -f "${RUNLIST_FILE}" ]]; then
    log_error "Missing run list ${RUNLIST_FILE}"
    exit 1
  fi
  local fingerprint
  fingerprint=$(plan_fingerprint)
  if [[ -f "${PLAN_FILE}" ]]; then
    if [[ "$(cat "${PLAN_META_FILE}" 2>/dev/null)" != "${fingerprint}" ]]; then
      log_error "runlist.txt or pilot-config.env changed after the plan was frozen."
      log_error "Restore them, or move ${PLAN_FILE} and ${STATE_FILE} aside to start a new pilot."
      exit 1
    fi
    return 0
  fi
  node "${RUN_HELPER}" shuffle-plan "${RUNLIST_FILE}" "${PILOT_SEED}" > "${PLAN_FILE}"
  echo "${fingerprint}" > "${PLAN_META_FILE}"
  log_success "Froze run order in ${PLAN_FILE} (seed ${PILOT_SEED})"
}

cmd_run() {
  local resume=false dry_run=false max_runs=0
  while [[ $# -gt 0 ]]; do
    case $1 in
      --resume) resume=true; shift ;;
      --dry-run) dry_run=true; shift ;;
      --max-runs) max_runs="$2"; shift 2 ;;
      *) echo "Unknown option for run: $1"; exit 1 ;;
    esac
  done

  mkdir -p "${RESULTS_BASE_DIR}"
  touch "${LOG_FILE}"
  load_pilot_config

  if [[ -f "${STATE_FILE}" && -s "${STATE_FILE}" ]] && ! ${resume} && ! ${dry_run}; then
    log_error "${STATE_FILE} already has completed runs; use --resume (or move it aside)."
    exit 1
  fi

  local plan_lines=()
  if [[ -f "${PLAN_FILE}" ]] || ! ${dry_run}; then
    ensure_plan
    mapfile -t plan_lines < <(tr -d '\r' < "${PLAN_FILE}")
  else
    # Dry run before the plan exists: show the order it would freeze.
    mapfile -t plan_lines < <(node "${RUN_HELPER}" shuffle-plan "${RUNLIST_FILE}" "${PILOT_SEED}")
  fi

  local pending=() pos=0 line service config pattern rep rid
  for line in "${plan_lines[@]}"; do
    pos=$((pos + 1))
    IFS='|' read -r service config pattern rep <<< "${line}"
    rid=$(run_id "${service}" "${config}" "${pattern}" "${rep}")
    is_completed "${rid}" && continue
    pending+=("${pos}|${line}")
  done

  local total=${#plan_lines[@]} todo=${#pending[@]}
  (( max_runs > 0 && todo > max_runs )) && todo=${max_runs}

  log "================================================================"
  log "  OPEN-LOOP PILOT  (${LOAD_PROFILE_VERSION}, k6 $(k6_image))"
  log "  Plan: ${total} runs | pending: ${#pending[@]} | this invocation: ${todo}"
  log "  auth ${AUTH_BASE_RATE:-?}->${AUTH_PEAK_RATE:-?} req/s | shipping ${SHIPPING_BASE_RATE:-?}->${SHIPPING_PEAK_RATE:-?} req/s"
  log "  timeout ${REQUEST_TIMEOUT}, VU factor ${VU_FACTOR}, seed ${PILOT_SEED}"
  log "  Estimated time for this invocation: $(calc_eta "${todo}" "${PILOT_RUN_SECONDS_EST}")"
  log "================================================================"

  local entry
  if ${dry_run}; then
    for entry in "${pending[@]:0:${todo}}"; do
      IFS='|' read -r pos service config pattern rep <<< "${entry}"
      echo "  ${pos}. $(run_id "${service}" "${config}" "${pattern}" "${rep}")"
    done
    exit 0
  fi

  for svc in "${CORE_SERVICES[@]}"; do
    grep -q "^${svc}|" "${PLAN_FILE}" && require_rates "${svc}"
  done

  if ! kubectl get namespace "${NAMESPACE}" &>/dev/null; then
    log_error "Cannot reach namespace '${NAMESPACE}'. Is the cluster running?"
    exit 1
  fi
  delete_k6_jobs
  apply_pilot_configmaps

  local done_now=0 elapsed=0
  for entry in "${pending[@]:0:${todo}}"; do
    IFS='|' read -r pos service config pattern rep <<< "${entry}"
    done_now=$((done_now + 1))
    log ""
    log "╔══ Pilot ${done_now}/${todo} (plan position ${pos}/${total}) ══╗"
    execute_pilot_run "${service}" "${config}" "${pattern}" "${rep}" "${pos}"
    elapsed=$((elapsed + RUN_DURATION))
  done

  for svc in "${CORE_SERVICES[@]}"; do
    cleanup_autoscalers "${svc}"
  done
  log_success "Pilot invocation finished: ${done_now} runs in $((elapsed / 60)) min."
  log_warn "Remember: az aks stop --resource-group ecommerce --name ecommerce-aks"
}

# ── Calibration ladder (fixed replicas, constant-arrival-rate steps) ─────────

cmd_ladder() {
  local service="" config="" rates="" step="2m" gap="30s" max_inflight=""
  while [[ $# -gt 0 ]]; do
    case $1 in
      --service) service="$2"; shift 2 ;;
      --config) config="$2"; shift 2 ;;
      --rates) rates="$2"; shift 2 ;;
      --step) step="$2"; shift 2 ;;
      --gap) gap="$2"; shift 2 ;;
      --max-inflight) max_inflight="$2"; shift 2 ;;
      *) echo "Unknown option for ladder: $1"; exit 1 ;;
    esac
  done
  if [[ -z "${service}" || ! "${config}" =~ ^(b1|b2)$ || ! "${rates}" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
    echo "usage: $0 ladder --service S --config b1|b2 --rates \"2,4,6\" [--step 2m] [--gap 30s]"
    exit 1
  fi
  if [[ ! "${step}" =~ ^[0-9]+[sm]$ || ! "${gap}" =~ ^[0-9]+[sm]$ ]]; then
    echo "--step/--gap must look like 2m or 30s"
    exit 1
  fi

  mkdir -p "${RESULTS_BASE_DIR}"
  touch "${LOG_FILE}"
  load_pilot_config
  # Calibrating the admission-control cap: try a value without editing the config.
  if [[ -n "${max_inflight}" ]]; then
    if [[ ! "${max_inflight}" =~ ^[0-9]+$ ]]; then
      echo "--max-inflight must be a non-negative integer"
      exit 1
    fi
    case "${service}" in
      auth-service) MAX_INFLIGHT_AUTH="${max_inflight}" ;;
      shipping-rate-service) MAX_INFLIGHT_SHIPPING="${max_inflight}" ;;
    esac
  fi

  local to_s=() v
  for v in "${step}" "${gap}"; do
    if [[ "${v}" == *m ]]; then to_s+=($(( ${v%m} * 60 ))); else to_s+=("${v%s}"); fi
  done
  local n_steps max_rate
  n_steps=$(tr ',' '\n' <<< "${rates}" | wc -l | tr -d ' ')
  max_rate=$(tr ',' '\n' <<< "${rates}" | sort -n | tail -1)
  local schedule_s=$(( n_steps * to_s[0] + (n_steps - 1) * to_s[1] ))

  local stamp out_dir
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  out_dir="${RESULTS_BASE_DIR}/calibration/${service}_${config}_${stamp}"
  mkdir -p "${out_dir}"

  log "================================================================"
  log "  OPEN-LOOP CALIBRATION LADDER: ${service} ${config}"
  log "  rates ${rates} req/s, step ${step}, gap ${gap}, timeout ${REQUEST_TIMEOUT}"
  log "  image tag '${SERVICE_IMAGE_TAG:-from manifest}', max in-flight $(max_inflight_for "${service}")"
  log "  schedule ${schedule_s}s, largest step needs $(vus_for_rate "${max_rate}") VUs"
  log "================================================================"

  if ! kubectl get namespace "${NAMESPACE}" &>/dev/null; then
    log_error "Cannot reach namespace '${NAMESPACE}'. Is the cluster running?"
    exit 1
  fi
  delete_k6_jobs
  apply_pilot_configmaps

  local run_start
  run_start=$(date +%s)
  date -Iseconds > "${out_dir}/start_time.txt"
  PREAUTH_COUNT="" PREAUTH_EPOCH=""
  reset_other_services "${service}"
  pilot_reset_cluster_state "${service}"
  apply_config_openloop "${service}" "${config}"
  verify_readiness "${service}"

  local job_name
  job_name=$(dns_job_name "k6-ol-ladder-${service}-${config}")
  start_watcher "${service}" "${out_dir}"
  create_openloop_job "${service}" "${job_name}" \
    "PATTERN=ladder" "LADDER_RATES=${rates}" "LADDER_STEP=${step}" "LADDER_GAP=${gap}"

  RAW_OK=false RAW_MD5="" RAW_BYTES=0 K6_EXIT_CODE="" K6_POD=""
  if wait_for_k6_done "${job_name}" $(( schedule_s + 600 )); then
    fetch_raw_results "${K6_POD}" "${out_dir}"
  else
    K6_POD=$(k6_pod_for_job "${job_name}")
  fi
  [[ -n "${K6_POD}" ]] && { finish_k6_job "${job_name}" "${K6_POD}" "${out_dir}" || true; }

  sleep "${LADDER_SETTLE_WAIT}"
  stop_watcher
  local export_ok=true
  export_pilot_metrics "${service}" "${config}" "${job_name}" "${out_dir}" "${run_start}" || export_ok=false

  local run_end
  run_end=$(date +%s)
  date -Iseconds > "${out_dir}/end_time.txt"
  M_RUN_ID="ladder_${service}_${config}_${stamp}" M_KIND="ladder" M_SERVICE="${service}" M_CONFIG="${config}" \
  M_PATTERN="ladder" M_START="${run_start}" M_END="${run_end}" M_JOB="${job_name}" M_POD="${K6_POD}" \
  M_K6_RC="${K6_EXIT_CODE}" M_SCEN_START="$(scenario_start_ms "${out_dir}/k6-output.log")" \
  M_TARGET_URL="http://${service}.${NAMESPACE}.svc.cluster.local:$(service_port "${service}")" \
  M_RAW_OK="${RAW_OK}" M_RAW_BYTES="${RAW_BYTES}" M_RAW_MD5="${RAW_MD5}" \
  M_VERSION="${LOAD_PROFILE_VERSION}" M_EXECUTOR="constant-arrival-rate" \
  M_LADDER_RATES="${rates}" M_LADDER_STEP="${step}" M_LADDER_GAP="${gap}" \
  M_TIMEOUT="${REQUEST_TIMEOUT}" M_VU_FACTOR="${VU_FACTOR}" M_MAX_VUS="$(vus_for_rate "${max_rate}")" \
  M_K6_IMAGE="$(k6_image)" M_K6_RESOURCES="$(k6_resources_for "${service}")" M_MIX="$(service_mix_env "${service}")" \
  M_RESET_WAIT="${RESET_WAIT}" M_STABILIZE_WAIT="${STABILIZE_WAIT}" M_EXPORT_OK="${export_ok}" \
  M_IMAGE_TAG="${SERVICE_IMAGE_TAG}" M_MAX_INFLIGHT="$(max_inflight_for "${service}")" M_OVERLAY_SHA="${OVERLAY_SHA}" \
  M_PREAUTH_ENABLED="$([[ "${service}" == "auth-service" && "${PREAUTH_AUTH_TOKENS}" == "true" ]] && echo true || echo false)" \
  M_PREAUTH_COUNT="${PREAUTH_COUNT}" M_PREAUTH_EPOCH="${PREAUTH_EPOCH}" \
    write_metadata "${out_dir}/metadata.json"

  kubectl delete job "${job_name}" -n "${NAMESPACE}" --ignore-not-found &>/dev/null || true
  cleanup_autoscalers "${service}"
  log_success "Ladder finished: ${out_dir} (raw_ok=${RAW_OK}, k6_exit=${K6_EXIT_CODE:-?}, export_ok=${export_ok})"
  log_warn "Remember: az aks stop --resource-group ecommerce --name ecommerce-aks"
}

pilot_main() {
  local cmd="${1:-}"
  shift || true
  case "${cmd}" in
    run) cmd_run "$@" ;;
    ladder) cmd_ladder "$@" ;;
    *)
      sed -n '2,40p' "${BASH_SOURCE[0]}" | grep -E '^# ?' | sed -E 's/^# ?//'
      exit 1
      ;;
  esac
}

# `exit` on the same line: bash never reads past this point, so editing this
# file while a multi-hour pilot is running cannot inject commands into it.
pilot_main "$@"; exit $?
