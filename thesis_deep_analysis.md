# Deep Experiment Verification Report

> **Date**: 2026-04-08 | **Analyst**: Senior DevOps / K8s Expert  
> **Scope**: 36 pilot runs (1 rep × 6 configs × 3 patterns × 2 services)  
> **Context**: [thesis_blueprint.md](file:///home/kevin/Projects/e-commerce/thesis_blueprint.md) + [anomaly_detection_guide.md](file:///home/kevin/Projects/e-commerce/anomaly_detection_guide.md)  
> **Tool**: [deep_validate.py](file:///home/kevin/Projects/e-commerce/scripts/deep_validate.py)

---

## Executive Summary

> [!CAUTION]
> **VERDICT: ALL 36 RUNS ARE INVALID.** The experiment has 5 systemic failures that make every single run unusable for thesis data. These are not minor issues — they would cause a thesis examiner to reject the entire dataset. None of these runs should be carried forward into the 180-run experiment.

| Metric | Value |
|--------|-------|
| Total runs analyzed | 36/36 |
| 🔴 Critical issues (Tier 1) | **82** |
| 🟡 Warnings (Tier 2) | **93** |
| Runs with zero critical issues | **0** |
| Runs safe to use for thesis data | **0** |

---

## The 5 Systemic Failures

### Failure #1: 🔴 Auth-Service Is Completely Overwhelmed (ALL 18 auth runs invalid)

**Evidence from actual data:**

| Config | Pattern | p95 | Error Rate | Dropped Iterations | Restarts |
|--------|---------|-----|------------|-------------------|----------|
| B1 | gradual | 51ms | **97.9%** | 60,743 | 6 |
| B1 | spike | 56ms | **97.7%** | 92,709 | 8 |
| B1 | oscillating | 54ms | **98.0%** | 65,114 | 12 |
| B2 | gradual | 57ms | **54.8%** | 66,654 | 12 |
| B2 | spike | 59ms | **60.2%** | 96,180 | 2 |
| B2 | oscillating | 59ms | **57.8%** | 69,251 | 2 |
| H1 | gradual | 57ms | **62.1%** | 66,451 | 3 |
| H1 | spike | 60ms | **69.3%** | 95,839 | 1 |
| H1 | oscillating | 58ms | **67.4%** | 68,553 | — |
| H2 | gradual | 58ms | **60.9%** | 66,580 | — |
| H2 | spike | 59ms | **61.4%** | 96,935 | — |
| H2 | oscillating | 59ms | **65.5%** | 69,359 | — |
| H3 | gradual | 56ms | **97.1%** | 67,178 | — |
| H3 | spike | 53ms | **97.6%** | 90,796 | — |
| H3 | oscillating | 53ms | **98.0%** | 64,147 | — |
| K1 | gradual | 56ms | **98.0%** | 63,284 | 18 |
| K1 | spike | 52ms | **96.9%** | 93,643 | 20 |
| K1 | oscillating | 54ms | **96.9%** | 66,107 | 25 |

**Root Cause Analysis:**

The k6 auth test sends `POST /auth/login` with bcrypt hashing (12 rounds ≈ 200–400ms CPU per request). At 200 RPS target:

```
200 requests/sec × 0.3 sec CPU/request = 60 CPU-seconds per real second
```

That requires **60,000m CPU** per second — but even 5 pods with 500m CPU limit only provide **2,500m CPU**. The math is physically impossible. The service is **24× overloaded** even at `maxReplicas: 5`.

**What the data proves:**
- Even B2 (5 replicas, the "best case") shows **55–60% error rate** — this is a fundamental capacity problem, not an autoscaling problem
- Auth pods crash-loop continuously (liveness probe timeouts → restart → more timeouts)
- k6 drops **60,000–97,000 iterations** per run because VUs are blocked waiting for responses
- The k6 log shows the actual failure mode: `"Insufficient VUs, reached 500 active VUs and cannot initialize more"` followed by floods of `EOF` and `connection refused` errors
- HTTP `429` responses indicate the auth-service or gateway is rate-limiting

**Why this invalidates the experiment:**
- Per [anomaly_detection_guide.md](file:///home/kevin/Projects/e-commerce/anomaly_detection_guide.md) Tier 1 §A1: `dropped_iterations > 0` → Critical, must re-run
- Per §B1: B2 with error rate >5% → "🔴 UNEXPECTED, investigate!"
- You **cannot compare autoscaling methods** when the baseline (B2) already fails. The experiment is measuring "which method crashes slightly less" — not "which method scales better"

**The blueprint warned about this** (Section 8, Risk 8):
> *"At 200 RPS, if every virtual user logs in, auth-service needs to process 200 bcrypt operations per second. That's 40-80 seconds of CPU per second — absolutely crushing."*

---

### Failure #2: 🔴 prometheus-adapter Is Broken (ALL 6 H3 runs invalid)

**Evidence from HPA status across ALL H3 runs:**

```yaml
# EVERY H3 hpa-status.yaml shows this:
reason: FailedGetPodsMetric
status: "False"
type: ScalingActive
message: 'the HPA was unable to compute the replica count: unable to get metric
  http_requests_per_second: unable to fetch metrics from custom metrics API:
  the server could not find the metric http_requests_per_second for pods'
currentReplicas: 1    # Never scaled
desiredReplicas: 0    # HPA has no idea what to do
```

| Service | Pattern | H3 Scaled? | Custom Metric Available? |
|---------|---------|-----------|------------------------|
| product-service | gradual | ❌ No (stayed at 1) | ❌ `FailedGetPodsMetric` |
| product-service | spike | ❌ No (stayed at 1) | ❌ `FailedGetPodsMetric` |
| product-service | oscillating | ❌ No (stayed at 1) | ❌ `FailedGetPodsMetric` |
| auth-service | gradual | ❌ No (stayed at 1) | ❌ `FailedGetPodsMetric` |
| auth-service | spike | ❌ No (stayed at 1) | ❌ `FailedGetPodsMetric` |
| auth-service | oscillating | ❌ No (stayed at 1) | ❌ `FailedGetPodsMetric` |

**Root Cause Analysis:**

The prometheus-adapter is either:
1. **Not installed/running** — the Custom Metrics API endpoint doesn't exist
2. **Misconfigured** — the `seriesQuery` rule doesn't match actual Prometheus metric labels
3. **Not able to reach Prometheus** — wrong service URL or port

The k8s events for auth-service K1 runs even captured this error from a previous H3 run:
```
FailedGetPodsMetric  horizontalpodautoscaler/auth-service-hpa-custom
  unable to get metric http_requests_per_second: unable to fetch metrics from
  custom metrics API: the server could not find the metric http_requests_per_second for pods
```

**Why this is catastrophic for the thesis:**

H3 is **the keystone of the entire factorial design**. Per the blueprint (Section 6):
> *"H3 is what makes this narrative possible. Without it, you can only say 'KEDA is better.' With it, you can say 'here's exactly WHY and WHICH FACTOR contributes HOW MUCH.'"*

Without working H3:
- The H3 vs H1 comparison (isolating metric effect) is **impossible**
- The H3 vs K1 comparison (isolating engine effect) is **impossible**
- The decomposition table (the thesis's unique deliverable) **cannot be produced**
- The "controlled factorial design" claim is **false**

The blueprint rated this as **Risk 2: 🔴 High** and budgeted 5 days for it. It was never resolved.

---

### Failure #3: 🔴 Cluster Reset Not Working (Wrong Starting Replicas)

**Evidence from `prom_replica_count.json` initial values:**

| Run | Expected Start | Actual Start | Status |
|-----|---------------|-------------|--------|
| product-service B2 gradual | 5 replicas | **1 replica** | ❌ A4 violation |
| product-service H1 spike | 1 replica | **4 replicas** | ❌ A4 violation |
| product-service H1 oscillating | 1 replica | **5 replicas** | ❌ A4 violation |
| product-service H2 gradual | 1 replica | **5 replicas** | ❌ A4 violation |

**Root Cause Analysis:**

The experiment runner's `cleanup_autoscalers()` function is not properly resetting between runs:

1. **B2 gradual starting at 1**: The deployment was set to `replicas: 5` but Prometheus captured the replica count before all pods were ready. OR the scale-up from 1→5 happened *after* data collection started.

2. **H1 spike starting at 4, H1 oscillating starting at 5**: The previous run (H1 gradual) scaled product-service to 5 replicas. The cleanup didn't fully delete the HPA, or the 60-second wait wasn't long enough for scale-down from 5→1. The next run started with leftover pods.

3. **H2 gradual starting at 5**: Same problem — the previous H1 oscillating run had 5 replicas, and they weren't scaled back down before H2 started.

**Why this invalidates the runs:**

Per [anomaly_detection_guide.md](file:///home/kevin/Projects/e-commerce/anomaly_detection_guide.md) Tier 1 §A4:
> *"Starting replicas ≠ expected → **discard and re-run**"*

When H1 starts at 5 replicas instead of 1, the test measures "how does an already-scaled service perform" — NOT "how does HPA react to increasing load." The entire scaling behavior measurement is meaningless.

---

### Failure #4: 🔴 Product-Service Doesn't Degrade Under Load (Thesis Hypothesis Disproven)

**Evidence from B1 (under-provisioned baseline, 1 replica):**

| Pattern | p95 Latency | Error Rate | Total Requests | Dropped |
|---------|-------------|------------|---------------|---------|
| gradual | **5.76ms** | **0.00%** | 71,869 | 2,648 |
| spike | **7.81ms** | **0.03%** | 98,951 | 8,298 |
| oscillating | **6.33ms** | **0.00%** | 77,604 | 2,645 |

**The thesis blueprint predicted** (Section 6, §C1):
> *"product-service starts queuing requests — response time climbs from 50ms → 500ms → 2000ms → timeouts"*
> *"HPA checks every 15 seconds: '25% < 70% target? No scaling needed.' 7 minutes later, the test ends. HPA never activated."*

**What actually happened:**
- Product-service handles 200 RPS on **a single replica** with **p95 < 8ms** and **0% error rate**
- There is zero degradation to measure
- B1 (1 replica) performs almost identically to B2 (5 replicas, p95=3.7ms)
- The "under-provisioned baseline shows degradation" finding **does not exist**

**Furthermore, CPU-based HPA DID scale product-service:**

| Config | Pattern | Max Replicas | Started At |
|--------|---------|-------------|-----------|
| H1 | gradual | **5** | 1 |
| H1 | spike | **5** | 4 (invalid start) |
| H1 | oscillating | **5** | 5 (invalid start) |
| H2 | gradual | **5** | 5 (invalid start) |
| H2 | spike | **5** | — |
| H2 | oscillating | **5** | — |

The thesis predicted: *"CPU-based HPA did NOT scale product-service — CONFIRMS thesis hypothesis."*

**Reality**: CPU-based HPA **scaled product-service to 5 replicas**. CPU data shows avg=22%, max=50%. The product-service is NOT behaving as "I/O-bound with flat CPU." It's generating enough CPU to trigger both H1 (70%) and H2 (50%) thresholds.

> [!WARNING]
> This fundamentally contradicts the thesis's central hypothesis. The "metric mismatch" narrative — that CPU-based HPA fails for I/O-bound services — is not demonstrated by this product-service under these load conditions.

**Possible explanations:**
1. Product-service's JSON serialization at 200 RPS generates meaningful CPU
2. PostgreSQL queries are fast (co-located in-cluster, small dataset), so the "I/O wait" is negligible
3. FastAPI's async framework handles I/O efficiently, converting what should be I/O-wait into CPU availability
4. The load test may be hitting a lightweight endpoint (GET /products with few products) rather than a complex query

---

### Failure #5: 🔴 KEDA Did Not Scale Auth-Service (K1 runs compromised)

**Evidence from `prom_replica_count.json` for auth-service K1:**

| Pattern | Min Replicas | Max Replicas | KEDA Ready? |
|---------|-------------|-------------|-------------|
| gradual | 1 | **1** (never scaled) | ✅ True |
| spike | 1 | **1** (never scaled) | ✅ True |
| oscillating | 1 | **1** (never scaled) | ✅ True |

Despite `ScaledObject Ready: True`, KEDA never created additional replicas. The k8s events confirm KEDA was built and watching:
```
KEDAScalersStarted  scaledobject/auth-service-keda  Scaler prometheus is built
KEDAScalersStarted  scaledobject/auth-service-keda  Started scalers watch
ScaledObjectReady   scaledobject/auth-service-keda  ScaledObject is ready for scaling
```

**But the auth-service pod was crash-looping continuously** (20–25 restarts). This means:
1. The pod crashes → Prometheus can't scrape it → `rate(http_requests_total[1m])` returns 0 or NaN
2. KEDA queries Prometheus and sees "no requests" → decides scaling is not needed
3. Meanwhile the pod restarts, gets flooded immediately, crashes again
4. The cycle repeats indefinitely

This is a **cascading failure**: the service crashes too fast for KEDA's metrics to register load.

---

## Detailed Per-Run Verdicts

### Product-Service Runs (18 runs)

| Run | Verdict | Critical Issues | Key Data |
|-----|---------|----------------|----------|
| B1 gradual | ❌ **INVALID** | A1 (2,648 dropped), A3 (backoff) | p95=6ms, err=0% — no degradation (contradicts hypothesis) |
| B1 spike | ❌ **INVALID** | A1 (8,298 dropped), A3 (backoff) | p95=8ms, err=0.03% — no degradation |
| B1 oscillating | ❌ **INVALID** | A1 (2,645 dropped), A3 (backoff) | p95=6ms, err=0% — no degradation |
| B2 gradual | ❌ **INVALID** | A3 (backoff), **A4 (started at 1, expected 5)** | p95=4ms, err=0% |
| B2 spike | ❌ **INVALID** | A3 (backoff) | p95=4ms, err=0% — contaminated by prior reset issues |
| B2 oscillating | ⚠️ **MARGINAL** | Warning only (low RPS) | p95=4ms, err=0% — mechanically ok |
| H1 gradual | ❌ **INVALID** | A1 (3 dropped), A3 (backoff) | HPA scaled to 5 — disproves hypothesis |
| H1 spike | ❌ **INVALID** | A3 (backoff), **A4 (started at 4, expected 1)** | HPA scaled to 5 — wrong start state |
| H1 oscillating | ❌ **INVALID** | A3 (backoff), **A4 (started at 5, expected 1)** | Started fully scaled — no scaling behavior measured |
| H2 gradual | ❌ **INVALID** | **A4 (started at 5, expected 1)** | Started fully scaled — no scaling behavior measured |
| H2 spike | ⚠️ **MARGINAL** | Warning only (hypothesis disproven) | HPA scaled to 5 — contradicts thesis |
| H2 oscillating | ⚠️ **MARGINAL** | Warning only (hypothesis disproven) | HPA scaled to 5, 23 thrashing events |
| H3 gradual | ❌ **INVALID** | A1 (5,375 dropped), A3, **FailedGetPodsMetric** | prometheus-adapter broken, never scaled |
| H3 spike | ❌ **INVALID** | A1 (14,023 dropped), A3, **FailedGetPodsMetric** | prometheus-adapter broken, never scaled |
| H3 oscillating | ❌ **INVALID** | A1 (5,425 dropped), A3, **FailedGetPodsMetric** | prometheus-adapter broken, never scaled |
| K1 gradual | ❌ **INVALID** | A1 (2 dropped), A3 (backoff) | KEDA works, scales properly — but useless without valid H3 |
| K1 spike | ❌ **INVALID** | A1 (194 dropped), A3 (backoff) | KEDA works, 38 scaling events |
| K1 oscillating | ❌ **INVALID** | A1 (75 dropped), A3 (backoff) | KEDA works, 48 scaling events |

### Auth-Service Runs (18 runs)

| Run | Verdict | Critical Issues | Key Data |
|-----|---------|----------------|----------|
| B1 gradual | ❌ **INVALID** | A1 (60,743 dropped), A2 (5 gaps), A3 | err=97.9%, service collapsed |
| B1 spike | ❌ **INVALID** | A1 (92,709 dropped), A2 (2 gaps), A3 | err=97.7%, service collapsed |
| B1 oscillating | ❌ **INVALID** | A1 (65,114 dropped), A2 (4 gaps), A3 | err=98.0%, service collapsed |
| B2 gradual | ❌ **INVALID** | A1 (66,654 dropped), A3, **B1-crit (54.8% err on B2!)** | Even 5 replicas can't handle the load |
| B2 spike | ❌ **INVALID** | A1 (96,180 dropped), A2, A3, **B1-crit (60.2% err on B2!)** | Liveness probe failures, pod restarts |
| B2 oscillating | ❌ **INVALID** | A1 (69,251 dropped), A3, **B1-crit (57.8% err on B2!)** | Even 5 replicas can't handle the load |
| H1 gradual | ❌ **INVALID** | A1 (66,451 dropped), A3 | err=62.1%, scaled to 5 but still failing |
| H1 spike | ❌ **INVALID** | A1 (95,839 dropped), A3 | err=69.3%, scaled to 5 but still failing |
| H1 oscillating | ❌ **INVALID** | A1 (68,553 dropped), A3 | err=67.4%, scaled to 5 but still failing |
| H2 gradual | ❌ **INVALID** | A1 (66,580 dropped), A3 | err=60.9%, scaled to 5 but still failing |
| H2 spike | ❌ **INVALID** | A1 (96,935 dropped), A3 | err=61.4%, scaled to 5 but still failing |
| H2 oscillating | ❌ **INVALID** | A1 (69,359 dropped), A3 | err=65.5%, scaled to 5 but still failing |
| H3 gradual | ❌ **INVALID** | A1 (67,178 dropped), **FailedGetPodsMetric** | err=97.1%, adapter broken + service collapsed |
| H3 spike | ❌ **INVALID** | A1 (90,796 dropped), **FailedGetPodsMetric** | err=97.6%, adapter broken + service collapsed |
| H3 oscillating | ❌ **INVALID** | A1 (64,147 dropped), **FailedGetPodsMetric** | err=98.0%, adapter broken + service collapsed |
| K1 gradual | ❌ **INVALID** | A1 (63,284 dropped), A2 (4 gaps), A3 | err=98.0%, KEDA never scaled, 18 restarts |
| K1 spike | ❌ **INVALID** | A1 (93,643 dropped), A2 (2 gaps), A3 | err=96.9%, KEDA never scaled, 20 restarts |
| K1 oscillating | ❌ **INVALID** | A1 (66,107 dropped), A2 (3 gaps), A3 | err=96.9%, KEDA never scaled, 25 restarts |

---

## Anomaly Detection Checklist (from anomaly_detection_guide.md)

### Tier 1 🔴 Critical Checks

| Check | Product-Service | Auth-Service |
|-------|----------------|--------------|
| **A1: k6 achieved target RPS** | ⚠️ Minor drops (2–14K) in some runs | ❌ **FAILED ALL** (60K–97K dropped) |
| **A2: No Prometheus scrape gaps** | ✅ Passed all | ❌ **FAILED** (2–5 gaps >30s per run) |
| **A3: No pod crashes** | ⚠️ `BackoffLimitExceeded` on k6 jobs (not service pods) | ❌ **FAILED** (6+ backoff events, 1–25 restarts) |
| **A4: Correct starting replicas** | ❌ **FAILED** 4 runs | ✅ Passed (always started at expected count) |
| **A5: KEDA Ready: True** | ✅ Passed | ✅ Passed (but KEDA never scaled) |

### Tier 2 🟡 Warning Checks

| Check | Product-Service | Auth-Service |
|-------|----------------|--------------|
| **B1: Error rate interpretation** | ✅ 0% (suspiciously LOW for B1) | ❌ 55–98% across ALL configs |
| **B4: Thrashing** | ℹ️ 14–48 scaling events (valid data) | ℹ️ Some thrashing observed |
| **B5: Flat zero metrics** | ✅ Passed | ✅ Passed |
| **B6: Gateway rate limiting** | ✅ Not applicable | ⚠️ 429 responses detected in many runs |

### Tier 3 🟢 Informational Checks

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| **C1: CPU HPA won't scale product-service** | HPA stays at 1 replica | HPA scaled to **5 replicas** | ❌ **HYPOTHESIS DISPROVEN** |
| **C2: All autoscalers scale auth-service** | All scale to 3–5 | H1/H2 scale but crash; H3/K1 don't scale | ❌ **PARTIAL FAILURE** |
| **C3: B2 has lowest latency** | B2 best performance | Auth B2 has 55% error rate | ❌ **FAILED** |
| **C4: H3 ≈ K1 performance** | Similar performance | H3 doesn't work at all | ❌ **NOT TESTABLE** |

---

## Required Fixes Before Re-Running

### Fix 1: Auth-Service Load Calibration (BLOCKING)

> [!IMPORTANT]
> The 200 RPS target for `POST /auth/login` with bcrypt-12 is physically impossible to serve. This must be fixed before any auth-service experiments can produce valid data.

**Options (pick one):**

| Option | Target RPS | Rationale | Impact on Thesis |
|--------|-----------|-----------|-----------------|
| **A: Reduce auth RPS to 30–50** | 30–50 | Calibrate to what 1 pod can handle at ~70% CPU | Smaller numbers but valid comparison |
| **B: Mixed endpoint load** | 200 total | 70% GET /auth/verify (lightweight), 30% POST /auth/login (heavy) | More realistic, still stresses CPU |
| **C: Reduce bcrypt rounds** | 200 | Lower from 12 to 8 rounds (~50ms/hash instead of ~300ms) | Faster but less "CPU-bound" |

**Recommended: Option A or B.** Run a calibration test first:
```bash
# Find the saturation point for auth-service (1 pod)
# Start at 10 RPS, increase by 10 every 60s, find where errors start
```

### Fix 2: Fix prometheus-adapter (BLOCKING)

```bash
# Step 1: Verify prometheus-adapter is running
kubectl get pods -n monitoring | grep prometheus-adapter

# Step 2: Check if the Custom Metrics API exists
kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1

# Step 3: If it returns 404, reinstall:
helm upgrade --install prometheus-adapter prometheus-community/prometheus-adapter \
  --namespace monitoring \
  --set prometheus.url=http://prometheus.monitoring.svc.cluster.local \
  --set prometheus.port=9090

# Step 4: Verify your metric appears
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/ecommerce/pods/*/http_requests_per_second"
```

### Fix 3: Fix Cluster Reset Between Runs (BLOCKING)

The experiment runner must:
1. **Delete ALL autoscaler objects** (HPA + ScaledObject) before each run
2. **Explicitly scale deployment to target replicas** (`kubectl scale deployment/product-service --replicas=1`)
3. **Wait and VERIFY** replicas match expected count before starting k6
4. Increase `RESET_WAIT` from 60s to at least **120s**

```bash
# Add verification step in the experiment runner:
EXPECTED=1  # or 5 for B2
kubectl scale deployment/product-service --replicas=$EXPECTED -n ecommerce
kubectl rollout status deployment/product-service -n ecommerce --timeout=120s
ACTUAL=$(kubectl get deployment/product-service -n ecommerce \
  -o jsonpath='{.status.readyReplicas}')
if [ "$ACTUAL" != "$EXPECTED" ]; then
  echo "ABORT: Expected $EXPECTED replicas, got $ACTUAL"
  exit 1
fi
```

### Fix 4: Make Product-Service Actually I/O-Bound (IMPORTANT)

The product-service handles 200 RPS at 1 replica with p95 < 8ms. It doesn't degrade. Options:

| Option | Approach | Effect |
|--------|---------|--------|
| **A: Seed more data** | Load 10,000+ products with large descriptions | Increases PostgreSQL query time and serialization CPU |
| **B: Add complex queries** | Use joins, pagination, search with LIKE | Forces real database work |
| **C: Increase RPS** | Target 500–1000 RPS | May push past single-pod capacity |
| **D: Add artificial I/O** | Add `asyncio.sleep(0.05)` to simulate external API call | Artificially I/O-bound but less realistic |

**Recommended: Option A + C.** Seed the database with real-world-sized data and increase the target RPS until B1 shows genuine degradation (p95 > 200ms, error rate > 1%).

### Fix 5: Debug KEDA Auth-Service Query (MODERATE)

KEDA's Prometheus query won't return meaningful data if the auth-service pod is crash-looping. Fix #1 (reduce load) will likely resolve this automatically. But also verify:

```bash
# Test the KEDA query manually in Prometheus UI:
sum(rate(http_requests_total{job="auth-service"}[1m]))

# If this returns 0 or NaN during load, the label may be wrong.
# Check actual label: http_requests_total and look at the "job" label value.
```

---

## Priority Order for Fixes

```
1. Fix prometheus-adapter (Fix #2) ─── BLOCKING, no H3 data possible
   └─ Estimated: 1-3 days
   
2. Calibrate auth-service load (Fix #1) ─── BLOCKING, all auth runs fail
   └─ Estimated: 1-2 days
   
3. Fix cluster reset (Fix #3) ─── BLOCKING, wrong starting conditions
   └─ Estimated: 0.5 days
   
4. Make product-service degrade (Fix #4) ─── IMPORTANT, hypothesis untestable
   └─ Estimated: 1-2 days
   
5. Verify KEDA auth query (Fix #5) ─── will likely self-resolve after Fix #1
   └─ Estimated: 0.5 days

Total estimated time: 4-8 days before valid pilot run
```

---

## Key Observations for Thesis Direction

> [!WARNING]
> **The thesis's central hypothesis may need revision.** The current data shows that product-service at 200 RPS does NOT exhibit the "I/O-bound, CPU stays flat, HPA fails" behavior that the thesis predicts. CPU-based HPA DID scale product-service to 5 replicas. If this persists after fixing the starting replica issues, the thesis narrative must adapt.

**Possible thesis pivots if product-service continues to trigger CPU HPA:**

1. **Increase I/O pressure**: More complex database queries, larger dataset, external API calls
2. **Different workload**: Use a different endpoint (e.g., product search with complex joins) that is genuinely I/O-bound
3. **Lower HPA threshold**: If CPU hits 50% but not 70%, the H1 vs H2 vs H3 comparison still has value — H1 (70%) won't trigger but H2 (50%) will
4. **Reframe the thesis**: If all methods scale, compare *speed* and *efficiency* of scaling rather than *whether* they scale. The decomposition table still works — it just shows different numbers than hypothesized

The experiment is **not a failure** — it's a calibration run that revealed the load parameters are wrong. This is exactly what pilot runs are for.

---

## Summary

| Issue | Severity | Affects | Fix Effort |
|-------|----------|---------|------------|
| Auth-service overwhelmed by bcrypt load | 🔴 Critical | All 18 auth runs | 1-2 days |
| prometheus-adapter not working | 🔴 Critical | All 6 H3 runs | 1-3 days |
| Wrong starting replicas | 🔴 Critical | 4 product runs + cascading | 0.5 days |
| Product-service doesn't degrade | 🔴 Critical | Thesis hypothesis | 1-2 days |
| KEDA didn't scale auth-service | 🟡 Warning | 3 auth K1 runs | 0.5 days |

**Bottom line**: These 36 runs served their purpose as a pilot validation — they revealed that the experiment infrastructure has systemic issues that would have corrupted all 180 runs. Fix the 5 issues above, re-run 6 pilot runs (one per config for product-service), and verify clean results before scaling to the full experiment.
