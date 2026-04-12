# Experiment Anomaly Detection Guide

A comprehensive checklist of patterns to watch for during the 180-run experiment. Organized by severity — from experiment-invalidating to informational.

---

## Tier 1: 🔴 Critical — Experiment Is Invalid, Must Re-run

These anomalies mean the data from this run is **unusable**. Discard and re-run.

---

### A1. k6 Did Not Achieve Target RPS

**What it looks like:**
- k6 output shows `http_reqs` rate significantly below target (e.g., 140 RPS when 200 was configured)
- `dropped_iterations` counter is > 0 in k6 output

**Where to detect:**
```bash
# In k6-output.log after each run, look for:
grep "http_reqs" experiment-results/{service}/{config}/{pattern}/rep{N}/k6-output.log
grep "dropped_iterations" experiment-results/{service}/{config}/{pattern}/rep{N}/k6-output.log
```

**Root cause:** k6 pod is CPU-starved. The Kubernetes scheduler placed it on a loaded node, and the 500m CPU limit isn't enough to generate 200 RPS.

**How to fix:**
- Check `kubectl top pod` for k6 during a pilot
- If k6 hits its CPU limit, increase to `cpu: "1000m"` in k6 job spec
- Or add `nodeSelector` to schedule k6 on a specific node

**Threshold:** If achieved RPS is >10% below target, **discard and re-run**.

---

### A2. Prometheus Scrape Gaps During Test Window

**What it looks like:**
- `prom_http_requests_rate.json` has null/empty data points during the test window
- Prometheus Targets page shows scrape duration > 5s or state "DOWN"
- KEDA/HPA didn't scale even though k6 was sending 200 RPS

**Where to detect:**
```bash
# Check for gaps in the Prometheus export. Healthy = continuous data every 15s.
# If there's a 30-60s gap: Prometheus missed 2-4 scrapes.
cat experiment-results/{service}/{config}/{pattern}/rep{N}/prom_http_requests_rate.json | \
  python3 -c "
import json, sys
data = json.load(sys.stdin)
values = data.get('data',{}).get('result',[{}])[0].get('values',[])
for i in range(1, len(values)):
    gap = float(values[i][0]) - float(values[i-1][0])
    if gap > 20:  # Expected 15s, flag anything > 20s
        print(f'⚠️  GAP: {gap:.0f}s at timestamp {values[i][0]}')
"
```

**Root cause:** Prometheus pod is BestEffort (no resource requests) and got CPU-throttled.

**How to fix:** Add resource requests to Prometheus deployment:
```yaml
resources:
  requests:
    cpu: "100m"
    memory: "256Mi"
```

**Threshold:** Any gap > 30s during the test window → **discard and re-run**.

---

### A3. Pod CrashLoopBackOff During Test

**What it looks like:**
- `pod-status.txt` shows pods in `CrashLoopBackOff` or `Error` state
- k6 gets HTTP 502/503 responses (gateway can't reach backend)
- `k8s-events.txt` shows `OOMKilled` or `BackOff` events

**Where to detect:**
```bash
# Check for crashes in run results
grep -i "crash\|oom\|error\|backoff" experiment-results/{service}/{config}/{pattern}/rep{N}/k8s-events.txt
grep -i "Restart" experiment-results/{service}/{config}/{pattern}/rep{N}/pod-status.txt
```

**Root cause options:**
- **OOMKilled**: Memory limit (256Mi) too low under load. Product-service loading large result sets, or auth-service bcrypt consuming memory.
- **DB connection error**: PostgreSQL `max_connections` exhausted (should be fixed at 200, but verify).
- **Unhandled exception**: Application bug triggered by specific request pattern.

**How to fix:**
- OOM: Increase memory limit to `512Mi`
- DB: Check `kubectl exec -n ecommerce postgres-pod -- psql -c "SELECT count(*) FROM pg_stat_activity;"`
- Bug: Check pod logs `kubectl logs {crashed-pod} --previous`

**Threshold:** Any pod crash during test window → **discard and re-run**.

---

### A4. Wrong Number of Replicas at Test Start

**What it looks like:**
- Run claims to be B1 (1 replica) but starts with 3 pods
- Previous HPA/ScaledObject wasn't fully cleaned up
- `pod-status.txt` shows more pods than expected at start

**Where to detect:**
```bash
# The script already logs this, but double-check:
# For B1/H1/H2/H3/K1 configs, starting replica count should be 1
# For B2, starting replica count should be 5
```

**Root cause:** The `cleanup_autoscalers()` function didn't fully delete the previous autoscaler, or the 60s wait wasn't long enough for KEDA to scale down.

**How to fix:** The script already handles this, but if it happens:
- Increase `RESET_WAIT` from 60 to 90 seconds
- Add explicit `kubectl wait --for=delete` for ScaledObject

**Threshold:** Starting replicas ≠ expected → **discard and re-run**.

---

### A5. KEDA ScaledObject Shows `READY: False`

**What it looks like:**
- `keda-status.yaml` shows condition `Ready: False`
- KEDA never scales despite 200 RPS hitting the service
- KEDA operator logs show query errors

**Where to detect:**
```bash
# Check after applying K1 config
grep -A3 "Ready" experiment-results/{service}/{config}/{pattern}/rep{N}/keda-status.yaml
# If it shows Ready: False, the entire K1 run is invalid
```

**Root cause:** Prometheus query returns `NaN` or empty result. Usually a label mismatch (`job` vs `service` vs `app`).

**How to fix:** Manually run the KEDA query in Prometheus UI and check the result. Fix the label selector in `k1-keda.yaml`.

**Threshold:** K1 config with `Ready: False` → **discard and re-run** after fixing.

---

## Tier 2: 🟡 Warning — Data May Be Contaminated

These anomalies don't necessarily invalidate the run, but you must note them and decide per-case.

---

### B1. High Error Rate (>5%) But Service Didn't Crash

**What it looks like:**
- k6 reports `http_req_failed` rate > 5%
- All errors are HTTP 429 (rate limited) or 503 (readiness probe failing)
- No pod crashes

**Where to detect:**
```bash
grep "http_req_failed" experiment-results/{service}/{config}/{pattern}/rep{N}/k6-output.log
# Expected: rate < 0.05 (5%)
# For B1 under high load: rate > 5% is EXPECTED (this is the degradation finding)
```

**How to interpret:**
- **B1 with high errors**: ✅ Expected. Under-provisioned service degrades — this IS the baseline.
- **H1/H2 with high errors for product-service**: ✅ Expected. CPU-based HPA doesn't trigger for I/O-bound service.
- **K1 with high errors**: ⚠️ Unexpected. KEDA should have scaled. Check if KEDA is actually running.
- **B2 with high errors**: 🔴 Unexpected. 5 replicas should handle 200 RPS. Investigate.

**Action:** Note the error rate in results. Only re-run if the pattern is unexpected for the config.

---

### B2. k6 Threshold Failed (Job Exit Code ≠ 0)

**What it looks like:**
- k6 job completes but exits with code 99 (threshold violation)
- Script logs: "k6 job did not complete cleanly"

**How to interpret:**
- The k6 thresholds are `p(95) < 2000ms` and `error_rate < 5%`
- **B1 failing thresholds**: ✅ Expected — under-provisioned service
- **H1 failing for product-service**: ✅ Expected — CPU HPA doesn't trigger
- **K1 failing thresholds**: ⚠️ Investigate — KEDA should have helped

**Action:** The script already handles this (continues despite non-zero exit). The threshold failure itself is data.

---

### B3. Wildly Inconsistent Results Across Repetitions

**What it looks like:**
- Rep 1-3 show p95 latency of ~200ms, but Rep 4 shows 2000ms
- One rep has 10× the error rate of others
- Replica count timeline is completely different in one rep

**Where to detect:**
```bash
# Compare p95 latency across reps for the same config:
for rep in 1 2 3 4 5; do
  echo "Rep ${rep}:"
  grep "p(95)" experiment-results/product-service/h1/gradual/rep${rep}/k6-output.log
done
# If one rep is >3× the median of others, flag it.
```

**Root cause options:**
- **Node scheduling**: One run's pods were scheduled on a different node with higher contention
- **GC/compaction**: PostgreSQL ran autovacuum during the test
- **Network blip**: AKS internal network had transient latency
- **Resource pressure**: Another tenant on the Azure host caused CPU steal

**Action:**
- If 1 out of 5 reps is an outlier: treat as statistical outlier, report it but you can exclude from median
- If 2+ out of 5 are outliers: something systemic is wrong, investigate before continuing
- The 5-repetition design specifically accounts for this — Wilcoxon test is robust to outliers

---

### B4. HPA/KEDA Thrashing (Rapid Scale-Up/Down Cycles)

**What it looks like:**
- `k8s-events.txt` shows multiple scale-up and scale-down events within 60 seconds
- Replica count oscillates: 1→3→1→4→2→5→2
- Latency spikes correlate with each scale change

**Where to detect:**
```bash
# Count scaling events per run
grep -c "Scaled\|SuccessfulRescale" experiment-results/{service}/{config}/{pattern}/rep{N}/k8s-events.txt
# Normal: 1-4 events. Thrashing: >8 events in a 12-minute window.
```

**Root cause:** The stabilization window is too short, or the threshold is near the tipping point where the service oscillates between above/below threshold.

**How to interpret:**
- **H1 thrashing**: Important finding — default HPA behavior causes instability
- **H2 thrashing**: Unexpected — H2 has `stabilizationWindowSeconds: 30`
- **K1 thrashing**: Unexpected — KEDA has `cooldownPeriod: 30`

**Action:** If an autoscaler is thrashing, this is VALID DATA (important finding for the thesis). Do not re-run. Report the event count as part of "Scaling Event Count" KPI.

---

### B5. Prometheus Metric Shows Flat Zero During Load

**What it looks like:**
- `prom_http_requests_rate.json` shows 0 RPS even though k6 is sending 200 RPS
- `prom_cpu_usage.json` shows 0% CPU during load

**Where to detect:**
```bash
# Quick check: does Prometheus data have non-zero values?
python3 -c "
import json
data = json.load(open('experiment-results/{service}/{config}/{pattern}/rep{N}/prom_http_requests_rate.json'))
values = data.get('data',{}).get('result',[{}])[0].get('values',[])
non_zero = [v for v in values if float(v[1]) > 0]
print(f'Non-zero data points: {len(non_zero)}/{len(values)}')
if len(non_zero) == 0:
    print('🔴 ALL ZEROS — Prometheus is not scraping this service!')
"
```

**Root cause options:**
- **Label mismatch**: Prometheus query uses `job="product-service"` but the actual label is `app="product-service"`
- **Service not exposing metrics**: The `/metrics` endpoint is broken or the instrumentator isn't attached
- **Wrong namespace**: Prometheus is scraping `default` namespace, pods are in `ecommerce`

**Action:** This is a setup issue. Fix and re-run ALL affected runs.

---

### B6. Gateway Rate Limiting Auth-Service Tests

**What it looks like:**
- Auth-service tests show many HTTP 429 (Too Many Requests)
- But only when `TARGET_URL` points to the gateway instead of auth-service directly
- Product-service tests (also through gateway) don't show 429s

**Where to detect:**
```bash
# Check for 429s in k6 output
grep "429\|rate.limit" experiment-results/auth-service/{config}/{pattern}/rep{N}/k6-output.log
```

**Root cause:** k6 auth-service job is routing through the gateway instead of direct. The gateway has a 5/min rate limiter on `POST /auth/login`.

**How to verify:** Check k6 job `TARGET_URL`:
```bash
kubectl get job k6-auth-test-gradual -n ecommerce -o yaml | grep TARGET_URL
# Should be: http://auth-service.ecommerce.svc.cluster.local:8001
# NOT: http://api-gateway.ecommerce.svc.cluster.local:80
```

**Action:** This should already be fixed (k6-auth-job.yaml targets auth-service directly). If 429s appear, verify the job template.

---

## Tier 3: 🟢 Informational — Expected But Verify

These are behaviors that SHOULD happen. If they DON'T, something is wrong.

---

### C1. CPU-Based HPA Never Scales for Product-Service

**What it looks like:**
- H1 and H2 configs: `prom_replica_count.json` stays at 1 the whole test
- No scaling events in `k8s-events.txt`
- Meanwhile, latency climbs from 50ms → 500ms → timeouts

**This is the thesis's central finding.** Product-service is I/O-bound → CPU stays low → HPA never triggers. If H1/H2 DO scale for product-service, your hypothesis is disproven (which is also a valid finding, but investigate why CPU is high).

**Check:** `prom_cpu_usage.json` should show < 30% CPU for product-service under 200 RPS.

---

### C2. All Autoscalers Scale for Auth-Service

**What it looks like:**
- H1, H2, H3, K1 all scale auth-service from 1→3-5 replicas
- CPU usage for auth-service reaches 50-70%+ (bcrypt is CPU-heavy)

**This is the control scenario.** For CPU-bound services, CPU-based HPA should work well. If H1/H2 DON'T scale auth-service, bcrypt isn't generating enough CPU load. Check:
```bash
kubectl top pod -l app=auth-service -n ecommerce
# During 200 RPS of POST /auth/login, CPU should be > 50% per pod
```

---

### C3. B2 Has Lowest Latency But Highest Cost

**What it looks like:**
- B2 (5 replicas) consistently has the best p95 latency
- But Resource Cost Index is 5× higher than B1

**This is expected and forms the Pareto frontier upper-right point.** If B2 does NOT have the lowest latency, something is wrong (DB bottleneck? Network?).

---

### C4. H3 ≈ K1 Performance (Within Statistical Noise)

**What it looks like:**
- H3 (HPA + request-rate) and K1 (KEDA + request-rate) produce similar p95 latency and replica count
- Difference is within 1 standard deviation across 5 reps

**This is outcome #1 from the blueprint: "The metric type is what matters, not the engine."** This is a perfectly valid finding. Report it with confidence — the factorial design proves it.

---

## Post-Run Validation Script

Add this to your workflow. Run it after each batch of experiments to catch anomalies early:

```bash
#!/usr/bin/env bash
# Quick anomaly scan across completed runs
# Usage: bash scripts/validate-results.sh

RESULTS_DIR="./experiment-results"

echo "=== EXPERIMENT RESULTS VALIDATION ==="
echo ""

TOTAL=0
ISSUES=0

for metadata in $(find "${RESULTS_DIR}" -name "metadata.json" | sort); do
  dir=$(dirname "${metadata}")
  run_id=$(python3 -c "import json; print(json.load(open('${metadata}'))['run_id'])")
  TOTAL=$((TOTAL + 1))

  issues=""

  # Check 1: k6 output exists and has data
  if [[ ! -f "${dir}/k6-output.log" ]] || [[ ! -s "${dir}/k6-output.log" ]]; then
    issues="${issues} [NO_K6_OUTPUT]"
  fi

  # Check 2: k6 achieved target RPS (look for dropped iterations)
  if grep -q "dropped_iterations" "${dir}/k6-output.log" 2>/dev/null; then
    dropped=$(grep "dropped_iterations" "${dir}/k6-output.log" | grep -oP '\d+' | head -1)
    if [[ "${dropped}" -gt 0 ]]; then
      issues="${issues} [DROPPED_ITERATIONS:${dropped}]"
    fi
  fi

  # Check 3: Error rate
  if grep -q "http_req_failed" "${dir}/k6-output.log" 2>/dev/null; then
    fail_rate=$(grep "http_req_failed" "${dir}/k6-output.log" | grep -oP '[\d.]+%' | head -1)
    issues="${issues} [ERR:${fail_rate}]"
  fi

  # Check 4: Prometheus data exists
  if [[ ! -f "${dir}/prom_http_requests_rate.json" ]] || [[ ! -s "${dir}/prom_http_requests_rate.json" ]]; then
    issues="${issues} [NO_PROM_DATA]"
  fi

  # Check 5: Run duration sanity (should be 600-1200s)
  duration=$(python3 -c "import json; print(json.load(open('${metadata}'))['duration_seconds'])" 2>/dev/null)
  if [[ -n "${duration}" ]]; then
    if [[ "${duration}" -lt 600 ]]; then
      issues="${issues} [TOO_SHORT:${duration}s]"
    elif [[ "${duration}" -gt 1200 ]]; then
      issues="${issues} [TOO_LONG:${duration}s]"
    fi
  fi

  # Report
  if [[ -n "${issues}" ]]; then
    ISSUES=$((ISSUES + 1))
    echo "⚠️  ${run_id}: ${issues}"
  fi
done

echo ""
echo "=== Summary: ${TOTAL} runs checked, ${ISSUES} with potential issues ==="
```

---

## Cross-Repetition Consistency Check

Run this after all 5 reps of a config are complete:

```bash
#!/usr/bin/env bash
# Compare p95 latency across repetitions for outlier detection
# Usage: bash scripts/check-consistency.sh product-service h1 gradual

SERVICE=$1
CONFIG=$2
PATTERN=$3
BASE="./experiment-results/${SERVICE}/${CONFIG}/${PATTERN}"

echo "=== Consistency Check: ${SERVICE} / ${CONFIG} / ${PATTERN} ==="

latencies=()
for rep in 1 2 3 4 5; do
  p95=$(grep "http_req_duration" "${BASE}/rep${rep}/k6-output.log" 2>/dev/null | \
        grep "p(95)" | grep -oP '[\d.]+' | tail -1)
  if [[ -n "${p95}" ]]; then
    echo "  Rep ${rep}: p95 = ${p95}ms"
    latencies+=("${p95}")
  else
    echo "  Rep ${rep}: ⚠️ NO DATA"
  fi
done

# Check for outliers (>3× median)
if [[ ${#latencies[@]} -eq 5 ]]; then
  python3 -c "
import statistics
vals = [${latencies[0]}, ${latencies[1]}, ${latencies[2]}, ${latencies[3]}, ${latencies[4]}]
median = statistics.median(vals)
stdev = statistics.stdev(vals)
cv = (stdev / median) * 100 if median > 0 else 0
print(f'  Median: {median:.1f}ms, StdDev: {stdev:.1f}ms, CV: {cv:.1f}%')
if cv > 30:
    print(f'  🔴 HIGH VARIANCE (CV > 30%) — investigate or add more reps')
elif cv > 15:
    print(f'  🟡 MODERATE VARIANCE (CV > 15%) — note in results')
else:
    print(f'  ✅ LOW VARIANCE (CV < 15%) — consistent')
outliers = [v for v in vals if abs(v - median) > 3 * stdev]
if outliers:
    print(f'  ⚠️  OUTLIERS (>3σ): {outliers}')
"
fi
```

---

## Quick-Reference Decision Matrix

When you encounter an anomaly, use this table:

| Anomaly | B1 | B2 | H1/H2 (product) | H1/H2 (auth) | H3 | K1 |
|---------|----|----|-----------------|--------------|----|----|
| **High error rate (>5%)** | ✅ Expected | 🔴 Investigate | ✅ Expected (no scaling) | 🟡 Check CPU | 🟡 Check metric | 🟡 Check KEDA |
| **HPA never scales** | N/A | N/A | ✅ Expected (I/O-bound) | 🔴 Bug (should trigger) | 🔴 Adapter broken | N/A |
| **KEDA never scales** | N/A | N/A | N/A | N/A | N/A | 🔴 Query broken |
| **p95 > 2000ms** | ✅ Expected | 🔴 Investigate | ✅ Expected | 🟡 Borderline | 🟡 Borderline | 🟡 Borderline |
| **0% CPU under load** | 🔴 Metric broken | 🔴 Metric broken | 🔴 Metric broken | 🔴 Metric broken | 🔴 Metric broken | 🔴 Metric broken |
| **Pod crashes** | 🔴 Re-run | 🔴 Re-run | 🔴 Re-run | 🔴 Re-run | 🔴 Re-run | 🔴 Re-run |
| **k6 under-delivers RPS** | 🔴 Re-run | 🔴 Re-run | 🔴 Re-run | 🔴 Re-run | 🔴 Re-run | 🔴 Re-run |
| **Prom scrape gap >30s** | 🟡 Note it | 🟡 Note it | 🟡 Note it | 🟡 Note it | 🔴 Re-run (H3 needs prom) | 🔴 Re-run (K1 needs prom) |
| **Thrashing (>8 events)** | N/A | N/A | ✅ Data (finding!) | ✅ Data | ✅ Data | ✅ Data |
| **Rep variance CV>30%** | 🟡 Add reps | 🟡 Add reps | 🟡 Add reps | 🟡 Add reps | 🟡 Add reps | 🟡 Add reps |

---

## Pilot Run Checklist

Before the full 180-run experiment, run exactly **1 rep** of each config for product-service (6 runs, ~90 min) and verify:

- [ ] k6 achieves target RPS (no `dropped_iterations`)
- [ ] Prometheus has continuous 15s data (no gaps)
- [ ] B1: Service degrades, HPA does nothing — ✅ expected
- [ ] B2: All 5 pods serve traffic, low latency
- [ ] H1: HPA exists but doesn't trigger (CPU < threshold) — ✅ expected for product
- [ ] H3: HPA triggers based on custom metric (check `kubectl get hpa` — targets should show real numbers, not `<unknown>`)
- [ ] K1: KEDA ScaledObject shows `Ready: True`, scales up during load
- [ ] No pod crashes across all 6 runs
- [ ] Results directory structure is correct (all 11 files per run)
- [ ] `validate-results.sh` shows no issues
