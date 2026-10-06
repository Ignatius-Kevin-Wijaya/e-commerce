# Open-Loop Pilot Report — HPA vs KEDA load-generator decision

Pilot run 2026-10-05 18:57 → 2026-10-06 01:39 UTC on `ecommerce-vm` against AKS `ecommerce-aks`.
Data: `experiment-results-pilot-openloop/` (20 runs, 6 calibration ladders, `analysis/summary.json`).
Analysis: `PYTHONUTF8=1 tools/python312/python.exe scripts/pilot_openloop.py validate | report | ladder`.

## 1. Decision

**Pre-registered rule result: GO** — criteria 1, 2, 3 and 5 pass; criterion 4 fails the ±25% test for two of six
autoscaled cells (auth H3, shipping H2), and both disagreements trace to a ~15 s difference in the autoscaler's first
post-onset decision, visible in the events and HPA timelines (the rule's explanation clause, §3.4).

| # | Criterion | Result | Evidence (one line) |
|---|---|---|---|
| 1 | dropped_iterations = 0 in all 20 runs | **PASS** | 0 in every run; attempted rate = offered rate within 0.02 req/s in every run |
| 2 | B2: error < 1% and window p95 ≤ SLO | **PASS** | auth 0.00% / 887 & 843 ms vs 1500; shipping 0.00% / 919 & 917 ms vs 1200 |
| 3 | B1 clearly overloaded | **PASS** | auth 86.18% / 85.50% errors, shipping 99.13% / 99.15%; SLO violated in all 410 s of every B1 run |
| 4 | Reps agree (±25%) or disagreement explained by poll phase | **FAIL on ±25%, explained** | auth H3 90 vs 60 s (40%), shipping H2 170 vs 310 s (58%); first scale-up 15.0 s / 14.6 s apart |
| 5 | Per-pod distribution passes in all autoscaled runs | **PASS** | no pod below 20% of the mean share (lowest 0.74); 4 shipping runs never had 2 pods Ready ≥ 60 s, so the check did not apply |

**Is the spread between H2, H3 and K1 larger than in the closed-loop data? Yes, by more than an order of magnitude**
(indicative only, n = 2):

| Service | Closed loop: H2/H3/K1 p95 range as % of B1→B2 gap | Open loop: SLO-violation range as % of B1→B2 gap | Open loop: error-% range as % of B1→B2 gap |
|---|---|---|---|
| auth | 0.77% (1462–1486 ms of a 3108 ms gap) | 20.3% (75–155 s of a 395 s gap) | 9.1% (8.90–16.75 points of 85.84) |
| shipping | 2.17% (940.7–992.9 ms of a 2407 ms gap) | 41.5% (240–410 s of a 410 s gap) | 71.5% (28.33–99.18 points of 99.14) |

The ranking also changes. Closed loop: all three within 1.6% (auth) and 5.5% (shipping), K1 best on shipping.
Open loop: on auth the request-rate configs (H3, K1) beat CPU (H2) in both reps; on shipping CPU (H2) beats
request-rate, because H3 and K1 never scale (§4.1).

**What GO certifies, and what it does not.** GO means the open-loop generator is *stable*: it delivers exactly the
scheduled load to every configuration, never runs out of VUs, is not CPU-bound, and B1/B2 bracket the system as
intended. The failures it records are the system's, not k6's. GO does **not** mean an open-loop campaign measures the
same thing as the closed-loop one. Before switching, decide on the three points in §6 — in particular whether the
shipping H3/K1 "metric blindness" (§4.1) is a result you want the thesis to rest on.

## 2. What was run

- **Matrix:** {auth-service, shipping-rate-service} × spike × {B1, B2, H2, H3, K1} × 2 reps = 20 runs, order shuffled
  within each rep block (seed 20261005, frozen in `.pilot-plan`). All 20 runs completed on the first attempt.
- **Only the generator changed.** Autoscaler manifests, thresholds (auth 5, shipping 15 req/s/pod), behaviour blocks,
  1 m rate window, RESET_WAIT 120 s / STABILIZE_WAIT 90 s / EXPORT_WAIT 180 s are the final campaign's.
- **Generator:** `ramping-arrival-rate`, same spike shape as closed loop (2 m base → 10 s jump → 6 m 50 s peak → 3 m
  ramp-down), same request mix, login-first `setup()`, shipping payload, `noConnectionReuse: true`. Request timeout
  5 s (timeouts are failed requests). preAllocatedVUs = maxVUs = ⌈1.5 × peak × 5 s⌉ = 225 (auth), 788 (shipping).
  No k6 thresholds. k6 pinned to `grafana/k6:0.46.0` for both services (closed-loop auth used unpinned `:latest`).
- **Rates and SLOs** (fixed before the pilot, `pilot-config.env`):

| | Base req/s | Peak req/s | SLO (window p95) | Why |
|---|---|---|---|---|
| auth | 2 | 30 | 1500 ms | C = 10, B2 healthy ceiling = 40 → peak = 75% of 40 and ≥ 2.5 × C. Base 2 (not 4): at 4 req/s single-pod CPU reached 147m = 59% of request, which would scale H2 during warm-up. SLO ≈ closed-loop B2 spike p95 (1452 ms). |
| shipping | 10 | 105 | 1200 ms | C = 50, B2 healthy at 140 (22% errors at 200) → peak = 75% of 140. The ≥ 2.5 × C rule (125) conflicts; it was relaxed because B1 already fails 100% at 60 req/s. SLO ≈ 1.3 × closed-loop B2 p95 (917 ms). |

- **Metric definitions** (fixed in `scripts/pilot_openloop.py` before the pilot ran): latency = client wall-clock per
  request including TCP connect (`req_e2e_duration`); requests binned by start time; failed requests count as infinitely
  slow; load window = k6 t ∈ [120 s, 540 s); SLO-violation seconds = 10 s bins in that window with p95 > SLO; "B1
  clearly overloaded" = SLO-violation ≥ 210 s or error ≥ B2 error + 5 points, in both reps; rep agreement =
  |a − b| / mean(a, b) ≤ 0.25.
- **Phase 2 fix confirmed:** every run's gzipped per-request JSON reached disk with a matching md5 (ladders 1.5–28 MB,
  pilot runs 2.6–9.0 MB); the closed-loop runner never captured this file.

## 3. Criteria — evidence

### 3.1 Dropped iterations and delivered load (PASS)

All 20 runs: `dropped_iterations = 0`, full 12 m schedule, 0 interrupted iterations, k6 exit 0, raw data verified.
Load-window offered vs attempted: auth 29.67 vs 29.67 req/s, shipping 103.87 vs 103.85–103.87 req/s. k6 never needed
more than 150 of 225 (auth) or 527 of 788 (shipping) VUs, peaked at 0.13 cores of its 2-core limit with ≤ 0.5% of CFS
periods throttled, and at 546 MiB of its 4 GiB limit. The generator delivered identical load to every configuration —
the June open-loop defect (config-dependent delivered load) is absent.

### 3.2 B2 healthy (PASS)

auth B2: 0.00% errors, window p95 887 / 843 ms (SLO 1500), p99 1927 / 1857 ms, SLO-violation 20 / 10 s.
shipping B2: 0.00% errors, window p95 919 / 917 ms (SLO 1200), p99 934 / 934 ms, SLO-violation 0 / 0 s.
The auth B2 violations are isolated bcrypt-tail bins (1671–1965 ms) with 5 pods Ready — background, not overload.

### 3.3 B1 clearly overloaded (PASS)

auth B1: 86.18% / 85.50% errors (all timeouts), goodput 4.10 / 4.30 req/s of 29.67 offered.
shipping B1: 99.13% / 99.15% errors (98.59% / 98.62% timeouts, the rest TCP dial timeouts/refusals), goodput
0.91 / 0.89 req/s of 103.87. Every 10 s bin of the 410 s window violates the SLO in all four runs.

### 3.4 Rep agreement (FAIL on ±25%, explained by poll phase)

| Cell | SLO-violation s (r1 / r2) | Diff | First scale-up s after onset (r1 / r2) | Verdict |
|---|---|---|---|---|
| auth H2 | 140 / 170 | 19% | 66 / 51 | agree |
| auth H3 | 90 / 60 | 40% | 36.5 / 21.5 | disagree → explained |
| auth K1 | 70 / 90 | 25.0% | 23.1 / 38.7 | agree (boundary) |
| shipping H2 | 170 / 310 | 58% | 63.9 / 49.3 | disagree → explained, amplified |
| shipping H3 | 410 / 410 | 0% | none / none | agree (both total failure) |
| shipping K1 | 410 / 410 | 0% | 19.0 / none | agree (both total failure) |

Window p95 agrees trivially: every autoscaled run had > 5% failures in the load window, so p95 lands in the failures
("fail") in both reps. SLO-violation seconds therefore carries the comparison.

- **auth H3.** Rep2's first HPA scale-up came 15.0 s (one 15 s sync period) earlier; its first new pod was Ready 17 s
  earlier (38 vs 55 s). The hard-failure block is identical (6 bins, 0–60 s, in both reps). Rep1 has one extra recovery
  bin (60–70 s, p95 2089 ms) and two isolated bins at full scale (1516 ms and 1772 ms) of the same kind B2 shows
  (1671–1965 ms). Poll phase explains the block difference; the rest is background.
- **shipping H2.** H2's CPU reading stayed at its pre-spike 22–25% until the first decision at +49.3 s (rep2) and
  +63.9 s (rep1). Rep2's first fresh reading, 14.6 s earlier, read 139%, so H2 scaled **1→3**; rep1's read 162% and
  scaled **1→4**. With 3 pods, one of them the original pod that had already collapsed, the two others would each have
  to carry ≈ 52 req/s (105 / 2) — at the single-pod cliff (§5) — and a second pod collapsed too (two pods unscrapeable
  in rep2, one in rep1). Rep2 reached
  4 pods at 109 s and stayed in violation until 300–310 s; rep1 recovered at 160–170 s. The trigger is the visible poll
  phase; the 140 s magnitude comes from metastable collapse amplifying it. **If you read criterion 4 as requiring the
  difference itself to be phase-sized, this cell fails and the rule gives STAY.**

### 3.5 Per-pod distribution (PASS)

No Ready-≥60 s pod received < 20% of the mean per-pod request rate or CPU in any run. Lowest mean rate share: 0.74
(auth H2 r1, pod `jt5jx` — created by the warm-up scale-up at −54 s and removed at +23 s, §4.3); B2 shares 0.96–1.06. The four shipping H3/K1 runs never had two pods Ready for 60 s,
so the check had nothing to compare; there was nothing to pin. The validator separately warns (8 warnings, 0 critical)
about pods too overloaded to answer Prometheus scrapes — all shipping, all collapse-related.

## 4. What the open loop revealed

### 4.1 Shipping H3/K1 never scale: the request-rate metric goes blind under overload

At spike onset one shipping pod receives 105 req/s against a cliff at ~55 req/s and collapses within seconds. The
H3/K1 metric (`rate(http_requests_total[1m])`, exported by the pod itself) counts **served** requests, so it fell
instead of rising: the HPA read 10.1 → 11.1 → 11.5 → 7.7 req/s/pod (shipping H3 r1), then `FailedGetPodsMetric` from
+52 s once Prometheus could no longer scrape the pod (`up = 0` observed live during run 1). KEDA read 10.1 → 11.6 →
8.1 → 0 (K1 r2). Neither ever crossed the 15 req/s/pod threshold. K1 r1 caught one value above it and scaled to 2 at
+19 s, then scaled back to 1 ("All metrics below target") under the shared 30 s / 100% scale-down policy. Result:
97.99–99.30% errors, identical to B1. H2 survives because CPU comes from the kubelet, not from the overloaded app.

This is a real property of this setup (pod-exported request counter + open-loop load beyond one pod's capacity), not a
generator artifact. The closed loop never shows it, because a closed-loop pod is never pushed past its cliff.

### 4.2 Request-rate reacts ~2× faster than CPU when the metric survives (auth)

On auth the pod stays scrapeable, and request-rate scaling is clearly faster: first scale-up H3 21.5–36.5 s, K1
23.1–38.7 s, H2 50.7–66.1 s; first new pod Ready 17–19 s after each scale-up in every config. SLO-violation: H3 75 s,
K1 80 s, H2 155 s (means). The closed loop showed a tie (1462 / 1476 / 1486 ms).

### 4.3 Auth H2 starts the spike already scaling — caused by `setup()`

Auth `setup()` performs 120 bcrypt logins in ~28 s just before the scenario. H2 read 82% CPU about a minute later and
scaled during the warm-up (1→2 in r1, 1→3 in r2, 54–69 s before onset), then scaled back down to 1 as the spike began
(r2: 3→1 at +6 s), under the 30 s scale-down window. H3/K1 did not react (setup averages ≈ 4.3 req/s < 5). This
confound exists in the closed-loop campaign too (same `setup()`, same H2 behaviour) and biases H2 in both.

### 4.4 Open loop amplifies small timing differences

Near the shipping cliff, a 15 s difference in the first HPA decision turned into 140 s more SLO violation (§3.4).
Expect large rep-to-rep variance wherever a configuration's capacity hovers near the single-pod cliff.

## 5. Calibration ladders (Phase 4)

| Ladder | Rate req/s | Goodput req/s | Error % | p95 ms | Pod CPU (m, per pod) | k6 CPU cores / MiB |
|---|---|---|---|---|---|---|
| auth B1 | 2 | 2.00 | 0.00 | 477 | 80 | 0.01 / 111 |
| auth B1 | 4 | 4.00 | 0.00 | 518 | 119 | 0.01 / 126 |
| auth B1 | 6 | 6.00 | 0.00 | 534 | 223 | 0.01 / 132 |
| auth B1 | 8 | 8.00 | 0.00 | 783 | 265 | 0.01 / 132 |
| auth B1 | 10 | 10.00 | 0.00 | 1250 | 373 | 0.02 / 135 |
| auth B1 | 12 | 9.46 | 21.20 | fail | 494 | 0.02 / 137 |
| auth B1 | 14 | 8.24 | 41.11 | fail | 500 | 0.02 / 140 |
| auth B1 | 16 | 4.91 | 69.31 | fail | 459 | 0.02 / 140 |
| auth B2 | 20 | 20.00 | 0.00 | 545 | 145, 143, 149, 121, 150 | 0.03 / 287 |
| auth B2 | 30 | 30.00 | 0.00 | 853 | 200, 289, 234, 202, 215 | 0.04 / 348 |
| auth B2 | 40 | 39.99 | 0.03 | 1156 | 359, 286, 269, 317, 278 | 0.05 / 374 |
| auth B2 | 50 | 49.74 | 0.51 | 2312 | 348, 323, 367, 435, 384 | 0.06 / 394 |
| auth B2 | 60 | 51.01 | 14.98 | fail | 446, 447, 474, 485, 460 | 0.06 / 401 |
| auth B2 | 70 | 34.18 | 51.17 | fail | 500, 500, 434, 500, 464 | 0.07 / 419 |
| shipping B1 | 5 | 5.00 | 0.00 | 921 | 30 | 0.01 / 182 |
| shipping B1 | 10 | 10.00 | 0.00 | 918 | 54 | 0.02 / 215 |
| shipping B1 | 15 | 15.00 | 0.00 | 921 | 89 | 0.02 / 225 |
| shipping B1 | 20 | 20.00 | 0.00 | 915 | 128 | 0.03 / 230 |
| shipping B1 | 25 | 25.00 | 0.00 | 918 | 142 | 0.03 / 234 |
| shipping B1 | 30 | 30.00 | 0.00 | 921 | 203 | 0.04 / 238 |
| shipping B1 | 40 | 40.00 | 0.00 | 919 | 256 | 0.05 / 240 |
| shipping B1 | 50 | 50.00 | 0.00 | 930 | 370 | 0.06 / 436 |
| shipping B1 | 60 | 0.00 | 100.00 | fail | 500 | 0.05 / 472 |
| shipping B1 | 70 | 0.07 | 99.90 | fail | 444 | 0.05 / 496 |
| shipping B1 | 80 | 0.00 | 100.00 | fail | 500 | 0.06 / 511 |
| shipping B1 | 90 | 0.00 | 100.00 | fail | 500 | 0.07 / 515 |
| shipping B1 | 100 | 0.00 | 100.00 | fail | 500 | 0.07 / 526 |
| shipping B2 | 40 | 40.00 | 0.00 | 916 | 55, 60, 57, 52, 56 | 0.06 / 538 |
| shipping B2 | 60 | 60.00 | 0.00 | 917 | 90, 94, 82, 80, 78 | 0.08 / 594 |
| shipping B2 | 80 | 80.00 | 0.00 | 918 | 112, 115, 120, 113, 109 | 0.10 / 646 |
| shipping B2 | 100 | 100.00 | 0.00 | 916 | 141, 149, 137, 130, 140 | 0.12 / 655 |
| shipping B2 | 120 | 120.00 | 0.00 | 917 | 157, 181, 166, 152, 166 | 0.14 / 664 |
| shipping B2 | 140 | 140.00 | 0.00 | 918 | 187, 171, 193, 188, 195 | 0.16 / 674 |
| shipping B2 | 200 | 155.52 | 22.24 | fail | 306, 306, 249, 288, 475 | 0.23 / 1472 |
| shipping B2 | 250 | 0.00 | 100.00 | fail | 500, 500, 480, 477, 447 | 0.37 / 1762 |
| shipping B2 | 300 | 42.91 | 85.70 | fail | 459, 437, 478, 241, 478 | 0.23 / 1804 |
| shipping B2 | 350 | 0.00 | 100.00 | fail | 479, 438, 482, 477, 481 | 0.57 / 1830 |
| shipping B2 | 400 | 36.98 | 90.76 | fail | 479, 323, 221, 487, 481 | 0.27 / 1888 |

Steady part of each 2 min step (first 30 s skipped); failures count as infinite latency ("fail" = p95 inside the
failures). Results: auth C = 10, B2 healthy ceiling 40; shipping C = 50 with a cliff (60 req/s → 100% failures,
server-side: request timeouts plus TCP dial timeouts/refusals while k6 used ≤ 0.07 cores), B2 healthy at 140, one pod
tipped into sticky collapse at 200. A pod left collapsed by the previous ladder was idle for ~4.5 min before the next
ladder started, so the 120 s reset drains backlog.

## 6. Before switching the campaign to open loop

1. **Shipping H3/K1 metric blindness (§4.1).** In open-loop spike (and very likely oscillating) runs, shipping H3/K1
   will be total failures for a reason that is about *where the metric is measured*, not about HPA vs KEDA. That is a
   publishable observation, but it reframes the thesis toward overload robustness, and the engine comparison (H3 vs K1)
   becomes uninformative on shipping. Changing the metric source would change the autoscaler configuration, which this
   pilot was not allowed to do.
2. **Auth `setup()` warm-up scaling (§4.3).** Fix before any new campaign (open or closed) — e.g. run the token
   pre-authentication before STABILIZE_WAIT, or lengthen the warm-up beyond H2's scale-down window — or disclose it.
3. **Variance.** Rep differences reached 58% (shipping H2). The campaign's 5 reps are the minimum; n = 2 here supports
   direction, not effect sizes. Only spike was piloted; gradual and oscillating are untested in open loop.

Cost of a full open-loop 180-run campaign at the pilot's measured 1202 s/run: ≈ 60.1 h ≈ $31.0 of AKS (estimate).
A cheaper option is to keep the closed-loop dataset as primary and report this pilot (optionally extended to 5 reps
of spike) as an open-loop robustness study.

## 7. Contradictions with `thesis_blueprint.md` and with the task brief

- **Blueprint §1 (line 54), "`BASE_VUS=1` delivers ≈6 req/s":** the final closed-loop data shows 11.6–15.9 req/s in the
  auth base phase (5 reps each of B1 12.1–14.4, B2 15.1–15.9, H3 11.6–15.8; spike runs, k6 progress lines 0:30–1:55).
  (Corrected 2026-10-06: an earlier version of this report said 12.1–15.9, omitting the H3 minimum.)
- **Blueprint finding #16 and "Why `ramping-vus`":** they attribute open-loop failures to the executor (dropped
  iterations, "k6's queuing behavior"). With a correctly sized generator there were 0 dropped iterations, k6 stayed
  below 0.13 cores and never ran out of VUs, and the failures were server-side. Open loop still produced large failures
  for autoscaled configs (7.45–32.01% on auth H2/H3/K1 and shipping H2; 97.99–99.30% on shipping H3/K1).
- **Blueprint findings #13–#14 (auth control within ~3% of B2):** true for the closed-loop data; under open-loop spike
  the auth autoscalers fail 7.45–19.70% of load-window requests while B2 fails 0%.
- **Task brief throughput figures:** closed-loop spike peak throughput (3–8 min, 5 reps) is shipping B1 25.2–25.4 req/s
  (brief: ≈48), auth B1 12.0–12.9 (brief: ≈16), auth B2 44.6–46.7 (brief: ≈51); shipping B2 112.4–112.7 matches ≈114.
- **Task brief premise "base below the H3/K1 threshold → every autoscaler starts at 1 replica":** H2's CPU target is the
  binding constraint for auth (base 4 would scale H2), and auth H2 still started at 2–3 replicas because of `setup()`.

## 8. Per-run results

Load window = k6 t 120–540 s. "fail" = the percentile falls inside the failed requests (failures > 5% / > 1%).

| Run | Plan pos. | Offered req/s | Attempted req/s | Goodput req/s | Dropped | Error % | Timeout % | p95 ms | p99 ms | p95 ok-only ms | SLO-viol. s | Onset → 1st scale-up s | Onset → 1st new Ready s | Ready at onset | Max Ready | Per-pod rate share (min) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| auth B1 r1 | 4 | 29.67 | 29.67 | 4.10 | 0 | 86.18 | 86.18 | fail | fail | 4967 | 410 | n/a | n/a | 1 | 1 | n/a (<2 pods Ready ≥60 s) |
| auth B1 r2 | 16 | 29.67 | 29.67 | 4.30 | 0 | 85.50 | 85.50 | fail | fail | 4970 | 410 | n/a | n/a | 1 | 1 | n/a (<2 pods Ready ≥60 s) |
| auth B2 r1 | 8 | 29.67 | 29.67 | 29.67 | 0 | 0.00 | 0.00 | 887 | 1927 | 887 | 20 | n/a | n/a | 5 | 5 | 0.96 |
| auth B2 r2 | 18 | 29.67 | 29.67 | 29.67 | 0 | 0.00 | 0.00 | 843 | 1857 | 843 | 10 | n/a | n/a | 5 | 5 | 0.96 |
| auth H2 r1 | 9 | 29.67 | 29.67 | 25.58 | 0 | 13.79 | 13.76 | fail | fail | 2456 | 140 | 66 | 83 | 2 | 5 | 0.74 |
| auth H2 r2 | 12 | 29.67 | 29.67 | 23.82 | 0 | 19.70 | 19.70 | fail | fail | 4429 | 170 | 51 | 69 | 3 | 5 | 0.97 |
| auth H3 r1 | 3 | 29.67 | 29.67 | 26.59 | 0 | 10.36 | 10.36 | fail | fail | 1263 | 90 | 36 | 55 | 1 | 5 | 0.98 |
| auth H3 r2 | 19 | 29.67 | 29.67 | 27.46 | 0 | 7.45 | 7.45 | fail | fail | 1356 | 60 | 21 | 38 | 1 | 5 | 0.97 |
| auth K1 r1 | 6 | 29.67 | 29.67 | 27.21 | 0 | 8.28 | 8.28 | fail | fail | 1441 | 70 | 23 | 42 | 1 | 5 | 0.98 |
| auth K1 r2 | 17 | 29.67 | 29.67 | 26.72 | 0 | 9.94 | 9.94 | fail | fail | 1763 | 90 | 39 | 57 | 1 | 5 | 0.98 |
| shipping B1 r1 | 10 | 103.87 | 103.85 | 0.91 | 0 | 99.13 | 98.59 | fail | fail | 4676 | 410 | n/a | n/a | 1 | 1 | n/a (<2 pods Ready ≥60 s) |
| shipping B1 r2 | 13 | 103.87 | 103.86 | 0.89 | 0 | 99.15 | 98.62 | fail | fail | 4514 | 410 | n/a | n/a | 1 | 1 | n/a (<2 pods Ready ≥60 s) |
| shipping B2 r1 | 7 | 103.87 | 103.85 | 103.85 | 0 | 0.00 | 0.00 | 919 | 934 | 919 | 0 | n/a | n/a | 5 | 5 | 0.97 |
| shipping B2 r2 | 14 | 103.87 | 103.86 | 103.86 | 0 | 0.00 | 0.00 | 917 | 934 | 917 | 0 | n/a | n/a | 5 | 5 | 0.97 |
| shipping H2 r1 | 5 | 103.87 | 103.86 | 78.26 | 0 | 24.65 | 24.65 | fail | fail | 921 | 170 | 64 | 82 | 1 | 5 | 0.92 |
| shipping H2 r2 | 15 | 103.87 | 103.86 | 70.62 | 0 | 32.01 | 32.01 | fail | fail | 930 | 310 | 49 | 66 | 1 | 5 | 0.91 |
| shipping H3 r1 | 2 | 103.87 | 103.86 | 0.72 | 0 | 99.30 | 98.74 | fail | fail | 4676 | 410 | n/a | n/a | 1 | 1 | n/a (<2 pods Ready ≥60 s) |
| shipping H3 r2 | 20 | 103.87 | 103.86 | 0.99 | 0 | 99.05 | 98.52 | fail | fail | 4713 | 410 | n/a | n/a | 1 | 1 | n/a (<2 pods Ready ≥60 s) |
| shipping K1 r1 | 1 | 103.87 | 103.86 | 2.09 | 0 | 97.99 | 96.97 | fail | fail | 4615 | 410 | 19 | 36 | 1 | 2 | n/a (<2 pods Ready ≥60 s) |
| shipping K1 r2 | 11 | 103.87 | 103.87 | 0.90 | 0 | 99.14 | 98.60 | fail | fail | 4508 | 410 | n/a | n/a | 1 | 1 | n/a (<2 pods Ready ≥60 s) |

### Per-config summary vs closed loop

The closed-loop column is the whole-run k6 p95 (5-rep mean, final 180-run dataset); the open-loop metrics are windowed
and count failures as infinitely slow, so compare the spread between configs, not absolute values.

| Service | Config | Error % (mean of 2) | SLO-viol. s (mean of 2) | Onset → scale-up s (r1 / r2) | Open-loop window p95 ms (r1 / r2) | Closed-loop spike p95 ms (5-rep mean) |
|---|---|---|---|---|---|---|
| auth-service | B1 | 85.84 | 410 | n/a / n/a | fail / fail | 4560.0 |
| auth-service | B2 | 0.00 | 15 | n/a / n/a | 887 / 843 | 1452.0 |
| auth-service | H2 | 16.75 | 155 | 66 / 51 | fail / fail | 1486.0 |
| auth-service | H3 | 8.90 | 75 | 36 / 21 | fail / fail | 1462.0 |
| auth-service | K1 | 9.11 | 80 | 23 / 39 | fail / fail | 1476.0 |
| shipping-rate-service | B1 | 99.14 | 410 | n/a / n/a | fail / fail | 3324.0 |
| shipping-rate-service | B2 | 0.00 | 0 | n/a / n/a | 919 / 917 | 917.0 |
| shipping-rate-service | H2 | 28.33 | 240 | 64 / 49 | fail / fail | 992.9 |
| shipping-rate-service | H3 | 99.18 | 410 | n/a / n/a | fail / fail | 987.3 |
| shipping-rate-service | K1 | 98.56 | 410 | 19 / n/a | fail / fail | 940.7 |

## 9. Limitations

- n = 2 per cell; spike only. Rep-agreement and spread results are indicative.
- k6 arrival-rate executors space arrivals evenly; real traffic is burstier (Poisson or worse).
- The window p95 is censored for every autoscaled run (> 5% failures), so SLO-violation seconds and error % carry the
  comparison.
- Open-loop and closed-loop latency metrics differ (windowed, connect-inclusive, failures = ∞ vs whole-run
  `http_req_duration`); only between-config spreads are compared.
- Auth H2 is confounded by the `setup()` warm-up scale-up (§4.3) in both datasets.
- Run order was shuffled within each rep block; plan positions are in §8.

## 10. Cost and provenance

- Pilot: 20 runs, 24 041 s of run time (6 h 41 m, 1172–1277 s per run) ≈ $3.45 of AKS. AKS was up ≈ 10.4 h in total
  for this work (idle start, 6 ladders, pilot) ≈ $5.4 (estimate from node age). The VM stopped AKS at 01:42 UTC after
  confirming 20/20 runs DONE.
- Code (uncommitted): `infrastructure/kubernetes/load-testing/k6-openloop-pilot.yaml`, `scripts/run-pilot-openloop.sh`,
  `scripts/pilot_openloop.py`, additions to `scripts/run-experiment-helper.js`, sourcing guard in
  `scripts/run-experiment.sh`. The VM's copy was md5-verified against the laptop's.
- Data: `experiment-results-pilot-openloop/` — `pilot-config.env`, `runlist.txt`, `.pilot-plan`, `.pilot-state`,
  20 run directories (raw `k6-results.json.gz`, `k6-output.log`, `pod-timeline.jsonl`, `hpa-timeline.jsonl`,
  `k8s-events.txt`, `prom_*.json`, `metadata.json`), `calibration/` (6 ladders), `analysis/` (summary, tables, ladder),
  `pilot-vm.log`, `pilot-console-vm.log`, `run-pilot-vm.sh`.
