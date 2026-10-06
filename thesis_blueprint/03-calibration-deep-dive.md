# Thesis Blueprint — Part 03: Closed-Loop Calibration Deep Dive

> Part of the thesis blueprint — index and executive summary: [thesis_blueprint.md](../thesis_blueprint.md).
> Sections moved verbatim from the single-file blueprint on 2026-10-06; original section numbers (§N) and finding numbers (#N) are kept so every cross-reference still resolves. Later additions are marked with their date.

---

### Shipping-Rate-Service Calibration Deep Dive (April 17–18, 2026)

This section records the full reasoning chain behind each calibration decision for shipping-rate-service, with explicit thesis implications.

#### Why `ramping-vus` Instead of `ramping-arrival-rate`

**Decision:** Replace `ramping-arrival-rate` with `ramping-vus` as the k6 executor for all shipping-rate-service tests.

**Technical reason:** `ramping-arrival-rate` is an open-loop executor — k6 fires requests at the specified rate regardless of whether the service is keeping up. When the service saturates, requests pile up in a VU queue. This generates *artificially inflated error rates* that reflect k6's queuing behavior, not the service's actual degradation curve. For a wait-dominant fan-out service (shipping-rate-service calls 3 carrier endpoints with ~200–800 ms simulated delay), the pod's asyncio event loop has no graceful backpressure signal to send to k6's open loop, so errors appear earlier and more abruptly than they would in real production traffic.

`ramping-vus` is a closed-loop executor — each virtual user completes one request before starting the next. This naturally self-regulates throughput via Little's Law: `throughput = VUs / avg_response_time`. When the service slows down, throughput drops proportionally but errors do not spike artificially. This produces the smooth degradation curve that autoscaler comparison research needs.

> ⚠️ **Correction (2026-10-06, open-loop pilot — Part 08):** with a correctly sized open-loop generator (all VUs preallocated at ≥ 1.5 × rate × a 5 s timeout) k6 is not the source of the errors: 20 pilot runs dropped 0 iterations, k6 used ≤ 0.13 cores and never ran out of VUs, and the failures were server-side (request timeouts plus TCP dial timeouts/refusals while one shipping pod collapsed above ~55 req/s). The April observation that one pod "generated errors at 60 RPS" was real overload behaviour, not "k6's queuing behavior". The choice of `ramping-vus` still stands for the final dataset, but the accurate justification is that closed loop measures scaling under self-throttled load, while open loop measures scaling under a fixed offered load (and needs load shedding in the service to stay observable — Part 08 §8.9–§8.10).

**Thesis implication:** Using `ramping-vus` makes the B1 (underprovisioned) results *more conservative* — the service degrades gracefully with high latency rather than failing loudly with errors. This is methodologically stronger because: (1) it matches production behavior more closely, (2) the B1/B2 differentiation comes from measurable p95 latency ratio rather than error rate, which is a richer signal for thesis analysis, and (3) autoscalers triggering on latency-driven load is more realistic than autoscalers triggering on artificially induced error storms.

#### Why PEAK_VUS = 80

**Decision:** Lock PEAK_VUS = 80 for all shipping runs (first fixed for the 18-run first sweep; retained for the final 90-run set).

**Calibration data:**

| VUs | B1 p95 | B1 Errors | CPU @ peak | B1/B2 ratio | Verdict |
|-----|--------|-----------|-----------|------------|---------|
| 70 | 4.21 s | 0% | 372 m (149%) | ~4.4× | p95 acceptable but margin too low |
| **80** | **5.10 s** | **0%** | **290 m (116%)** | **5.56×** | **✅ Selected** |
| 100 | 9.49 s | 0% | 500 m (200%) | ~10× | CPU throttled, near timeout boundary |
| 120 | 11.81 s | 19.6% | 358 m (143%) | — | ❌ Errors disqualify |

**Selection rationale:**
- **0% errors** — no artificial error signal contaminating the autoscaler comparison
- **5.56× B1/B2 p95 ratio** — statistically large differentiation between provisioning levels, sufficient to distinguish autoscaler effectiveness in BAB 4
- **CPU not throttled** — at VU=100 the pod is CPU-throttled (500 m against a 500 m limit), which distorts the CPU-HPA comparison because throttling makes CPU appear to plateau even though load is still increasing
- **Below the 10 s carrier timeout** — p99 at VU=80 stays below 10 s, so there is no carrier-timeout error contamination

**⚠️ Calibration provenance:** the ladder above was measured in April 2026 with HTTP keep-alive still enabled, so its absolute p95 values (5.10 s at VU=80) do not match the final dataset. **PEAK_VUS = 80 remains the correct choice** — the ladder's purpose was to pick a VU level with 0% errors, no CPU throttling, and clear B1/B2 separation, and all three still hold post-fix. Only the absolute latencies shifted.

**Thesis implication — report the *measured* gate, not the calibration-ladder gate.** The B1/B2 ratio is the scientific validity gate: if B2 (5 pods) cannot outperform B1 (1 pod) significantly, the workload is not app-tier-sensitive and autoscaler comparison is meaningless. Measured on the final 180-run dataset:

| Service | Gradual | Spike | Oscillating |
|---------|---------|-------|-------------|
| shipping-rate-service | 3.51× | 3.62× | 3.57× |
| auth-service | 2.98× | 3.14× | 2.72× |

Every cell clears the gate. Shipping sits at ~3.5–3.6× and auth at ~2.7–3.1×, all within the accepted 2–3×+ band, with shipping comfortably above it. The gate is narrower than the 5.56× quoted from the April ladder because disabling connection reuse improved B1 (a single pod no longer suffers keep-alive queueing) far more than B2. **Report these six figures in BAB 3 (Metode Penelitian) as the load calibration evidence — not the 5.56×, which was measured under the defective generator.**

#### Why the Service Is Not Purely Wait-Dominant at High VUs

**Finding:** At VU=80, the shipping-rate-service pod consumes 290 m CPU — 116% of its 250 m resource request. H1 (70% CPU threshold = 175 m) and H2 (50% CPU threshold = 125 m) both trigger scaling. This was unexpected.

**Root cause:** asyncio is not truly CPU-free at high concurrency. At 80 simultaneous coroutines, the Python event loop generates measurable CPU overhead from:
1. **Coroutine scheduling** — selecting which coroutine to run next at each `await` point
2. **httpx connection pool management** — SSL handshakes, socket polling, connection reuse
3. **JSON serialization** — deserializing carrier responses and re-serializing the aggregate quote
4. **Prometheus instrumentation** — counter and histogram operations on every request
5. **FastAPI request routing** — Pydantic validation, dependency injection overhead

**Revised thesis narrative:** The original framing was "CPU HPA should fail on a wait-dominant service because the CPU signal is too weak." This is now replaced with a more nuanced and actually *stronger* claim:

> "For fan-out aggregation services, both CPU and request-rate signals generate autoscaling activity, but they differ in **timing precision and proportionality**. CPU-based scaling (H1/H2) reacts to event-loop overhead, which is a byproduct of concurrency rather than a direct measure of user-visible degradation. Request-rate scaling (H3/K1) reacts directly to traffic intensity, which is the root cause of latency increase. This difference in signal semantics produces measurable differences in scale-up timing, pod headcount, and time-to-recovery that constitute the empirical contribution of this thesis."

**Thesis implication:** This finding makes the thesis *stronger* in three ways:
1. **It is a more honest result** — claiming CPU HPA "simply fails" would be an exaggeration. Showing that it *responds to a different signal with different timing* is a more sophisticated and defensible finding.
2. **It provides a concrete research contribution** — the distinction between "metric that correlates with load" and "metric that causes load" is the core academic insight. Request rate is the *cause*; CPU overhead is an *effect* (and a noisy one at high coroutine counts). This maps directly to BAB 4 analysis and BAB 5 conclusions.
3. **It opens the door for a timing analysis** — H3/K1 should scale *earlier* in the ramp than H1/H2 because they react to the root cause rather than its consequence. If the Prometheus data confirms this, it becomes a publishable-quality finding.

#### H3/K1 Threshold Recalibration: 5 → 15 req/s/pod

**Decision:** Raise the `averageValue` (H3) and `threshold` (K1) from 5 to 15 req/s/pod.

**Problem with threshold = 5:** The original threshold of 5 req/s/pod was calibrated when the shipping service used `ramping-arrival-rate`. Under that executor, Prometheus observed only 10–15 req/s from the single pod even when k6 was trying to send 60 req/s — because errors and backpressure ate the undelivered load. With `ramping-vus`, the same 10 BASE_VUS at ~750 ms avg latency generates `10 / 0.75 = 13.3 req/s` cleanly, with no errors. A threshold of 5 would cause H3 and K1 to scale up *during the warm-up phase*, before peak load even begins. This would pollute the B1-level starting condition and make H3/K1 look faster than they are.

**New threshold = 15:** At VU=80 peak, Prometheus observed 16.6 req/s/pod. Threshold of 15 fires when the pod is at ~90% throughput capacity. It remains silent at warm-up (13.3 req/s < 15). KEDA scaling math: `ceil(16.6 / 15) = 2 replicas` — matches H3 AverageValue semantics exactly.

**Important note for BAB 3:** H3 and K1 use the *same numeric threshold* (15) but the underlying Kubernetes mechanics differ. H3 HPA computes `desiredReplicas = ceil(currentMetricValue / averageValue)` where `currentMetricValue` is the sum over all pods. K1 KEDA computes `desiredReplicas = ceil(queryResult / threshold)` where `queryResult` is the raw PromQL aggregate. Since both query `sum(rate(http_requests_total{job="shipping-rate-service"}[1m]))`, the math is identical. This equivalence is intentional — it isolates the autoscaler *engine* (HPA vs KEDA controller) from the *metric semantics* (same query, same threshold), which is required for a fair head-to-head comparison.

#### Pre-Flight Bug Fixes (April 17, 2026)

Before launching the 18-run matrix, a deep pre-flight audit found 4 bugs. All were fixed.

| Bug | File | Root Cause | Fix | Thesis Impact |
|-----|------|-----------|-----|--------------|
| Stale state file | `.experiment-state` | 5 calibration runs wrote duplicate `DONE:shipping_b1_gradual_rep1` entries | Removed all shipping entries; deleted stale results dir | Would have caused `--resume` to skip B1 gradual, corrupting the dataset |
| Wrong env var names | `run-experiment.sh` | Runner set `BASE_RPS`/`PEAK_RPS` but k6 reads `BASE_VUS`/`PEAK_VUS` | Renamed to `SHIPPING_BASE_VUS`/`SHIPPING_PEAK_VUS` throughout | k6 used correct template defaults (harmless), but runner could not override VUs at runtime |
| Misleading metadata | `run-experiment.sh` | `metadata.json` recorded `"base_rps": 10, "peak_rps": 60"` | Conditional logic: shipping records `"base_vus": 10, "peak_vus": 80"` | Metadata is the ground truth for the validator and thesis appendix; wrong units would cause confusion |
| Validator false alarm | `deep_validate.py` | `expected_request_count()` used RPS×time math, overestimating by 32% | Added `SHIPPING_EXPECTED_REQUESTS` with calibrated per-pattern minimums (15k/12k/10k) | Every B1 shipping run would have flagged as A1-RPS critical, causing false re-runs |
