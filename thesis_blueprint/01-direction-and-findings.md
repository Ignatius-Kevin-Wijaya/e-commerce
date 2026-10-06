# Thesis Blueprint — Part 01: Thesis Direction, Validated State and Confirmed Findings

> Part of the thesis blueprint — index and executive summary: [thesis_blueprint.md](../thesis_blueprint.md).
> Sections moved verbatim from the single-file blueprint on 2026-10-06; original section numbers (§N) and finding numbers (#N) are kept so every cross-reference still resolves. Later additions are marked with their date.

---

## 1. Re-analysis of the Current Thesis Direction

### What changed since the prior analyses

The thesis has evolved through five iterations:
1. **Original outline** (5.5/10): HPA-on vs HPA-off — confirmation experiment, no novelty
2. **Revised scope** (8/10): HPA threshold × scaling policy matrix — added depth but remained within reactive scaling paradigm
3. **First KEDA blueprint** (8.5/10): HPA vs KEDA — paradigm comparison, but had a fairness flaw (changing two variables at once: engine AND metric type)
4. **Factorial-design blueprint** (9/10): HPA (CPU) vs HPA (request-rate via prometheus-adapter) vs KEDA (request-rate) — **controlled factorial design** that isolates the metric-type effect from the engine-architecture effect
5. **Current evidence-bearing state** (this revision): same factorial design, backed by a **complete, uniformly clean 180-run dataset** re-run 2026-08-15→17 after the connection-reuse defect was found and fixed (finding #12). **All 180 runs have valid Prometheus exports, and 177 of 180 report 0.00% error** (the other three — shipping oscillating H2 rep1, H3 rep4, K1 rep2 — are at 0.02%, 0.04% and 0.01%); `validate-results.sh` returns 0 critical / 0 warnings / 0 info and `deep_validate.py` returns 0 critical. The earlier asymmetry — clean shipping versus partially contaminated auth — is gone: migrating auth to closed-loop `ramping-vus` eliminated the open-loop saturation meltdowns entirely. Auth-service remains the **CPU-dominant control**, shipping-rate-service is the **wait-dominant comparison service**, and product-service is retained only as an **exploratory dependency-limited appendix case**
6. **Open-loop study (added 2026-10-06, in progress):** a correctly sized open-loop (`ramping-arrival-rate`) generator was piloted on 20 runs (2026-10-05/06). The generator proved stable (0 dropped iterations, delivered = offered), but the services collapse under open-loop overload and the pod-exported request-rate metric goes blind, so the between-config spread is more than an order of magnitude larger than in closed loop. The user decided to switch the full campaign to open loop **only if it is robust**; v2 fixes (admission control, auth pre-authentication, a pre-registered robustness gate) are implemented and a 9-run smoke test is running. Findings #17–#22 below; full details in [Part 08](08-open-loop-study.md). The closed-loop dataset stays authoritative until an open-loop campaign passes its gate.

### What is good about the HPA vs KEDA theme

1. **It asks a fundamentally better question.** Instead of "which HPA setting is best?" (optimization within one tool), it asks "which autoscaling paradigm is better for which workload type?" (strategic architectural comparison). This is a senior-engineer-level question, not a config-tuning exercise.

2. **It directly addresses the #1 HPA limitation, but now in a cleaner and more realistic way.** CPU-based HPA can fail when CPU stops correlating with user load, and request-rate scaling addresses that mismatch directly. The updated AKS findings showed that product-service was not a clean counterpart because downstream DB capacity dominated too easily. That led to a stronger design choice: keep product-service as evidence of the "wrong tier" problem, but run the final controlled non-CPU comparison on a purpose-built wait-dominant service instead of forcing a confounded result.

3. **KEDA is industry-relevant.** KEDA is a CNCF graduated project and a standard AKS add-on. Comparing it against native HPA is practical research that practitioners care about.

4. **Your infrastructure already supports it.** Your FastAPI services use `prometheus_fastapi_instrumentator`, which exposes `http_requests_total` and `http_request_duration_seconds`. KEDA's Prometheus scaler can consume these directly — no code changes needed.

### What is weak or risky

1. **KEDA adds engineering complexity.** Setting up KEDA's Prometheus scaler requires understanding `ScaledObject`, trigger queries, metric naming, polling intervals, and cooldown periods. If the Prometheus query returns unexpected values, KEDA won't scale — and debugging this under a thesis deadline is stressful.

2. **~~The comparison must be fair.~~** ✅ **RESOLVED in this revision.** The prior blueprint compared HPA (CPU-based) against KEDA (request-rate-based), which changed TWO variables at once (engine AND metric type). A reviewer could argue the improvement comes from the metric, not KEDA. **This revision adds H3 (HPA + request-rate via prometheus-adapter)**, creating a proper 2×2 factorial design that isolates each variable. See Section 6 for the full controlled comparison matrix.

3. **KEDA's scale-to-zero adds a confound.** KEDA can scale to zero replicas during idle periods. HPA cannot go below `minReplicas`. If you enable scale-to-zero, KEDA tests include cold-start latency that HPA tests don't face. You must either disable scale-to-zero (simpler comparison) or measure it separately (more interesting but more complex).

4. **prometheus-adapter adds engineering complexity.** Bridging Prometheus metrics into the Kubernetes Custom Metrics API requires configuring metric naming rules, API registration, and debugging "custom metric not found" errors. This is the second-highest-risk component after KEDA itself. Budget 3-5 days for setup and debugging.

### What must be fixed from previous analyses

| Issue from Prior Analysis | Status | Resolution |
|--------------------------|--------|------------|
| No statistical methodology | ✅ Fixed | 5 repetitions, Wilcoxon signed-rank, 95% CI |
| Unrealistic k6 load test | ✅ Re-scoped and implemented | Auth now uses weighted `/auth/me` + `/auth/login`. Product calibration proved the original non-CPU candidate was too dependency-sensitive for the core matrix. A dedicated shipping-rate workload with controlled outbound wait has now been implemented, smoke-tested, and calibrated as the core non-CPU comparison path. |
| Monitoring pods have no resource requests | ✅ Fixed in Kubernetes manifests | Prometheus, Grafana, Loki, and Promtail now declare requests/limits in the AKS manifests |
| Identical HPA configs across all services | ✅ Resolved by design | Only 2 services tested, each independently |
| maxReplicas conflict (outline vs code) | ✅ Fixed | Standardized to `maxReplicas: 5` |
| AKS node sizing with KEDA overhead | 🔧 New | Addressed in Section 4 |
| Fairness argument (2 variables changed) | ✅ Fixed | Added H3 (HPA + request-rate via prometheus-adapter) — isolates metric type from engine |

### What has now been validated on AKS (as of 2026-08-17 — final post-fix 180-run dataset)

- **All 180 runs are complete.** The full matrix — 6 configs × 3 patterns × 5 reps × 2 services — has been executed and stored in `experiment-results/`. The `.experiment-state` file contains 180 `DONE:` entries. The stored dataset is the post-fix re-run of 2026-08-15 → 08-17 (finding #12); every earlier campaign is superseded.
- **Auth-service is now a calibrated CPU-bound control.** The original auth load was too aggressive, the original request-rate threshold was unreachable for H3/K1, and the original `100m` CPU request made CPU HPA unfairly eager. Those issues have been corrected and verified live on AKS. Its load profile was then migrated from open-loop `ramping-arrival-rate` (`10 -> 40` RPS) to closed-loop `ramping-vus` (`BASE_VUS=1`, `PEAK_VUS=12`) on 2026-08-15 (finding #16).
- **Shipping-rate-service has a clean 90-run post-fix dataset (all 5 reps).** The service fans out to mock carriers and mostly waits on outbound quote latency; it is exposed through the API gateway in the application, while the k6 tests target its Service ClusterIP directly. `deep_validate.py` reports 0 critical issues and 0 warnings across all 90 shipping runs. (The superseded pre-fix 90-run set received the same validator verdict but was invalid: the validators had no per-pod load-distribution check, so connection pinning went undetected — finding #12.)
- **Product-service should no longer be described as the final non-CPU thesis service.** It is a mixed DB-backed workload, and once the dataset/load become interesting enough the single `product-db` can become the true bottleneck. In that regime, scaling the app tier may not help and can even make outcomes worse.
- **Threshold calibration is service-specific and methodology-specific, not global.** H3 and K1 must share the same threshold within a given service, but the correct auth threshold and the correct shipping threshold do not need to be the same number. Auth calibrates at `5` req/s/pod and shipping at `15` req/s/pod, both under closed-loop `ramping-vus` with the shared 1 m rate window. Auth's `5` was originally derived under the retired arrival-rate profile and was kept after the migration: `BASE_VUS=1` delivers ≈6 req/s, just above the trigger. Product's historical exploratory threshold remained `5` in its older regime.
  - ⚠️ **Correction (2026-10-05, measured on the final dataset):** `BASE_VUS=1` delivers **11.6–15.9 req/s** in the auth base phase (spike runs, k6 progress lines 0:30–1:55, 5 reps: B1 12.1–14.4, B2 15.1–15.9, H3 11.6–15.8), i.e. 2.3–3.2× the 5 req/s/pod trigger, not ≈6 req/s. This is consistent with finding #14's validation note (auth autoscalers already at 2–4 replicas at the end of the warm-up). Shipping's 10 base VUs deliver 14.0–14.2 req/s, just below its 15 req/s/pod trigger. The same stale "~6 req/s" comment remains in `k6-auth-job.yaml`.
- **CPU-request fairness matters academically.** HPA CPU scales on `usage / request`, not `usage / limit`, so an unrealistically tiny CPU request can make H1/H2 look stronger than they really are. This is now explicitly part of the methodology.
- **Seed size and downstream capacity must be calibrated together.** More product rows are not automatically "better" for the thesis. The April 15 ladder showed that changing product seed size can move the system from "too easy" to "DB-bottlenecked" without ever passing through a clean app-tier autoscaling regime unless dependency capacity is controlled too.
- **The strongest final direction is now auth-service + the implemented wait-dominant shipping-rate-service.** This preserves the factorial design while removing the biggest confound from the non-CPU side of the comparison.
- **The thesis remains stronger, not weaker, after the pivot.** Product-service is still useful as an exploratory finding about downstream bottlenecks and the limits of app-tier autoscaling, but it should no longer anchor the final head-to-head matrix.
- **The core evidence is now uniformly clean.** Both services' 90-run sets pass both validators with 0 critical issues; the earlier asymmetry (clean shipping vs artifact-contaminated auth) disappeared with the 2026-08 re-run.

### Detailed Confirmed Findings

1. **Auth-service is genuinely CPU-bound.** The bcrypt-heavy auth path drives CPU hard enough that CPU utilization is a valid autoscaling signal. This makes auth-service the thesis control scenario where H1/H2 are expected to remain competitive.

2. **CPU-based HPA was originally helped by configuration, not just by metric suitability.** With `request.cpu: 100m` and `limit.cpu: 500m`, H1 at `70%` effectively reacted around `70m` actual CPU. Raising auth-service and product-service to `250m` removed the biggest fairness confound and made the CPU-trigger points academically defensible.

3. **Request-rate autoscaling can look falsely weak when thresholds are calibrated against offered load instead of observed Prometheus load.** On both auth-service and product-service, the old `50 req/s` threshold was too high relative to the metric Prometheus actually exposed from a saturated single pod. This made H3/K1 appear inactive even when the service was already overloaded.

4. **After proper calibration, H3 and K1 were not fundamentally broken.** On auth-service, lowering the threshold to `5` produced live scale-up. On product-service, the same change allowed both H3 and K1 to scale on the heavier datasets. But scaling activity alone is not enough; once the database becomes the limiting component, more app replicas may still fail to improve end-to-end behavior.

5. **Product-service should be described as a mixed read-heavy / DB-backed exploratory case, not a guaranteed pure I/O-bound example.** Search-heavy PostgreSQL reads matter, but app-side CPU from result materialization and JSON serialization still exists and must be measured rather than assumed away.

6. **The corrected `experiment-first` sweep was diagnostically useful but not thesis-valid for product-service.** Auth-service looked mostly usable, but product-service at the old `20 -> 200` profile collapsed across all 18 runs, including scaled configurations. That indicates overall saturation or a downstream bottleneck, not a fair autoscaler comparison.

7. **Product-service seed size is now a first-class experimental variable, not a background detail.** The April 15 AKS ladder showed: `~50k` products with `B2 spike 5 -> 20` still failed at `88.04%`, `~50k` with `B2 spike 2 -> 10` still failed at `76.26%`, `~30k` improved to `39.72%`, and `~20k` with `B2 spike 2 -> 10` became completely healthy. This is direct evidence that the product regime is highly sensitive to catalog size.

8. **At `~20k` products and `2 -> 11` spike load, scaling the app tier did not help.** The most revealing live result was: `B1` stayed healthy (`0%` failed), while `B2` failed at `8.75%`, `H1` failed at `13.09%` while staying at `1` replica, and `K1` failed at `12.42%` after scaling to `3` replicas. That is strong evidence that the single `product-db` was the real bottleneck and that scaling the wrong tier can worsen outcomes.

9. **The deeper thesis finding is now metric-to-workload fit plus bottleneck location.** CPU works well for clearly CPU-bound workloads, can still work on mixed workloads, and becomes weaker as downstream wait dominates. But there is an additional limit: when a dependency becomes the dominant bottleneck, app-tier autoscaling itself may cease to be the right intervention.

10. **The final controlled non-CPU comparison should use the implemented wait-dominant shipping-rate-service, not the current product-service.** The shipping path fans out asynchronously to three carrier endpoints with controlled delay, making it methodologically cleaner against auth-service than a DB-sensitive product workload.

11. **Product-service still belongs in the thesis, but as an exploratory or appendix result.** It demonstrates a valuable real-world limitation: scaling the wrong tier can make HPA and KEDA both look worse, even when the autoscaler itself is functioning correctly.

12. **🚨 ALL PRE-2026-08-15 RESULTS ARE SUPERSEDED. The entire 180-run dataset was re-run after a load-generator defect was found and fixed.** k6 VUs held HTTP/1.1 keep-alive connections for the whole run, and kube-proxy load-balances per *new* connection — so pods added by the autoscaler after the VUs connected received **zero traffic**, and scaling up could not reduce latency. Measured on the old data: in **20 of 20** autoscaled shipping spike runs, ONE pod ran at 367–396m CPU while every other pod sat at 1–4m. The control that proves it: B2's five *fixed* pods spread evenly (167/124/122/106/76m), because its pods existed before the VUs connected. Fixed by `noConnectionReuse: true` in all six k6 scenarios (commit `7fde0a2`). Justification for BAB 3: the tests hit the Service ClusterIP directly, bypassing the NGINX ingress that re-resolves endpoints in production, so disabling reuse restores realistic redistribution rather than distorting the workload. **Any number in this document dated before 2026-08-15 is an artifact and must not be used.**

13. **The definitive 180-run result (p95 ms, mean ± pop. stdev, 5 reps).** Campaign ran 2026-08-15 06:11 → 08-17 17:05 UTC. **177 of 180 runs report 0.00% error**; the other three are shipping oscillating H2 rep1 (0.02%), H3 rep4 (0.04%) and K1 rep2 (0.01%). Every run has a valid Prometheus export. `validate-results.sh`: 180 runs, **0 critical / 0 warnings / 0 info**. `deep_validate.py`: **0 critical**, 19 warnings (15× `B1-LOW` + 4× `A4`, all on auth b1 — stale heuristics that still assume the retired open-loop profile). Both validators re-run 2026-10-05 with identical results. These are the authoritative numbers for BAB 4/5.

**shipping-rate-service (wait-dominant — the comparison service):**

| Config | Gradual | Spike | Oscillating |
|--------|---------|-------|-------------|
| B1 | 3218 ± 22 | 3324 ± 22 | 3272 ± 15 |
| B2 | 917 ± 0 | 917 ± 0 | 916 ± 0 |
| H1 (CPU 70%) | 920 ± 2 | 1101 ± 177 | **2656 ± 486** |
| H2 (CPU 50%) | 918 ± 1 | 993 ± 109 | 3008 ± 409 |
| H3 (req-rate HPA) | 917 ± 0 | 987 ± 64 | 3096 ± 22 |
| K1 (req-rate KEDA) | **916 ± 0** | **941 ± 10** | 2748 ± 596 |

**auth-service (CPU-bound — the control):**

| Config | Gradual | Spike | Oscillating |
|--------|---------|-------|-------------|
| B1 | 3376 ± 79 | 4560 ± 102 | 3134 ± 102 |
| B2 | 1134 ± 12 | 1452 ± 21 | 1154 ± 27 |
| H1 | 1164 ± 22 | 1496 ± 24 | 1170 ± 19 |
| H2 | **1132 ± 16** | 1486 ± 85 | **1160 ± 32** |
| H3 | 1160 ± 22 | **1462 ± 57** | 1188 ± 25 |
| K1 | 1150 ± 20 | 1476 ± 38 | 1260 ± 25 |

B2 reproduces at 916–917 ms ± 0 across all 15 shipping runs — an exceptionally tight control, which is what licenses treating the differences above as signal.

14. **⭐ THE HEADLINE — normalise as the fraction of the B1→B2 gap closed by the best autoscaler.** This removes the two services' different absolute floors and makes the result a single clean statement:

| Condition | Best autoscaler | Gap closed |
|-----------|-----------------|-----------|
| shipping gradual | K1 916 ms | **100%** |
| shipping spike | K1 941 ms | **99%** |
| **shipping oscillating** | **H1 2656 ms** | **26%** ← the only failure |
| auth gradual | H2 1132 ms | **100%** |
| auth spike | H3 1462 ms | **99.7%** |
| auth oscillating | H2 1160 ms | **99.7%** |

**In five of six conditions the best autoscaler closes ≥99% of the gap and every autoscaler closes ≥92% (lowest: shipping spike H1, 92.4%). Exactly one condition fails: wait-dominant workload under oscillating load, where the four autoscalers close only 7.5–26%.** That single cell is the thesis contribution. **Proposed mechanism (partly verified — see validation note below):** shipping's per-request latency is much longer than auth's (B2 5-rep mean ≈ 709 ms, median ≈ 709 ms, versus auth's ≈ 184–227 ms mean and 13–17 ms median — auth is bimodal: fast `/auth/me`, bcrypt-bound `/auth/login`), so against a 90 s half-cycle shipping's replica count lags the load and ends up out of phase.

**⚠️ Validation note (2026-10-05, `prom_replica_count.json`, 5 reps, windows aligned to the k6 start in `experiment.log`):** the out-of-phase claim holds for shipping — all four autoscalers average 1.9–2.8 replicas during peaks but 3.6–4.2 during troughs. Auth, however, does *not* track the oscillation at all: it already sits at 2–4 replicas at the end of the base-load warm-up, averages 3.9–4.6 replicas during peaks, and stays at or near `maxReplicas` (4.9–5.0) through every trough — under oscillation the auth autoscalers behave almost like B2. The auth/shipping contrast is therefore confounded by load intensity relative to threshold and replica ceiling, and does not by itself isolate service time as the cause. (Earlier revisions quoted shipping ~900 ms and auth ~70–170 ms; those figures did not match the measured latencies and were replaced.) **Scope caveat for BAB 5:** shipping is the only wait-dominant workload tested, so this is a single-workload finding whose mechanism is only partly verified (validation note above), not a general law — frame it as such.

15. **Secondary effects — both real, both small, and both visible only where autoscaling is stressed (shipping spike).**
    - **Metric (CPU vs request-rate):** request-rate 941/987 vs CPU 993/1101 ≈ **10%** advantage (H3 vs H1 −10.4%; K1 vs H2 −5.2%). Within ±2.5% (a tie) in the shipping-gradual and all three auth conditions. On shipping oscillating the ranking is mixed among failing configurations (H1 2656 < K1 2748 < H2 3008 < H3 3096 ms).
    - **Engine (H3 vs K1, identical metric and threshold — the fairness control):** K1 941 ± 10 vs H3 987 ± 64. KEDA is ~**5% faster and 6× more stable**. This is the cleanest engine result in the dataset and the factorial design's main payoff; the pre-fix data could not show it because connection pinning swamped the effect. Elsewhere within ±1%, except two oscillating cells: on auth oscillating HPA wins (H3 1188 vs K1 1260, +6.1%); on shipping oscillating KEDA is better (K1 2748 vs H3 3096, −11.2%) but both fail.
    - **⚠️ The old "request-rate gives −49% on gradual" claim is dead.** All four autoscalers now sit on the B2 floor on gradual (916–920 ms, a 4 ms spread = noise). That gap was entirely connection pinning: request-rate scaled *earlier*, so more pods existed while VUs were still opening new connections. The apparent metric advantage was really "scaled earlier, caught more new connections."

16. **The auth open-loop meltdowns are gone.** The old auth data (B1 at 60 s / 52% error, K1 spike 22 644 ms / 11.9% bimodal) was an artifact of the `ramping-arrival-rate` executor, which drops iterations under saturation and therefore delivered *unequal load* to different configs — making cross-config p95 meaningless. auth-service was migrated to closed-loop `ramping-vus` (commit `2bbdb1f`: `PEAK_VUS=12` calibrated against fixed-replica B1/B2 ladders; `BASE_VUS` lowered from the provisional 3 to 1 in commit `7fde0a2`). Every auth run now reports 0.00% error with tight SDs. A separate fix removed a constant measurement artifact: `setup()` unconditionally re-registered 120 existing users, injecting exactly 120 failures per run *before any load* — which was the entire reported "0.7% error" on otherwise-clean auth runs (commit `a39b1f2`).
    - ⚠️ **Qualification (2026-10-06, open-loop pilot — Part 08):** the meltdowns were not *only* an executor artifact. A correctly sized open-loop generator (all VUs preallocated at ≥ 1.5 × rate × 5 s timeout) dropped **0 iterations in 20 runs** and delivered exactly the scheduled load, yet still produced large failures because an unprotected single-worker pod collapses once offered load exceeds its capacity, and the pod-exported request-rate metric then goes blind. The old configuration (60 s timeout, 400 → 1000 VUs at 40 req/s ⇒ up to 2,400 in flight) guaranteed drops on top of that. The closed-loop dataset remains valid; what changes is the reason for preferring closed loop: not "open loop is broken" but "the two generators measure different things" (findings #17–#18).


#### Open-loop study findings (added 2026-10-06 — details and all tables in [Part 08](08-open-loop-study.md))

17. **A correctly sized open-loop generator is stable.** 20 pilot runs (spike, both services, B1/B2/H2/H3/K1 × 2, 2026-10-05/06): `dropped_iterations = 0` in every run; attempted = offered within 0.02 req/s; k6 never exceeded 0.13 cores, 546 MiB or 527 of 788 VUs; raw per-request data captured and md5-verified for every run (fixing the "Could not copy k6 JSON results" bug the closed-loop runner logged on every run).

18. **Closed loop masks overload; open loop exposes it.** Closed-loop spike peak throughput is self-throttled (shipping B1 25.2–25.4 vs B2 112.4–112.7 req/s; auth B1 12.0–12.9 vs B2 44.6–46.7). Under a fixed open-loop offer (auth 2→30, shipping 10→105 req/s) the H2/H3/K1 spread is **20.3% (auth) / 41.5% (shipping) of the B1→B2 gap in SLO-violation seconds** versus **0.77% / 2.17%** in closed-loop p95 (indicative, n = 2), and the rankings change (auth: request-rate beats CPU; shipping: CPU beats request-rate).

19. **Unprotected pods collapse and the pod-exported request-rate metric goes blind.** One shipping pod is healthy at 50 req/s (p95 930 ms) and fails 100% at 60 req/s; once collapsed it completes almost nothing, so `http_requests_total` (counted on completion) falls and Prometheus can no longer scrape it. Shipping H3/K1 therefore **never scaled** in the pilot (metric peaked at 11.6 req/s/pod against a 15 threshold; H3 `FailedGetPodsMetric` from +52 s; K1 scaled 1→2→1), failing 97.99–99.30% of load-window requests — as badly as B1. CPU (from the kubelet) survives, so H2 scaled (24.65 / 32.01% errors).

20. **When the metric survives, request rate reacts about twice as fast as CPU.** Auth first scale-up after spike onset: H3 21.5–36.5 s, K1 23.1–38.7 s, H2 50.7–66.1 s (CPU-based decisions come only after the HPA's CPU reading refreshes: shipping H2's reading stayed at its pre-spike 22–25% until +49.3 / +63.9 s); pods become Ready 17–19 s after each scale-up. Auth SLO-violation seconds: H3 75, K1 80, H2 155 (means of 2).

21. **Auth `setup()` scales H2 during the warm-up (both datasets).** The 120 bcrypt pre-authentication logins (~28 s, right before the warm-up) drove H2 to 2–3 replicas 54–69 s before onset, then H2 scaled back to 1 as the spike started. The closed-loop campaign runs the same `setup()`; disclose for auth H1/H2 (in closed loop the 12–16 req/s base load already scales the autoscalers, finding #14's validation note). Fixed for v2 by pre-authenticating during the cluster reset.

22. **Load shedding restores observability under overload (v2, 2026-10-06).** With admission control as the outermost middleware (cap 48 in-flight), one shipping pod stays graceful up to 105 req/s (goodput 42.36 req/s, 59.66% fast 503s, 0 timeouts, 0 scrape failures; it still collapses somewhere between 105 and 140 req/s). Placed inside the other middleware it did not help (goodput 7.50 at 105). First smoke run: shipping H3 now scales 1→5 within 83 s, load-window goodput 98.34 of 103.87 req/s, 5.32% errors (all 503s, 0 timeouts) — versus 0.72 req/s and 99.30% errors in the pilot. Second smoke run: shipping K1 reaches 5 pods by +98.8 s, goodput 95.95 of 103.85 req/s, 7.61% errors (all 503s, 0 timeouts) — versus 97.99% errors in the pilot. Both: 70 s SLO-violation (pilot: 410 s). Runs 3–5 (done by 10:11 UTC): shipping H2 13.02% errors (all 503s, 0 timeouts), 100 s SLO-violation (pilot: 24.65 / 32.01%, 170 / 310 s); auth H2 11.48% errors (1.59% timeouts), 140 s, now starting from 1 replica; the single shipping B1 pod held 105 req/s for the whole 7-minute window at 42.32–43.07 req/s goodput per minute with 0 timeouts (pilot: collapse, 99.13% errors). Smoke test still running (4 of 9 runs pending at 10:25 UTC).

### What This Means For The Thesis

- **The original strong claim that "CPU HPA should clearly fail on product-service" is too strong.** Product-service should no longer be treated as the final non-CPU counterpart in the core matrix.
- **The strongest thesis contribution is now a three-part story (post-fix data, findings #13–15).** (1) Auth-service validates the CPU-dominant control: every autoscaler is within ~3% of B2 on all three patterns except K1 oscillating (+9.2%). (2) On shipping gradual and spike every autoscaler closes ≥92% of the B1→B2 gap; metric and engine separate only on shipping spike (request-rate −10.4%, KEDA a further −4.7% with ~6× lower SD). (3) Shipping oscillating is the single failure — the four autoscalers close only 7.5–26% of the gap — so the dominant effect is workload × load pattern, not metric or engine.
- **This makes the thesis more credible, not weaker.** A conditional finding ("metric and engine matter only where autoscaling is stressed, and one workload × pattern cell defeats every configuration") is more defensible than a binary one ("CPU fails, request-rate wins"). The factorial design isolates metric choice from autoscaler engine choice.
- **Methodological calibration is now explicitly part of the contribution.** Fair CPU requests, service-specific VU calibration, executor selection rationale (closed-loop for both services), disabled connection reuse (finding #12), threshold derivation math, and a dependency-isolation gate all explain why prior results were misleading and why the corrected runs are academically defensible. This methodology section will be a key strength in the thesis defense.
- **The data collection phase is complete (final post-fix re-run 2026-08-15 → 08-17).** The next phase is statistical analysis (tests, CI, effect sizes), time-to-scale extraction from `k8s-events.txt`, Resource Cost Index, regenerating `thesis-figures/` (the current PNGs were generated 2026-06-12 from the superseded data), and thesis writing.
- **The final controlled comparison is auth-service vs shipping-rate-service.** Auth-service provides the CPU-dominant control where H1/H2 are expected to be both reactive and proportional. Shipping-rate-service provides the mixed-workload case where H1/H2 still react (via asyncio overhead). On the post-fix data the request-rate advantage appears only on spike; on gradual all autoscalers tie on the B2 floor, and on oscillating all fail (H1 is the least-bad at 2656 ms).
- **Product-service remains in the thesis as a case-study, not as wasted work.** It provides a realistic counterexample showing that autoscaling app pods does not fix every performance problem — specifically, that when a downstream dependency dominates, app-tier scaling can make outcomes *worse* by increasing database connection pressure.
- **The revised thesis central claim (for BAB 5):** On the CPU-bound control, metric and engine choice are immaterial (every autoscaler within ~3% of B2, except K1 oscillating at +9.2%). On the wait-dominant service, any autoscaler suffices for gradual load; under spike load request-rate scaling helps (~10%) and KEDA adds ~5% with markedly lower variance; under oscillating load with a 90 s half-cycle no tested configuration is adequate (≤26% of the gap closed). The decomposition is therefore conditional: metric and engine matter only where autoscaling is stressed, and the workload × load-pattern interaction dominates both. Mechanism and generality claims are limited by the single wait-dominant workload and by the validation note under finding #14.

### Dataset Status (CURRENT — 2026-08-17)

> **Update 2026-10-06:** this closed-loop dataset is still the authoritative dataset for BAB 4/5. Two open-loop datasets now exist alongside it — the 20-run pilot (`experiment-results-pilot-openloop/`, 2026-10-05/06) and the v2 calibration + smoke data (`experiment-results-openloop/`, `experiment-results-openloop-smoke/`, 2026-10-06, smoke in progress). A 180-run open-loop campaign replaces or complements this dataset only if it passes the pre-registered robustness gate (Part 08 §8.9, §8.13). Two closed-loop caveats surfaced in that work: the auth base-throughput correction (above, under "validated on AKS") and the `setup()` warm-up burst (finding #21).

**All 180 runs are complete and uniformly clean.** Every run has a valid Prometheus export; 177 of 180 report 0.00% error and the other three (shipping oscillating H2 rep1, H3 rep4, K1 rep2) are at 0.02%, 0.04% and 0.01%. Re-verified 2026-10-05 from the k6 logs and by re-running both validators.

| Validator | Result |
|-----------|--------|
| `validate-results.sh` | 180 runs — **0 critical, 0 warnings, 0 info** |
| `deep_validate.py` (5 reps, `--strict-matrix`) | 180/180 — **0 critical**, 19 warnings |

The 19 warnings are all on auth `b1` and are **stale validator heuristics, not data defects**: 15× `B1-LOW` (expects the open-loop meltdown that closed-loop VUs no longer produce) and 4× `A4` (could not identify the active load window from the Prometheus RPS series). `A1-RPS`, which compares against the retired `base=10/peak=40` **RPS** profile, fires only at info level. `deep_validate.py` should be updated to branch on `load_profile.version == "closed-loop-vus-v3"`.

**No runs require rerun or qualification.** Both services are fully usable for BAB 4, including all spike and oscillating cells.

---

<details>
<summary><strong>⚠️ SUPERSEDED — dataset status as of 2026-06-03 (kept for provenance only; do not use)</strong></summary>

The assessment below describes the **pre-fix** dataset, which was discarded in the 2026-08 re-run. Its conclusions about which runs were clean no longer apply — and note that its "clean shipping, 0 critical / 0 warnings" verdict was itself misleading, because the validators had no check for load distribution across pods and therefore could not detect that autoscaler-added pods were receiving zero traffic (finding #12).

All 180 runs are complete. The dataset is asymmetric in quality:

**Shipping (90/90 clean):** All configs, patterns, reps pass `deep_validate.py` with 0 critical / 0 warnings. This is publishable. Wilcoxon tests and effect-size calculations can be run directly from the on-disk data.

**Auth — clean data:**
- **Gradual (all configs, all 5 reps):** Fully clean. Use these for the CPU-bound control story.
- **Spike / Oscillating — H1, H2:** Mostly clean but with variance (some dropped iterations in individual reps; Prometheus exports are intact). Usable with documentation of variance.

**Auth — requires attention before BAB 4:**
- **H3 spike rep1, rep2 / H3 oscillating rep1, rep2 / K1 spike rep1:** Total Prometheus-export loss (all 5 prom_*.json = empty `result:[]`). k6 client-side p95 numbers survive but there is no server-side scaling/CPU/latency timeseries. These 5 runs need targeted reruns OR must be excluded from server-side analysis with explicit notation.
- **K1 oscillating rep1, rep2 / H3 oscillating rep3-5:** Genuine saturation (dropped iterations >200, p95 at 60s ceiling for K1). These are real findings about autoscaler limits, not tooling failures, but the unequal offered load means cross-config p95 comparison requires careful qualification.

**Remaining work before statistical analysis:**
1. **Decision on 5 empty-export runs:** Either rerun `h3/spike r1+r2`, `h3/oscillating r1+r2`, `k1/spike r1` to get server-side timeseries, or proceed using only k6 client-side metrics for those 5 runs with explicit methodology note.
2. **Run Wilcoxon signed-rank tests** across the 5-rep distributions for the primary KPIs (shipping gradual is ready; shipping spike/oscillating ready; auth gradual ready).
3. **Extract time-to-scale** (load-onset → first `SuccessfulRescale` event) — this primary KPI is not yet computed from the stored artifacts.
4. **Lock product-service as appendix-only** — product results stay outside the pooled core statistics.

</details>



