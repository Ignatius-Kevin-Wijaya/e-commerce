# Thesis Blueprint — Part 07: Risks (§8)

> Part of the thesis blueprint — index and executive summary: [thesis_blueprint.md](../thesis_blueprint.md).
> Sections moved verbatim from the single-file blueprint on 2026-10-06; original section numbers (§N) and finding numbers (#N) are kept so every cross-reference still resolves. Later additions are marked with their date.

---

## 8. Risk Deep-Dive: What Can Actually Go Wrong

### Risk Priority Summary

| Risk | Worry Level | Budget Time | When to Tackle |
|------|------------|------------|----------------|
| **prometheus-adapter setup** | 🔴 **High** | 5 days | Week 8 |
| **KEDA Prometheus scaler** | 🟡 **Medium** | 3 days | Week 7 |
| **k6 script rewrite** | 🟡 **Medium** | 1 week | Week 5 |
| **Forgot `az aks stop`** | 🟡 **Medium** | Day 1 setup | Week 3 (cluster creation) |
| **Threshold calibration** | 🟡 **Medium** | 2-3 days | Week 9 |
| **Prometheus scrape gaps** | 🟢 **Low** | 1 hour | Week 6 (add resource requests) |
| **k6 CPU-starvation** | 🟢 **Low** | 1 hour | Week 5 (set resource requests) |
| **Wait-dominant service drifts into a mixed or dependency-limited regime** | 🔴 **High** | 2-3 days | Treat as a calibration/methodology decision, not a thesis failure |

---

### Risk 1: KEDA Prometheus Scaler Doesn't Trigger

**Probability:** Medium | **Impact:** 🔴 High — experiment blocked | **Budget:** 3 days

**What happens technically:**

KEDA's Prometheus scaler works by periodically running a PromQL query against your Prometheus instance. If the query returns a value above the threshold, KEDA scales up. Sounds simple. Here's where it breaks:

Your KEDA config for the final wait-dominant service now uses a deliberately simple aggregate query:
```
sum(rate(http_requests_total{job="shipping-rate-service"}[1m]))
```

**How it could break for YOU specifically:**

1. **Label mismatch.** Your FastAPI instrumentator exposes `http_requests_total`, but the label might not be `job="shipping-rate-service"`. It could be `service="shipping-rate-service"` or `app="shipping-rate-service"` depending on how Prometheus relabeling works. If the label doesn't match, the query returns `0`, KEDA sees "no load", and never scales.

2. **Prometheus is in the `monitoring` namespace, KEDA is in `keda` namespace.** KEDA's operator needs to reach `http://prometheus.monitoring.svc.cluster.local:9090`. If cross-namespace traffic is blocked or the service name is wrong, metric fetches fail and scale-up never happens.

3. **Prometheus scrape gaps or stale data.** Even with the correct query, KEDA can react too slowly if Prometheus misses scrapes or returns stale rate values during the spike.

4. **Threshold mismatch with observed metrics.** This already happened during recovery: a threshold that looks reasonable against offered RPS can still be unreachable from Prometheus' observed single-pod rate. If you skip calibration, KEDA will appear broken again.

**How you'd notice:** You'd run your k6 load test, see latency climbing, check `kubectl get scaledobject` and see `READY: False` or scaling metrics stuck at 0. Then you'd spend hours reading KEDA operator logs trying to figure out WHY.

**How to avoid it — step by step:**

```bash
# Step 1: BEFORE configuring KEDA, verify your actual Prometheus labels
# Port-forward to Prometheus
kubectl port-forward -n monitoring svc/prometheus 9090:9090

# Step 2: Open http://localhost:9090 and run these queries:
# Query A: Check what labels http_requests_total actually has
http_requests_total

# Look at the labels carefully. Note the exact label names and values.
# Example result might show: http_requests_total{method="POST", handler="/shipping/quotes", job="shipping-rate-service"}
# If the label is "job" not "service", you need to update the KEDA query.

# Query B: Test the exact aggregate query directly
sum(rate(http_requests_total{job="shipping-rate-service"}[1m]))

# If this returns "no data", inspect the real labels and adjust the query before
# touching the ScaledObject.

# Step 3: Test your EXACT KEDA query in Prometheus UI BEFORE putting it in the ScaledObject
# Paste the full query and verify it returns a number (not empty, not stale)

# Step 4: After deploying ScaledObject, verify KEDA can read the metric
kubectl get scaledobject shipping-rate-service-keda -o yaml
# Check: status.conditions should show "Ready: True"

# Step 5: If KEDA isn't triggering, check operator logs
kubectl logs -n keda deployment/keda-operator --tail=50

# Look for errors like:
# - "failed to get metric" → query/connection issue
# - "connection refused" → Prometheus URL wrong
# - stale/zero values while traffic is high → scrape gap or label mismatch
```

**Fallback if unresolvable:** Use KEDA's built-in `cpu` trigger type instead of `prometheus`. This makes KEDA behave like HPA (CPU-based), which defeats the purpose of the comparison — but at least proves the KEDA pipeline works. Then debug the Prometheus query separately.

---

### Risk 2: prometheus-adapter Doesn't Register Custom Metric

**Probability:** Medium | **Impact:** 🔴 High — H3 config blocked | **Budget:** 5 days

**What happens technically:**

prometheus-adapter bridges Prometheus metrics into Kubernetes' Custom Metrics API. HPA can only use custom metrics if they appear in this API. The adapter runs a set of "rules" that convert PromQL queries into Kubernetes API endpoints.

**How it could break for YOU specifically:**

1. **The metric naming rule doesn't match your metric.** Your rule says:
   ```yaml
   seriesQuery: 'http_requests_total{namespace="ecommerce"}'
   ```
   But what if your pods are in namespace `default` instead of `ecommerce`? Or what if the metric is called `http_request_total` (singular) instead of `http_requests_total` (plural)? The query matches zero series, prometheus-adapter registers zero custom metrics, and HPA says:
   ```
   unable to fetch metrics from custom metrics API:
   the server could not find the requested resource (get pods.custom.metrics.k8s.io)
   ```
   You'd see this event on the HPA object and have no idea why.

2. **prometheus-adapter can't reach Prometheus.** The Helm install defaults might set the wrong Prometheus URL. If you install with `--set prometheus.url=http://prometheus.monitoring.svc.cluster.local` but your Prometheus service is actually called `prometheus-server` or is on port `9091`, the adapter silently fails to scrape and registers zero metrics.

3. **The adapter conflicts with metrics-server.** Both metrics-server (for CPU/memory) and prometheus-adapter (for custom metrics) register with the Kubernetes API aggregation layer. If configured wrong, prometheus-adapter could shadow metrics-server, breaking H1 and H2 (CPU-based HPA) while trying to fix H3. Now you've broken your working configs trying to add a new one.

4. **The `rate()` window is too short/long.** Your rule uses `rate(...[1m])`. If Prometheus scrapes every 15 seconds but there's a scrape gap (missed one scrape), `rate()` over 1 minute might return 0 for a brief period, causing HPA to scale down prematurely during a test. Worse — the metric flickers between 0 and the real value, making HPA scale up and down erratically.

**How to avoid it — step by step:**

```bash
# Step 1: BEFORE installing prometheus-adapter, verify your Prometheus metric format
kubectl port-forward -n monitoring svc/prometheus 9090:9090
# Open http://localhost:9090
# Query: http_requests_total
# Note the EXACT metric name and namespace label

# Step 2: Install prometheus-adapter with correct Prometheus URL
helm install prometheus-adapter prometheus-community/prometheus-adapter \
  --namespace monitoring \
  --set prometheus.url=http://prometheus.monitoring.svc.cluster.local \
  --set prometheus.port=9090

# Step 3: Wait 2-3 minutes for the adapter to discover metrics, then verify
kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1
# Should return a list of available metrics
# If it returns 404 or empty: adapter isn't registered or found no metrics

# Step 4: Check if YOUR specific metric is available
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/ecommerce/pods/*/http_requests_per_second"
# Should return metric values for each pod
# If 404: the naming rule didn't match. Check adapter logs:
kubectl logs -n monitoring deployment/prometheus-adapter --tail=50

# Step 5: If metric doesn't appear, debug the adapter config
# Export the current config:
kubectl get configmap -n monitoring prometheus-adapter -o yaml
# Compare the seriesQuery against what Prometheus actually has

# Step 6: Verify metrics-server still works (H1/H2 dependency)
kubectl top pods -n ecommerce
# If this breaks after installing prometheus-adapter, you have an API conflict
# Fix: ensure prometheus-adapter uses custom.metrics.k8s.io, NOT metrics.k8s.io

# Step 7: Test H3 HPA end-to-end
kubectl apply -f h3-hpa-custom-metric.yaml
kubectl get hpa shipping-rate-service-hpa-custom
# Check the TARGETS column: should show "current/target" like "3/5" or "4/5"
# If it shows "<unknown>/5": the custom metric is not being read
```

**Fallback if unresolvable after 5 days:** Drop H3, revert to 5-config design (B1, B2, H1, H2, K1). The thesis is still 8.5/10. Acknowledge the metric-vs-engine isolation as a limitation, and reference it as future work. prometheus-adapter is the only 9→8.5 downgrade risk.

---

### Risk 3: Product-service Enters a Downstream-Bottleneck Regime Before the Autoscaler Comparison Becomes Clean

**Probability:** Medium | **Impact:** 🔴 High for methodology, but not for thesis validity | **Budget:** 2-3 days for calibration confirmation and decision-making, not for panic

**What happens technically:**

The older assumption was simple:
1. Most of the request time is spent waiting on PostgreSQL
2. CPU stays low
3. HPA CPU never scales

The newer AKS evidence is more nuanced:
1. Search-heavy PostgreSQL reads still matter
2. The handler also does count queries, result materialization, sorting effects, and JSON serialization
3. CPU can therefore remain correlated enough with load for H1/H2 to scale in some regimes
4. But once the single `product-db` becomes the dominant bottleneck, scaling the app tier may not help and can even make results worse

**How it plays out for YOU:**

- On `~50k` products, even `B2 spike 5 -> 20` still failed at `88.04%`, and `B2 spike 2 -> 10` still failed at `76.26%`
- On `~30k` products, `B2 spike 2 -> 10` improved to `39.72%`, proving seed size really changes the regime
- On `~20k` products, `B2 spike 2 -> 10` became too easy (`0%` failed), while `B2 spike 2 -> 11` sat near the cliff (`8.75%` failed)
- The most revealing April 15 result was `~20k` + `2 -> 11`: `B1` stayed healthy (`0%`), while `B2`, `H1`, and `K1` all degraded

**This is now a strong candidate central finding, not a blind assumption.** The real question is no longer only "does CPU decouple from load?" but also "when does the bottleneck move far enough downstream that app-tier autoscaling itself stops being the right lever?"

**Best methodological response:** this decision has now been made. Product-service should be frozen as a dependency-limited case study and written honestly into the thesis, while the final controlled non-CPU matrix shifts to shipping-rate-service.

**The only actual risk:** If this also happens for auth-service (CPU-bound with bcrypt), your control scenario breaks. auth-service SHOULD trigger CPU-based HPA because bcrypt hashing is heavily CPU-intensive. If bcrypt doesn't push CPU above 50%, something is wrong with your resource limits or load test intensity.

**How to verify auth-service behaves correctly:**
```bash
# During pilot, run a quick load test against auth-service (POST /auth/login)
# Then check CPU
kubectl top pod -n ecommerce -l app=auth-service
# CPU should be near or exceeding the 50% target at high load
# If CPU is low: check if bcrypt rounds are too few (should be 12)
# or if the load test isn't actually hitting the login endpoint
```

---

### Risk 4: k6 Pod Gets CPU-Starved

**Probability:** Low | **Impact:** 🔴 High — invalidates load pattern | **Budget:** 1 hour setup

**What happens technically:**

k6 drives a specified number of virtual users. Even at the current thesis profiles (`1 -> 12` VUs for auth, `10 -> 80` VUs for shipping, both closed-loop), k6 still needs steady CPU to maintain concurrent HTTP connections, serialize bodies, and record timing metrics in real time.

If k6 doesn't get enough CPU, it silently under-delivers the offered load. Your "80-VU spike" can quietly become a lower-throughput test without any obvious application-side crash.

**How it could happen to YOU:**

During a spike test, your scaled service pods, monitoring stack, and autoscaler components are all competing for CPU. If the k6 pod lands on a busy node and its limits are too low for the active profile, Linux can throttle k6 first. The nasty part is that k6 usually doesn't crash; it just under-delivers the load.

The good news is that the current auth/product/shipping k6 manifests already include requests and limits. The risk now is drift: if one manifest gets edited differently from the others, or if a future template drops those resources, the load generator becomes the bottleneck instead of the service under test.

**How to avoid it:**

```yaml
# Keep resource requests/limits present and aligned across all k6 manifests:
spec:
  template:
    spec:
      containers:
      - name: k6
        image: grafana/k6:latest
        resources:
          requests:
            cpu: "500m"
            memory: "512Mi"
          limits:
            cpu: "1500m"
            memory: "1Gi"
```

```bash
# During pilot runs, verify k6 actually achieves target RPS:
# Check k6 output for "http_reqs" counter — should match target rate
# Also monitor k6 pod CPU during the test:
kubectl top pod -n ecommerce -l app=k6 --containers
# If k6 is hitting its CPU limit (1500m), increase the limit or schedule it
# on a specific node with kubectl label + nodeSelector
```

---

### Risk 5: Prometheus Misses Scrapes Under Load

**Probability:** Low (after fix) | **Impact:** 🟡 Medium — data gaps at critical moments | **Budget:** 1 hour

**What happens technically:**

Prometheus scrapes your services every 15 seconds. Each scrape is an HTTP GET to `/metrics`. Under heavy load, two things happen:
1. Prometheus itself needs CPU to fetch, parse, and store metrics
2. Your services are CPU-busy and might respond slowly to the `/metrics` endpoint

Your AKS Prometheus manifest now has explicit requests/limits, which is good. The remaining risk is undersizing it relative to the final experiment intensity or accidentally reverting the manifest to a weaker BestEffort-style configuration.

**How it could happen to YOU:**

During a spike test on the wait-dominant service (for example, shipping-rate-service at its calibrated peak):
1. Shipping pods, carrier-mock pods, and monitoring pods are all consuming CPU
2. If Prometheus is undersized, it gets CPU-throttled by the Linux scheduler
3. A scrape attempt to shipping-rate-service takes 3 seconds instead of 100ms
4. Prometheus marks the scrape as "timed out" and drops it
5. For the next 15-30 seconds, there's NO metric data for shipping-rate-service

**The insidious part:** Your KEDA and H3 both rely on Prometheus data. During the gap:
- KEDA runs its query: `rate(http_requests_total[1m])` — but the last data point is 30 seconds stale
- KEDA sees a LOWER rate than reality (stale data) and doesn't scale up
- You'd conclude "KEDA was slow to react" — but the real cause was Prometheus data loss, not KEDA

You'd only discover this weeks later when analyzing data: "Why is there no data point at t=125s, right when the spike started?"

**How to avoid it:**

```yaml
# Keep these requests/limits in your prometheus.yaml deployment:
containers:
  - name: prometheus
    image: prom/prometheus:v2.45.0
    resources:
      requests:
        cpu: "100m"       # Guarantees CPU won't be stolen
        memory: "256Mi"
      limits:
        cpu: "500m"
        memory: "512Mi"
```

```bash
# During pilot runs, check for scrape failures:
# Open Prometheus UI → Status → Targets
# All targets should show "State: UP" with scrape duration < 1s
# If any target shows "State: DOWN" during load tests, Prometheus is CPU-starved

# Also verify data continuity after a pilot run:
# Query: rate(http_requests_total{job="shipping-rate-service"}[1m])
# Graph it over the test window. Look for gaps or sudden drops to zero.
```

---

### Risk 6: Threshold Calibration Affects H3 vs K1 Comparison

**Probability:** Medium | **Impact:** 🟡 Medium — subtle bias in results | **Budget:** 2-3 days

**What happens technically:**

H3 (HPA + custom metric) and K1 (KEDA) both use request-rate as their metric with the same service-specific threshold. But the same numeric threshold can still behave slightly differently across the two systems if it is chosen carelessly.

**How it could affect YOUR results:**

1. **Timing offset.** HPA's control loop runs every 15 seconds. KEDA's polling interval is also 15 seconds. But they don't synchronize. HPA might poll at t=0, t=15, t=30... while KEDA polls at t=3, t=18, t=33. If a spike hits at t=5:
   - HPA detects it at t=15 (10s delay)
   - KEDA detects it at t=18 (13s delay)

   Or KEDA polls at t=7 and detects it in 2 seconds while HPA waits until t=15. This random 0-15 second offset adds noise to "time-to-scale" measurements. Over 5 repetitions, it may average out — but if it doesn't, you might conclude "KEDA is 5 seconds faster" when it's actually random polling alignment.

2. **Rate window mismatch.** prometheus-adapter computes `rate()[1m]` when IT scrapes. KEDA computes `rate()[1m]` when IT scrapes. They scrape at different times, so the 1-minute windows cover slightly different time ranges, giving different values for the "same" metric. During a sharp spike, the value difference can be significant.

3. **Different controller timing and sampling.** HPA and KEDA may read the same Prometheus source at slightly different moments and may reconcile desired replicas on different control-loop ticks. During a sharp spike, that can still create small H3-vs-K1 differences even when the configured threshold is numerically identical.

**How to minimize it:**

```bash
# Step 1: During calibration (Week 9), run H3 and K1 pilot tests back-to-back
# on the same load pattern, same day, same cluster state
# Compare the time-to-scale measurements

# Step 2: Verify both systems are reading similar values
# During a test, simultaneously check:
kubectl get hpa shipping-rate-service-hpa-custom -o yaml | grep -A5 "currentMetrics"
kubectl get scaledobject shipping-rate-service-keda -o yaml | grep -A5 "metrics"
# The "current" values should be within 10% of each other
# If they diverge significantly, investigate the rate() window or pod count source

# Step 3: If timing offset is a concern, document it honestly
# In BAB 3, write: "Both HPA and KEDA poll metrics at 15-second intervals.
# The polling phases are not synchronized, introducing ±15 seconds of
# measurement variance in time-to-scale. This variance is expected to
# average out across 5 repetitions per configuration."

# Step 4: Consider using a longer rate window (2 minutes instead of 1)
# to smooth out timing differences:
# KEDA: rate(http_requests_total[2m])
# prometheus-adapter: rate(<<.Series>>{<<.LabelMatchers>>}[2m])
# Trade-off: longer window = smoother but slower to detect spikes
```

---

### Risk 7: Forgot to `az aks stop`

**Probability:** Medium (it WILL happen at least once) | **Impact:** 🟡 $4-87 per occurrence | **Budget:** 30 min setup on Day 1

**What happens:**

3× D4as_v5 at $0.516/hour. You finish experimenting at 11pm, go to bed, forget to stop.

| Scenario | Cost Burned |
|----------|------------|
| 8 hours overnight | $4.13 |
| Full weekend forgot | $24.77 |
| Holiday week forgot | $86.69 |

**How it WILL happen to YOU:**

The most common scenario: you finish a debugging session at 10pm, think "I'll run one more test tomorrow morning," leave the cluster running, then get busy with classes or homework and don't open your laptop for 2 days. $24.77 gone.

**How to prevent it:**

```bash
# Option 1: Azure Automation (set once, works forever)
# Create a Logic App or Automation Runbook that runs 'az aks stop' at midnight daily
# Azure Automation → Create Runbook → PowerShell:
#   Stop-AzAksCluster -ResourceGroupName "ecommerce" -Name "ecommerce-aks"
#   Schedule: daily at 00:00 WIB

# Option 2: Simple cron reminder (less reliable but still helpful)
# On your phone: set a DAILY alarm at 11pm: "STOP AKS CLUSTER"

# Option 3: Check-before-sleep script
# Save this as ~/stop-aks.sh
az aks stop --resource-group ecommerce --name ecommerce-aks --no-wait
echo "Cluster stopping. Goodnight. 💤"

# Before bed, run: bash ~/stop-aks.sh

# Option 4: Azure Budget Alert
# Azure Portal → Cost Management → Budgets → Create
# Set $100 budget, alert at $50 (50%), $75 (75%), $100 (100%)
# You'll get email/SMS when spending crosses thresholds
```

**Set up Option 4 (Budget Alert) on the FIRST DAY you create the cluster.** It's non-negotiable.

---

### Risk 8: Experiment Script Drift After the Thesis Pivot

**Probability:** Medium | **Impact:** 🟡 +2-4 days | **Budget:** 3-4 focused workdays

**What happens technically:**

The thesis pivot changed the core experiment from `product-service + auth-service` to `shipping-rate-service + auth-service`. The runtime stack has already been updated, but any stale script, validator, graph generator, or blueprint example that still assumes `product-service` can quietly corrupt later analysis.

**How it could break for YOU specifically:**

1. **`run-experiment.sh` drift.** If the service matrix, k6 template selection, or metadata export still references product defaults, your shipping runs can execute with the wrong workload shape or be mislabeled in `metadata.json`.

2. **Validation/graph drift.** If `deep_validate.py` or `generate_thesis_graphs.py` still assume `/products` or `product-service`, they can silently classify correct shipping runs as bad data or produce the wrong figures.

3. **Gateway/route drift.** The gateway service is exposed internally on port `80` while the container listens on `8080`. A stale k6 target or smoke command can therefore fail even when the route itself is healthy.

4. **Threshold drift.** Shipping H3/K1 now depend on the calibrated threshold `15` under the `ramping-vus` methodology. If the manifests, blueprint, or validator drift away from that value, the thesis will reintroduce a calibration bug that has already been solved.

5. **Unscoped exports.** If event/HPA/KEDA exports are not scoped to the current run, you can end up attributing autoscaler behavior from one service to another and poisoning the core dataset.

**How to approach the rewrite:**

```bash
# Minimum post-pivot verification set before running the final matrix:
bash scripts/run-experiment.sh --dry-run
bash scripts/validate-results.sh shipping-rate-service
python3 scripts/deep_validate.py
python3 scripts/generate_thesis_graphs.py --dry-run
```

**Key insight:** the hardest part is no longer writing a complex user journey. The real risk is keeping the execution scripts, validators, figures, and thesis text synchronized after the product → shipping pivot.

---

### Risk 9: Advisor Requests Scope Change Mid-Project

**Probability:** Low-Medium | **Impact:** 🟡 +1-2 weeks | **Budget:** 1 meeting

**What happens:** You've built everything, started experiments, and your advisor says "Why don't you also test VPA?" or "Add 3 more services" or "Compare with GKE too." Any of these would add 3-6 weeks of work.

**How to prevent it:** Present your experiment design (this blueprint's Section 6) to your advisor for explicit approval BEFORE building anything. Get agreement on the scope, the 6 configurations, the 2 services, and the metrics. Ideally get this in writing (email confirmation).

**When it happens anyway:** If the request is small (add one more metric, adjust a threshold), accommodate it. If it's large (add VPA, test on GKE), explain the time/budget constraint and propose it as "Saran untuk Penelitian Selanjutnya" in BAB 5. Most advisors accept this framing.

---

---

### Risk 10: Open-Loop Overload Makes Pods Collapse and Request-Rate Metrics Go Blind (added 2026-10-06)

**Observed, not hypothetical (Part 08 §8.7):** under a fixed open-loop offer above one pod's capacity, an unprotected single-worker FastAPI pod keeps accepting work it can never finish. Its goodput falls to ≈0, its readiness probe fails, Prometheus can no longer scrape `/metrics` (`up = 0`), and `http_requests_total` (counted on completion) falls instead of rising. In the pilot, shipping H3/K1 therefore never scaled (97.99–99.30% errors) and collapsed pods stayed sick after new pods arrived, which amplified a 15 s poll-phase difference into 140 s of extra SLO violation (shipping H2).

**Mitigation in v2:** per-pod admission control (cap on in-flight requests, immediate 503 for the excess, probes and `/metrics` exempt), registered as the **outermost** middleware. Inside the other middleware it did not help: rejections still paid for the gateway check and the instrumentation. One shipping pod then stays graceful up to 105 req/s; it still collapses somewhere between 105 and 140 req/s. That limit is the single-worker accept/parse capacity, so **open-loop peaks must stay below what one pod can reject gracefully**, because every autoscaled run starts on one pod.

**Detection:** `pilot_openloop.py validate` / `gate` (G3: Ready pod unscrapeable, autoscaler metric failures, container restarts).

### Risk 11: Auth `setup()` Burst Scales CPU HPAs Before the Experiment Starts (added 2026-10-06)

The 120 bcrypt pre-authentication logins (~28 s) run immediately before the warm-up. H2 read 82% CPU about a minute later and scaled to 2–3 replicas before spike onset, then scaled back down as the spike began. H1 is exposed even more, because its default 300 s scale-down window would keep the extra pods. The closed-loop campaign has the same `setup()`. **Mitigation (v2):** pre-authenticate during the cluster reset, before `RESET_WAIT` and before any autoscaler exists, and hand the tokens to k6 through a ConfigMap. The gate's G2 requires exactly 1 Ready replica at scenario start and at onset.

### Risk 12: Platform Gaps in Indonesia Central (added 2026-10-06)

ACR Tasks (`az acr build`) are unavailable in the registry's region, and the laptop has no Docker, so service images cannot be rebuilt quickly. Workarounds: ConfigMap code overlay on the existing image (used for v2; verify first that the image's code equals the repo, as done 2026-10-06), a temporary ACR in a supported region plus `az acr import`, or Docker on a VM.

### Operational Lessons (added 2026-10-06)

| Lesson | What happened / how it is handled now |
|---|---|
| Never edit a bash script while it is running | Bash reads scripts by byte offset. A mid-ladder edit of `run-pilot-openloop.sh` was reverted before harm; the runner now ends with `pilot_main "$@"; exit $?` so later edits cannot inject commands. |
| Git Bash rewrites POSIX-looking arguments for native programs | `kubectl exec … -- cat /results/…` became a Windows path; in-pod paths go through `MSYS_NO_PATHCONV=1` (`kexec`). |
| Verify every file transfer | A stray `< /dev/null` silently broke a tar-over-ssh sync to the VM; the md5 check caught it. Transfers now use an scp'd tarball plus `md5sum -c`. |
| `kubectl cp` needs a running container | The closed-loop runner copied k6 results after the pod exited and never got them; the open-loop wrapper holds the pod until the copy is verified. |
| k6 JSON field order varies | Point lines are `{"metric":…,"type":"Point",…}`, metric definitions `{"type":"Metric",…}`; the parser reads the metric name from either position. |
| k6 reuses VUs across non-overlapping scenarios | Ladder header showed "6 scenarios, 525 max VUs" (the largest step), so ladders do not sum VUs. |
| Bundled Windows Python ignores `PYTHONPATH` | `tools/python312` is an embeddable build (`._pth`); scripts insert paths explicitly. Run analysis with `PYTHONUTF8=1`. |
| Count scrape failures only for live pods | A pod stopping for a scale-down fails its last scrape; the validator now requires the pod to be seen after the sample and not deleted within 15 s. |
| Long runs belong on the VM | `ecommerce-vm` runs unattended in tmux; `~/run-openloop-vm.sh <dir> yes` resumes after failures and stops AKS when done or after 4 attempts without progress. |
