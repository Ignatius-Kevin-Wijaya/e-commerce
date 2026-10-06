# Thesis Blueprint — Part 06: Experimental Methodology and KPI Design (§6–§7)

> Part of the thesis blueprint — index and executive summary: [thesis_blueprint.md](../thesis_blueprint.md).
> Sections moved verbatim from the single-file blueprint on 2026-10-06; original section numbers (§N) and finding numbers (#N) are kept so every cross-reference still resolves. Later additions are marked with their date.

---

## 6. Experimental Methodology

### Experiment Design Overview

The experiment compares **6 autoscaling configurations** across **3 load patterns** on **2 services** with distinct workload profiles, using a **controlled factorial design** that isolates the metric-type effect from the engine-architecture effect. The final core pair is now **auth-service** (CPU-dominant control) and the implemented **shipping-rate-service** (wait-dominant external-dependency workload).

### The Controlled Factorial Design

The prior blueprint's weakness was comparing HPA (CPU) vs KEDA (request-rate), which changed two variables simultaneously. This revision isolates them:

```
                       CPU metric          Request-rate metric
                 ┌───────────────────┬──────────────────────────┐
  HPA engine     │  H1 (default)     │  H3 (custom metric       │
                 │  H2 (tuned)       │      via prometheus-      │
                 │                   │      adapter)             │
                 ├───────────────────┼──────────────────────────┤
  KEDA engine    │  (not applicable) │  K1 (Prometheus scaler)  │
                 └───────────────────┴──────────────────────────┘
```

This enables three isolated comparisons:

| Comparison | What It Isolates | Research Question |
|-----------|-----------------|-------------------|
| **H1/H2 vs H3** | Same engine (HPA), different metric | "Does switching from CPU to request-rate improve HPA's scaling behavior?" |
| **H3 vs K1** | Same metric (request-rate), different engine | "Does KEDA's architecture provide benefits beyond the metric type advantage?" |
| **H1/H2 vs K1** | Different engine AND metric | "What is the combined real-world improvement when switching from default HPA to KEDA?" |

A reviewer **cannot** argue that the improvement is "just the metric" — because H3 directly tests that claim.

### Autoscaling Configurations (Independent Variable #1)

| Config | Method | Metric | Key Settings | Rationale |
|--------|--------|--------|-------------|-----------|
| **B1: Under-provisioned** | Fixed | — | `replicas: 1` | Lower-bound baseline: shows degradation without scaling |
| **B2: Over-provisioned** | Fixed | — | `replicas: 5` | Upper-bound baseline: shows maximum performance at maximum cost |
| **H1: HPA Default** | HPA | CPU utilization | `targetCPU: 70%`, default behavior policy | How HPA performs "out of the box" — the most common production config |
| **H2: HPA Tuned** | HPA | CPU utilization | `targetCPU: 50%`, aggressive scaling behavior | Best-case HPA with CPU: optimized threshold + fast scaling policy |
| **H3: HPA Custom Metric** | HPA | HTTP request rate (via prometheus-adapter) | `type: Pods`, `averageValue: service-specific calibrated threshold` | **The fairness control** — same metric as KEDA, but using HPA engine. Isolates metric effect from engine effect. |
| **K1: KEDA** | KEDA | HTTP request rate (via Prometheus scaler) | `trigger: prometheus`, `threshold: service-specific calibrated threshold` | Event-driven scaling based on actual traffic |

**Why this 6-config structure?**
- **B1 + B2:** Baselines — frame the performance envelope (worst case to best case)
- **H1 + H2:** HPA with CPU — tests the "default" and "best possible" CPU-based scaling
- **H3:** HPA with request-rate — isolates whether the metric type is what matters, not the engine
- **K1:** KEDA with request-rate — the full event-driven paradigm

**The three possible experimental outcomes:**
1. **H3 ≈ K1 >> H1/H2** → "The metric type is what matters. HPA with the right metric matches KEDA."
2. **K1 > H3 >> H1/H2** → "Both the metric AND the engine matter. KEDA's architecture provides additional benefit."
3. **H3 ≈ H1/H2 ≈ K1** (for auth-service/CPU-bound) → "For CPU-bound services, all methods perform similarly — CPU is an adequate metric."

**Every outcome is a valid, publishable finding.** The experiment cannot "fail."

**Threshold calibration (for H3 and K1):**
Both H3 and K1 use request-rate as the scaling metric. Their thresholds must be calibrated identically **within the same service**, but do not need to be identical across different services:
1. Run a low-load-to-saturation ladder for the target service with `1` pod
2. Measure the request-rate Prometheus actually observes, not just the RPS k6 tries to send
3. Set the service's threshold near the point where scale-up should begin
4. Apply the SAME threshold value to both H3 (`averageValue`) and K1 (`threshold`) for that service
5. Document service-specific calibration results separately (e.g. auth threshold and shipping threshold may differ)
6. This ensures any H3 vs K1 performance difference is due to the engine, not the threshold

### HPA Configurations

**Implementation note:** The YAML examples below now mirror the real `shipping-rate-service` manifests already present in the repository and validated on AKS.

```yaml
# H1: HPA Default
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: shipping-rate-service-hpa-default
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: shipping-rate-service
  minReplicas: 1
  maxReplicas: 5
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  # No behavior field — uses Kubernetes defaults
```

```yaml
# H2: HPA Tuned (aggressive scaling)
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: shipping-rate-service-hpa-tuned
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: shipping-rate-service
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
```

### H3: HPA with Custom Metric (via prometheus-adapter)

**prometheus-adapter configuration** (makes Prometheus metrics available to HPA via the Custom Metrics API):

```yaml
# prometheus-adapter rules ConfigMap
rules:
  custom:
  - seriesQuery: 'http_requests_total{namespace="ecommerce"}'
    resources:
      overrides:
        namespace: {resource: "namespace"}
        pod: {resource: "pod"}
    name:
      matches: "^(.*)_total$"
      as: "${1}_per_second"
    metricsQuery: 'sum(rate(<<.Series>>{<<.LabelMatchers>>}[1m])) by (<<.GroupBy>>)'
```

```yaml
# H3: HPA with request-rate custom metric
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: shipping-rate-service-hpa-custom
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: shipping-rate-service
  minReplicas: 1
  maxReplicas: 5
  metrics:
  - type: Pods
    pods:
      metric:
        name: http_requests_per_second
      target:
        type: AverageValue
        averageValue: "15"   # shipping-rate-service threshold under the ramping-vus methodology
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
```

**Note:** H3 uses the same aggressive scaling behavior as H2. This ensures any performance difference between H3 and K1 is due to the autoscaling engine architecture, not the scaling policy.

### KEDA Configuration

```yaml
# K1: KEDA with Prometheus trigger
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: shipping-rate-service-keda
spec:
  scaleTargetRef:
    name: shipping-rate-service
  minReplicaCount: 1      # Match HPA minReplicas for fair comparison
  maxReplicaCount: 5       # Match HPA maxReplicas for fair comparison
  cooldownPeriod: 30
  pollingInterval: 15      # Match HPA control loop interval for fairness
  triggers:
  - type: prometheus
    metadata:
      serverAddress: http://prometheus.monitoring.svc.cluster.local:9090
      metricName: http_requests_per_second
      query: |
        sum(rate(http_requests_total{job="shipping-rate-service"}[1m]))
      threshold: "15"      # shipping-rate-service threshold under the ramping-vus methodology
```

**Fairness note:** H3 and K1 use the same service-specific threshold, the same Prometheus data source, and the same scaling-policy intent. The ONLY difference is the autoscaling engine (HPA controller vs KEDA operator). This is what makes the comparison scientifically controlled.

### Load Patterns (Independent Variable #2)

| Pattern | Description | k6 Configuration | Why |
|---------|-------------|-------------------|-----|
| **Gradual Ramp** | Linear increase from a service-specific calibrated baseline to a calibrated peak over 5 minutes | `ramping-vus` for both services (auth `1 -> 12` VUs, shipping `10 -> 80` VUs); stages 2 m base / 5 m ramp / 2 m hold / 3 m ramp-down | Tests how smoothly autoscaling follows predictable growth |
| **Sudden Spike** | Service-specific calibrated baseline → instant jump to calibrated peak at t=2min | `ramping-vus` 10 s VU jump for both services; stages 2 m base / 10 s jump / 6 m 50 s at peak / 3 m ramp-down | Tests reaction speed — the worst case for reactive autoscaling |
| **Oscillating** | Alternating between calibrated baseline and calibrated peak every 90 seconds | `ramping-vus` for both services; 2 m base, then 80 s holds at peak/base joined by 10 s transitions (90 s half-cycle), 3 m ramp-down | Tests scaling stability — does the system thrash (scale up/down repeatedly)? |

**Calibration note (final):** Both services use closed-loop `ramping-vus` with `noConnectionReuse: true` and the shared 1 m request-rate window. Auth-service: `BASE_VUS = 1`, `PEAK_VUS = 12`, shared H3/K1 threshold `5` req/s/pod (migrated from the retired `10 -> 40` RPS arrival-rate profile on 2026-08-15). Shipping-rate-service: `BASE_VUS = 10`, `PEAK_VUS = 80`, shared H3/K1 threshold `15` req/s/pod.

> **Open-loop variant (added 2026-10-06, Part 08):** the same three stage shapes as `ramping-arrival-rate` targets in req/s. Pilot and v2 settings: auth 2→30 req/s, shipping 10→105 req/s, 5 s request timeout (a timeout is a failed request), all VUs preallocated at ⌈1.5 × peak × timeout⌉ (225 / 788), no k6 thresholds. v2 adds per-pod admission control (cap 22 auth / 48 shipping) and auth token pre-authentication during the reset. Autoscaler manifests, thresholds, rate windows and runner timings are unchanged.

### Services Under Test (Independent Variable #3)

| Service | Workload Type | Why It's Different for This Experiment |
|---------|--------------|---------------------------------------|
| **shipping-rate-service** | Wait-dominant external-dependency workload | The hot path asynchronously fans out to three carrier quote endpoints, each with controlled delay and small payloads. This keeps the service mostly waiting on downstream responses with minimal local CPU, making it the deliberate non-CPU counterpart to auth-service. |
| **auth-service** | CPU-bound (bcrypt hashing) | CPU correlates with load → HPA works well → KEDA may offer no advantage. This is the "control" scenario. |

**Working hypothesis, revised against the post-fix 180-run evidence (2026-08-17):** The control behaves exactly as predicted — on CPU-bound auth-service every autoscaler lands within ~3% of B2 on all three patterns except K1 oscillating (+9.2%), so metric and engine choice are both immaterial there. What did *not* survive is the expected wait-dominant advantage for request-rate: on shipping gradual all four autoscalers sit on the B2 floor (916–920 ms, a 4 ms spread), because the original −49% gap was a load-generator artifact (finding #12). The surviving result is **conditional**: metric and engine matter only where autoscaling is genuinely stressed — shipping **spike**, where request-rate gains ~10% and KEDA a further ~5% with 6× better stability. And the dominant effect is neither metric nor engine but **workload × load-pattern**: shipping **oscillating** is the single condition where every configuration fails (the best configuration closes only 26% of the B1→B2 gap, versus ≥99% for the best configuration everywhere else). Product-service is retained as a supporting case-study showing: **when the dominant bottleneck lives in a downstream dependency, app-tier autoscaling may not help and can even worsen outcomes.**

### Experimental Protocol

1. **Dependency-isolation gate (before freezing any service profile):** Verify that the fixed overprovisioned control (`B2`) is healthy and meaningfully better than the fixed underprovisioned control (`B1`) under the same workload. If `B2` is no better, or is worse, classify the regime as downstream-limited and either raise dependency capacity or treat it as a separate case-study instead of a clean app-tier comparison.
2. **Cluster state reset:** Before each run, delete the previous autoscaler (HPA or ScaledObject), wait for the deployment to return to 1/1 ready replicas, delete leftover k6 jobs, wait 120 seconds (`RESET_WAIT`) for stabilization, verify no residual pods
3. **Apply configuration:** Deploy the test config (HPA/KEDA/fixed replicas)
4. **Wait for stabilization:** 90 seconds (`STABILIZE_WAIT`) for metrics to baseline, then a `/ready` pre-flight check
5. **Warm-up:** 2 minutes at the service-specific calibrated base load, data excluded from analysis
6. **Test execution:** 7 minutes of the designated load pattern at the service-specific calibrated peak behavior
7. **Cooldown observation:** 3-minute k6 ramp-down to 0 VUs, then a further 180 seconds (`EXPORT_WAIT`) before export to capture scale-down behavior
8. **Data export:** Pull Prometheus metrics via PromQL, export k6 results to JSON
9. **Total per run:** ~12 minutes of k6 load + ~8 minutes of reset/stabilization/export ≈ 20 minutes (final campaign: 180 runs in 58 h 49 m ≈ 19.6 min/run)

### Total Experiment Runs

| Component | Count |
|-----------|-------|
| Autoscaling configs | 6 (B1, B2, H1, H2, H3, K1) |
| Load patterns | 3 (gradual, spike, oscillating) |
| Repetitions | 5 |
| Services (core matrix) | 2 |
| **Total runs** | **6 × 3 × 5 × 2 = 180** |
| **Time per run** | ~15 minutes planned; ≈19.6 minutes actual (including setup/reset/export) |
| **Total experiment time** | ~45 hours planned; 58 h 49 m actual (final campaign 2026-08-15 → 08-17) |
| **AKS cost** | planned 45 × $0.516 ≈ $23.22; final campaign ≈ 58.8 × $0.516 ≈ $30.35 |

With 30% buffer for re-runs: **~59 hours, ~$30 AKS compute cost.**

With 7-8 months available, you can spread experiments across multiple sessions (e.g., 4-5 hours per day over 10-12 days), reducing fatigue and allowing same-day analysis of anomalies.

---

## 7. KPI / Metrics Design

### Primary KPIs (Must Report For Every Configuration)

| KPI | Definition | Unit | Source | Why It's Primary |
|-----|-----------|------|--------|-----------------|
| **p95 Response Latency** | 95th percentile of successful request duration during the test window | ms | k6 `http_req_duration{p(95)}` | The single most important performance indicator; directly reflects user experience |
| **Error Rate** | Percentage of requests returning HTTP 4xx/5xx during the test window | % | k6 `http_req_failed` | A service that's fast but returns errors is worse than one that's slow but correct |
| **Time-to-Scale** | Seconds from load increase to new pod serving traffic (passing readiness probe) | seconds | Prometheus `kube_pod_status_ready` timestamps correlated with load start | Measures how quickly each method reacts — the core comparison |
| **Resource Cost Index** | `Σ(active_pods × duration_seconds × cpu_request) × price_per_cpu_second` over the test window | $ equivalent | Prometheus `kube_deployment_status_replicas` sampled every 15s | Converts resource usage to dollar cost — enables Pareto analysis |

### Secondary KPIs (Report For Key Configurations)

| KPI | Definition | Unit | Source | Why It Matters |
|-----|-----------|------|--------|---------------|
| **Scaling Event Count** | Total number of scale-up + scale-down decisions during test | count | HPA events / KEDA events via `kubectl get events` | High count = instability (thrashing); low count = smooth scaling |
| **Recovery Time** | Seconds from load decrease to p95 latency returning to ≤ 1.5× warm-up baseline | seconds | k6 latency timeline correlated with load timeline | Measures how well the system recovers — important for oscillating loads |
| **Average CPU Utilization** | Mean CPU usage across all pods of the tested service during the test | % | Prometheus `container_cpu_usage_seconds_total` | Shows resource efficiency — low utilization with many pods = waste |
| **Latency Degradation Ratio** | (p95 during peak load) / (p95 during warm-up) | ratio | k6 data | Normalized metric that's comparable across services with different baseline latencies |

### Optional KPIs (Report If Interesting Results Emerge)

| KPI | Definition | Why Optional |
|-----|-----------|-------------|
| **Pod Utilization Ratio** | actual_CPU_used / total_CPU_requested | Shows how efficiently scheduled resources are used; interesting if HPA overprovisions |
| **Scale-down Completeness** | Final pod count 3 min after load stops, relative to minReplicas | Shows whether aggressive scaling leaves behind orphan pods |
| **Metric Detection Latency** | Seconds from actual load change to metric reflecting it in Prometheus | Only measurable with precise correlation; interesting for understanding WHY one method reacts faster |

### Open-Loop KPI Definitions (added 2026-10-06, Part 08)

These were fixed before any open-loop data existed (`scripts/pilot_openloop.py`):

| KPI | Definition |
|---|---|
| Window p95 / p99 | Client wall-clock latency per request **including the TCP connect** (`req_e2e_duration`), for requests *started* in the load window (k6 t 120–540 s: no warm-up, no ramp-down). **Failed requests count as infinitely slow**, so a p95 that falls inside the failures is reported as "fail". |
| SLO-violation seconds | Number of 10 s bins in the load window whose p95 exceeds the SLO, × 10 s. SLO: auth 1500 ms, shipping 1200 ms. |
| Offered / attempted / goodput | Scheduled arrivals (integrated stage schedule) / started requests + dropped iterations / successful requests per second. |
| Error %, timeout %, shed % | Failed requests; requests that hit the 5 s timeout; requests rejected with 503 by admission control (v2). |
| Time to scale | Spike onset → first `ScalingReplicaSet` scale-up event, and → first new pod's Ready transition (5 s pod watcher with exact `lastTransitionTime`). |
| Per-pod distribution | During the peak, each pod Ready ≥ 60 s: its mean share of the per-pod request rate and CPU relative to the mean of such pods; < 20% flags pinning. |

### How KPIs Are Interpreted

The central analysis combines primary KPIs into a **trade-off assessment:**

- **Performance winner:** Lowest p95 latency + lowest error rate + fastest time-to-scale
- **Cost winner:** Lowest resource cost index while meeting SLO thresholds
- **Balanced winner:** Best position on the Pareto frontier (latency vs cost)

If HPA and KEDA produce similar latency but KEDA uses fewer pod-minutes (because it scales more precisely), KEDA wins on efficiency. If HPA (CPU) underperforms on shipping-rate-service while H3 (HPA with request-rate) DOES trigger more appropriately, the conclusion is: **the metric type matters more than the HPA engine alone.** If KEDA still outperforms H3 despite using the same metric, KEDA's architecture provides additional value. Product-service remains separately useful here: if `B2`, `H3`, or `K1` are worse than `B1` under the same product workload, that should be interpreted as evidence of a downstream bottleneck and the limits of app-tier autoscaling, not as a simple "autoscaler X lost" result.

---
