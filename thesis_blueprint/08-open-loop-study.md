# Thesis Blueprint — Part 08: Open-Loop Load-Generator Study

> Part of the thesis blueprint — index and executive summary: [thesis_blueprint.md](../thesis_blueprint.md).
> New part, written 2026-10-06. Covers everything from the open-loop pilot request (2026-10-05) to the 180-run
> open-loop campaign (running since 2026-10-06 12:33 UTC). Detailed pilot write-up: `pilot-openloop-report.md` (repo root; every result in it is
> reproduced here). All numbers below were computed from the stored data;
> estimates are labelled as estimates. Times are UTC unless marked otherwise.

---

## 8.0 Status at a glance (2026-10-06, 17:40 UTC)

| Stage | Status | Outcome |
|---|---|---|
| Pilot v1 (20 runs, spike, both services) | ✅ Done 2026-10-05 18:57 → 2026-10-06 01:39 | Pre-registered rule: **GO**, but only via the criterion-4 explanation clause; strict reading → STAY (§8.7) |
| User decision | ✅ 2026-10-06 | "Switch to the full 180-run open-loop campaign **only if it is robust already**" (§8.8); after the smoke: run the campaign under G6 rule v2 (§8.12), thesis structure "Replace" (§8.14), H1 = 80% (§8.13) |
| v2 fixes (admission control, auth pre-auth, robustness gate) | ✅ Implemented, unit-tested, deployed via ConfigMap overlay | §8.9–§8.10 |
| v2 calibration ladders | ✅ Done 2026-10-06 06:44–08:28 | Collapse removed up to the planned peaks (§8.11) |
| v2 smoke test (9 runs) | ✅ Done 08:31–11:31; AKS stopped 11:35 | **Pre-registered gate FAIL on one cell:** shipping H3 error rate 5.32 / 6.97% across reps (27% of mean; limit 25% or 1 point), caused by a first scale-up one 15 s HPA cycle later. Everything else passes: 9/9 runs clean, B1 hold graceful, SLO-violation seconds 70/70, 70/70, 100/100 (shipping) and 140/170 (auth) (§8.12) |
| 180-run open-loop campaign | ⏳ Rep blocks 1–2 (72 runs) running on `ecommerce-vm` since 12:33:42 UTC under G6 rule v2 (§8.9); **12/72 DONE at 17:36 UTC**; H1 = 80% from position 13 (confirmed live 16:44), positions 1 and 9 re-run at 80% after position 72 | Pre-launch check: VM and cluster match the pushed HEAD (one inert adapter leftover); no failure since the start-up hiccup; the VM stops AKS after the re-runs (≈13:30 UTC 2026-10-07, estimate), then the gate decides (§8.13). Thesis structure: "Replace" (§8.14) |

**"Replace" (§8.14):** if the campaign passes its gate it is the thesis dataset; the closed-loop final dataset (Part 01,
findings #13–#16) then becomes methodology background. If the campaign fails, the closed-loop dataset is the thesis
dataset.

---

## 8.1 Why the study was done

- **June 2026:** auth was moved from open-loop `ramping-arrival-rate` (10→40 RPS) to closed-loop `ramping-vus`
  because open loop dropped iterations under saturation (VU pool 400 → max 1000, k6 default 60 s timeout), so
  delivered load depended on the configuration; B1 sat at the 60 s timeout with 52% errors; and reps were bimodal
  (K1 spike: one rep at 52% failures, four at 1–3%).
- **That evidence predates three generator/measurement fixes:** connection pinning (`noConnectionReuse`, finding #12),
  the auth-only 30 s rate window (reverted to 1 m, commit `cf466b4`), and `setup()` injecting 120 failures per run
  (commit `a39b1f2`). The open-loop failures therefore could not be attributed to the executor alone.
- **The drops were guaranteed by the old configuration:** at 40 req/s with responses reaching 60 s, in-flight
  requests reach 2,400 — above the 1,000 max VUs. With a 5 s timeout only ~200 VUs are needed.
- **Closed loop throttles itself.** Measured on the final dataset (spike, 3–8 min window, 5 reps, k6 progress lines):

| Service | B1 peak throughput | B2 peak throughput |
|---|---|---|
| shipping-rate-service (80 VUs) | 25.2–25.4 req/s | 112.4–112.7 req/s |
| auth-service (12 VUs) | 12.0–12.9 req/s | 44.6–46.7 req/s |

  A slow autoscaler is therefore penalised less in closed loop (its pods simply receive less load), which may explain
  why the final closed-loop results are nearly all ties (H2 ≈ H3 ≈ K1 within a few percent).
- **Goal:** decide with data whether a correctly sized open-loop generator is stable now, changing only the load
  generator (autoscaler configs exactly as in the final campaign), and give a go/no-go on switching the experiment.

## 8.2 Constraints and pre-set decision criteria (pilot v1)

- Only the generator changes; autoscaler manifests (thresholds, behaviour, windows) untouched; existing datasets
  (`experiment-results/`, `experiment-results-archive/`) and closed-loop k6 jobs/runner modes unchanged (new files or
  opt-in flags only); pilot output in its own directory with its own state file; every cost- or cluster-changing step
  approved by the user first; no commits unless asked.
  *(For the campaign the user later changed one autoscaler setting: H1's CPU target to the Kubernetes default 80%,
  2026-10-06 — §8.13. The pilot and smoke had no H1 runs.)*
- **Decision criteria (fixed before data):**
  1. `dropped_iterations = 0` in all 20 runs.
  2. B2: error < 1% and window p95 ≤ SLO.
  3. B1 clearly overloaded — operationalised before the data as: in every B1 rep, SLO-violation ≥ 210 s (half the
     420 s load window) **or** error ≥ max B2 error + 5 points.
  4. Reps agree: per autoscaled config, SLO-violation seconds and window p95 within ±25% (|a−b| / mean ≤ 0.25), or
     the disagreement is explained by autoscaler poll phase visible in the events/replica timelines.
  5. The per-pod distribution check passes in all autoscaled runs.
  - **Rule:** GO if 1, 2, 3 and 5 pass and 4 passes or is explained; otherwise STAY. Also report whether the
    H2/H3/K1 spread is larger than in the closed-loop data (indicative only at n = 2).
- **Metric definitions (fixed in `scripts/pilot_openloop.py` before any pilot data):** latency = client wall-clock per
  request **including the TCP connect** (`req_e2e_duration`; with `noConnectionReuse` every request connects afresh
  and `http_req_duration` leaves the connect out); requests binned by **start** time; **failed requests count as
  infinitely slow** in every p95/p99/SLO statistic; load window = k6 t ∈ [120 s, 540 s) (excludes the 2 m warm-up and
  3 m ramp-down); spike onset = k6 t = 120 s; SLO-violation seconds = 10 s bins in the load window with p95 > SLO;
  per-pod check = during the peak, a pod Ready ≥ 60 s whose mean share of the per-pod request rate or CPU is < 20% of
  the mean of such pods (the check that would have caught connection pinning).

## 8.3 Environment and operational decisions

| Date | Decision | Reason |
|---|---|---|
| 2026-10-05 | Work from the Windows laptop (Git Bash, `az` signed in, `kubectl` context `ecommerce-aks`) | The final campaign host (`ecommerce-vm`, `/home/kevin/e-commerce-vus`) had no laptop SSH access at the time |
| 2026-10-05 | AKS was found **running** (nodes up ~55 min, idle); user: **leave it running** | So calibration could start as soon as the code was ready |
| 2026-10-05 | **Pin k6 to `grafana/k6:0.46.0` for both services** | Closed-loop auth jobs use unpinned `:latest`, shipping uses 0.46.0; one known version, recorded in metadata |
| 2026-10-05 | Ladders run from the laptop; long runs from a terminal tab, then (user) **from the VM so the PC can be switched off** | Laptop sleep/network risk for multi-hour runs |
| 2026-10-05 | Pilot code deployed to the VM via `az vm run-command` (base64 tarball, md5-verified) | Laptop key was not authorised on the VM |
| 2026-10-05 | When the pilot finished: **stop AKS only, and only after all runs are DONE**; VM stays up | User instruction |
| 2026-10-06 | **Laptop SSH key (`id_ed25519`) added to VM user `kevin`** via `az vm user update` (user-approved) | To copy the 99 MB results to the laptop (run-command returns ≤ ~4 KB) |
| 2026-10-06 | v2: smoke test runs on the VM; AKS stopped when it finishes **or** gives up (4 attempts without progress) | Nobody watching; avoid idle billing |

The VM's system-assigned managed identity is **Contributor on the subscription** (plus AKS cluster-admin roles), which
is what lets the VM stop AKS itself. `ecommerce-vm` = Standard_B2ats_v2, 842 MB RAM, Python 3 without numpy (analysis
runs on the laptop with `tools/python312`).

## 8.4 Tooling built

| File | Purpose |
|---|---|
| `infrastructure/kubernetes/load-testing/k6-openloop-pilot.yaml` | Shared stage-shape module + one open-loop script per service. `PATTERN` = gradual / spike / oscillating (`ramping-arrival-rate`, same shapes as closed loop: spike = 2 m base → 10 s jump → 6 m 50 s peak → 3 m ramp-down) or `ladder` (`constant-arrival-rate` steps). Same request mix (auth 70% `/auth/me` + 30% `/auth/login`), login-first `setup()`, shipping payload generator and `noConnectionReuse: true` as closed loop. `REQUEST_TIMEOUT` (default 5 s). preAllocatedVUs = maxVUs = ⌈1.5 × rate × timeout⌉. **No thresholds** (cannot abort). Trimmed system tags. `req_e2e_duration` Trend. One `SCENARIO_START` log line with the scenario's wall-clock start. Suspended Job templates (auth, shipping, auth pre-auth); a wrapper keeps the k6 container alive after k6 exits until the runner has fetched the gzipped per-request JSON |
| `scripts/run-pilot-openloop.sh` | `run [--resume] [--dry-run] [--max-runs N]` and `ladder --service S --config b1\|b2 --rates "…" [--step] [--gap] [--max-inflight N]`. Sources `run-experiment.sh` for reset/apply/readiness. Explicit run list; own results dir and state file (`OPENLOOP_RESULTS_DIR` selects the campaign dir); run order shuffled within each rep block with a seeded PRNG and **frozen** in `.pilot-plan` (+ fingerprint of run list + config; changing either after the freeze aborts). Resets **both** core services each run (runs of the two services are interleaved). 5 s pod/HPA watcher (`pod-timeline.jsonl`, `hpa-timeline.jsonl`). Raw-data fetch verified by md5 + `gzip -t`. Extra Prometheus exports. A run is DONE only if raw data verified, k6 exit 0, required exports non-empty (and, v2, pre-auth tokens used) |
| `scripts/pilot_openloop.py` | `ladder`, `validate`, `report`, `gate` (v2). Parses the raw JSON (cached as `.npz`), computes window statistics, SLO bins, scaling timelines, per-pod distribution, k6 resource use, closed-loop references, criteria/gate verdicts |
| `scripts/run-experiment-helper.js` | New subcommands only: `clone-job-env`, `pod-snapshot`, `hpa-snapshot`, `shuffle-plan`, `render-deployment`, `configmap-from-file(s)` |
| `scripts/run-experiment.sh` | Only a `BASH_SOURCE` guard around `main "$@"` so it can be sourced; behaviour unchanged when executed |
| `experiment-results-pilot-openloop/` | Pilot v1: `pilot-config.env`, `runlist.txt` (20 runs), `.pilot-plan`, `.pilot-state`, 20 run dirs, `calibration/` (6 ladders), `analysis/`, `pilot-vm.log`, `pilot-console-vm.log`, `run-pilot-vm.sh` |
| `experiment-results-openloop/` | v2 campaign: config (v2 knobs), `runlist.txt` (180 runs, seed 20261006), `calibration/` (v2 ladders) |
| `experiment-results-openloop-smoke/` | v2 smoke: config (filled), `runlist.txt` (9 runs, seed 20261007) |
| `backend/services/{auth-service,shipping-rate-service}/internal/middleware/admission_control.py` + `tests/test_admission_control.py`; `app/main.py` registration | v2 admission control (§8.10) |

**Bug fixed along the way:** every run of the final closed-loop campaign logged "Could not copy k6 JSON results"
(411 occurrences in `experiment-results/experiment.log` across campaigns) because the runner `kubectl cp`'d
`/results/results.json` after the k6 pod had terminated. The open-loop wrapper keeps the container alive until the
gzipped file has been copied and verified, so raw per-request data now lands on disk for every run (ladders
1.5–28 MB, pilot runs 2.6–9.0 MB).

**Phase 0 observations (2026-10-05):** the brief's closed-loop throughput figures were off (shipping B1 25.2–25.4
req/s, not ≈48; auth B1 12.0–12.9, not ≈16; auth B2 44.6–46.7, not ≈51; shipping B2 112.4–112.7 matches ≈114);
Part 01 line "BASE_VUS=1 ≈ 6 req/s" contradicts the data (11.6–15.9 req/s, see the correction there); the Prometheus
export had no per-pod request rate (added); connect time is outside `http_req_duration` (hence `req_e2e_duration`).

## 8.5 Calibration ladders v1 (2026-10-05, 16:18–18:37)

2 min steps, 30 s gaps, 5 s timeout, steady part of each step (first 30 s skipped); failures count as infinite latency
("fail" = the percentile lies inside the failures).

| Ladder | Rate (req/s) → p95 (ms) / error % | Pod CPU |
|---|---|---|
| auth B1 | 2 → 477 / 0 · 4 → 518 / 0 · 6 → 534 / 0 · 8 → 783 / 0 · **10 → 1250 / 0** · 12 → fail / 21.20 · 14 → fail / 41.11 · 16 → fail / 69.31 | 80 · 119 · 223 · 265 · 373 · 494 · 500 · 459 m |
| auth B2 | 20 → 545 / 0 · 30 → 853 / 0 · **40 → 1156 / 0.03** · 50 → 2312 / 0.51 · 60 → fail / 14.98 · 70 → fail / 51.17 | 121–150 m per pod at 20 → ≈500 m at 70 |
| shipping B1 | 5 … 40 → 915–921 / 0 · **50 → 930 / 0** · 60 → fail / 100 · 70 → fail / 99.90 · 80, 90, 100 → fail / 100 | 30 m at 5 → 256 m at 40, 370 m at 50; 500 m at 60 and 80–100 (444 m at 70) |
| shipping B2 | 40 … 140 → 916–918 / 0 · 200 → fail / 22.24 · 250 → fail / 100 · 300 → fail / 85.70 · 350 → fail / 100 · 400 → fail / 90.76 | 52–60 m per pod at 40 → 171–195 m at 140 |

- **One shipping pod is concurrency-limited, not rate-limited:** closed loop with 80 VUs keeps 80 requests in flight
  on one pod (p95 3.3 s at ~25 req/s); open loop at 40 req/s keeps ≈28 in flight and stays at the latency floor.
  The httpx carrier pool is 80 connections per pod (`max_connections=80`). The collapse at 60 req/s is server-side:
  failures are request timeouts (k6 error 1050) plus TCP dial timeouts/refusals (1211/1212) while k6 used ≤ 0.07
  cores and never exhausted its VUs.
- **Shipping B2 at 200** failed because one pod tipped into a sticky collapse (that pod later showed no request-rate
  series because Prometheus could not scrape it). A pod left collapsed by the previous ladder had been idle for
  ~4.5 min before the next ladder started, so the 120 s reset drains backlog.
- **k6 sizing evidence:** 204 MiB for 525 preallocated VUs (≈0.4 MiB/VU), 631 MiB for 1050, 1752 MiB for 3000; CPU
  ≤ 0.57 cores; VUs are reused across non-overlapping ladder scenarios (header "6 scenarios, 525 max VUs").
- **Derived settings (approved):**

| | C (B1 healthy max) | B2 healthy ceiling | Base | Peak | SLO |
|---|---|---|---|---|---|
| auth | 10 req/s | 40 req/s | **2 req/s** | **30 req/s** (75% of 40; ≥ 2.5 × C = 25) | **1500 ms** (≈ closed-loop B2 spike p95 1452 ms) |
| shipping | 50 req/s | 140 req/s (200 fails) | **10 req/s** | **105 req/s** | **1200 ms** (≈ 1.3 × closed-loop B2 p95 917 ms) |

- **Auth base = 2, not 4:** H2's CPU target, not the H3/K1 threshold, is the binding constraint. At 4 req/s single-pod
  CPU samples reached 147 m (59% of the 250 m request), which would scale H2 during warm-up; at 2 req/s CPU is 78–83 m
  (31–33%) and Prometheus sees 2.13 req/s (< 5 req/s/pod). This contradicts the brief's premise that a base below the
  H3/K1 threshold makes every autoscaler start at 1 replica.
- **Shipping base = 10:** single-pod CPU 54 m (22% of request); 10 req/s vs the 15 req/s/pod threshold.
- **Shipping peak rule conflict:** 75% of the B2 ceiling (140) = 105, but ≥ 2.5 × C = 125. The 2.5 × C rule exists to
  make B1 clearly overloaded, which already holds from 60 req/s (100% failures); 105 also keeps B2 margin over a
  7-minute hold and is close to the ~112 req/s closed-loop B2 actually served at peak. **User: "pick the best path
  for my thesis" → 105 chosen** for those three reasons.

## 8.6 Pilot v1 execution

- Matrix: {auth, shipping} × spike × {B1, B2, H2, H3, K1} × 2 reps = 20 runs (H1 left out to save time), order
  shuffled within each rep block (seed 20261005). Settings: auth 2→30 req/s (225 VUs), shipping 10→105 req/s
  (788 VUs), timeout 5 s, k6 0.46.0, k6 pod 1000 m/1 Gi request, 2000 m/4 Gi limit.
- Ran on `ecommerce-vm` (tmux `pilot`, wrapper `/home/kevin/run-pilot-vm.sh`) 2026-10-05 18:57 → 2026-10-06 01:39;
  20/20 DONE on the first attempt, 1172–1277 s per run (24,041 s total, ≈ $3.45 of AKS); the VM stopped AKS at 01:42.
- **First run (shipping K1) showed the key failure live:** at onset the single pod hit its 500 m limit, failed
  readiness, and `up{job="shipping-rate-service"} = 0`; KEDA read 0/15, scaled 1→2 at +19 s and back to 1 under the
  shared 30 s / 100% scale-down, and stayed at 1 for the whole peak. The pilot was **not** stopped: the failure mode
  is what the pilot exists to detect, and the pre-set criteria capture it.

## 8.7 Pilot v1 results and verdict

Validator: **0 critical, 8 warnings** (all: shipping pods too overloaded to be scraped). k6 never exceeded 0.13 cores,
546 MiB or 527 of its 788 VUs; attempted = offered within 0.02 req/s in every run.

**Per-config results (load window, mean of 2 reps; closed loop = whole-run k6 p95, 5-rep mean):**

| Service | Config | Error % | SLO-violation s | Onset → first scale-up s (r1 / r2) | Closed-loop spike p95 (ms) |
|---|---|---|---|---|---|
| auth | B1 | 85.84 | 410 | – | 4560.0 |
| auth | B2 | 0.00 | 15 | – | 1452.0 |
| auth | H2 | 16.75 | 155 | 66 / 51 | 1486.0 |
| auth | H3 | 8.90 | 75 | 36 / 21 | 1462.0 |
| auth | K1 | 9.11 | 80 | 23 / 39 | 1476.0 |
| shipping | B1 | 99.14 | 410 | – | 3324.0 |
| shipping | B2 | 0.00 | 0 | – | 917.0 |
| shipping | H2 | 28.33 | 240 | 64 / 49 | 992.9 |
| shipping | H3 | 99.18 | 410 | never | 987.3 |
| shipping | K1 | 98.56 | 410 | 19 (then back to 1) / never | 940.7 |

B2 window p95: auth 887 / 843 ms, shipping 919 / 917 ms. Every autoscaled run had > 5% failures in the load window,
so its window p95 lies inside the failures; SLO-violation seconds and error % carry the comparison.

| # | Criterion | Result |
|---|---|---|
| 1 | dropped = 0 | **PASS** (0 in all 20 runs) |
| 2 | B2 healthy | **PASS** (0.00% errors; p95 887/843 vs 1500 and 919/917 vs 1200) |
| 3 | B1 overloaded | **PASS** (auth 86.18/85.50%, shipping 99.13/99.15%; all 410 s violated) |
| 4 | Reps agree | **FAIL on ±25%** — auth H3 90 vs 60 s (40%), shipping H2 170 vs 310 s (58%); auth H2 19%, auth K1 25.0% (boundary), shipping H3/K1 0% (both total failure). **Explained by poll phase:** auth H3's first scale-up 15.0 s apart (one sync), identical 6-bin failure block, 2 extra B2-level tail bins (1516, 1772 ms; B2 itself shows 1671–1965 ms bins); shipping H2's first CPU reading came 14.6 s earlier in r2 at 139% → 1→3 pods (r1: 162% → 1→4), and with one collapsed pod the other two sat at the single-pod cliff, so a second pod collapsed — the trigger is poll phase, the 140 s magnitude is metastable amplification |
| 5 | Per-pod distribution | **PASS** (no pod < 20%; lowest 0.74 = auth H2 r1 warm-up pod `jt5jx`); the 4 shipping H3/K1 runs never had two pods Ready ≥ 60 s |

**Verdict by the pre-set rule: GO** (1, 2, 3, 5 pass; 4 explained). **If criterion 4 is read as requiring the
difference itself to be phase-sized, shipping H2 fails and the verdict is STAY.**

**Spread between H2, H3 and K1 — much larger in open loop (indicative, n = 2):**

| Service | Closed loop: p95 range / B1→B2 gap | Open loop: SLO-violation range / gap | Open loop: error-% range / gap |
|---|---|---|---|
| auth | 0.77% (1462–1486 of 3108 ms) | 20.3% (75–155 of 395 s) | 9.1% (8.90–16.75 of 85.84 points) |
| shipping | 2.17% (940.7–992.9 of 2407 ms) | 41.5% (240–410 of 410 s) | 71.5% (28.33–99.18 of 99.14 points) |

Rankings change: auth — request-rate (H3, K1) beats CPU (H2) in both reps; shipping — CPU (H2) beats request-rate,
because H3/K1 never scale. Closed loop had all three within 1.6% (auth) and 5.5% (shipping), K1 best on shipping.

**Mechanisms found:**
1. **Request-rate metric blindness (shipping H3/K1).** The metric is the pod's own `http_requests_total`, counted when a
   response completes. A collapsed pod completes almost nothing, so the metric fell (H3 r1: 10.1 → 11.1 → 11.5 → 7.7
   req/s/pod, then `FailedGetPodsMetric` from +52 s; K1 r2: 10.1 → 11.6 → 10 → 8.1 → 0) and never crossed the
   15 req/s/pod threshold. H2's CPU comes from the kubelet and survives.
2. **Request-rate reacts faster than CPU when the metric survives (auth):** first scale-up H3 21.5–36.5 s, K1
   23.1–38.7 s, H2 50.7–66.1 s; first new pod Ready 17–19 s after each scale-up in every config. The CPU signal lags:
   shipping H2's HPA reading stayed at its pre-spike 22–25% until its first decisions at +49.3 s / +63.9 s.
3. **Auth `setup()` warm-up confound:** 120 bcrypt logins in ~28 s (e.g. 21:42:32–21:43:00) right before the warm-up;
   H2 read 82% CPU about a minute later and scaled 54 s (r1, 1→2) / 69 s (r2, 1→3) **before** onset, then scaled back
   to 1 as the spike began (r2: 3→1 at +6 s). H3/K1 did not react (setup averages ≈4.3 req/s < 5). **The closed-loop
   campaign has the same `setup()`** (there the 12–16 req/s base load already scales the autoscalers, finding #14's
   validation note) — disclose for auth H1/H2.
4. **Metastable collapse amplifies timing noise** (shipping H2: 15 s → 140 s), readiness fails during collapse, and the
   shipping liveness probe (60 s period, 10 failures) restarted the collapsed pod in 2 of 20 runs (B1 r1, K1 r2,
   ≈9.5 min after onset, during the ramp-down).

## 8.8 Decision after the pilot

- **User (2026-10-06): "My decision is to switch to full 180 run open loop campaign ONLY if it's robust already."**
- **Assessment: not robust yet.** Criterion 4 fails strictly in 2 of 6 cells; a known confound (setup burst) biases
  H2 (and would bias H1 more: 300 s scale-down window); shipping H3/K1 are degenerate (they measure where the metric is
  exported, not HPA vs KEDA). The generator itself is sound — the fragility comes from how the services behave under
  overload.

## 8.9 Issues → root causes → fixes (v2)

| # | Issue | Root cause | Fix | Status |
|---|---|---|---|---|
| 1 | Shipping H3/K1 never scale | No overload protection: one single-worker pod collapses past ~55 req/s; goodput → 0; `/metrics` (same event loop) stops answering; the counter counts completions | **Admission control** in the service: cap in-flight requests per pod, reject the excess immediately with 503; `/metrics`, `/health`, `/ready` exempt | ✅ Approved, implemented |
| 2 | Shipping H2 reps differ by 58% | Collapsed pods stay sick (they keep processing requests the client abandoned) | Same fix: admitted requests finish promptly; recovery ≈ scale-up + 17–19 s pod start | ✅ |
| 3 | Probe instability (readiness flaps; 2 liveness restarts) | Probes share the saturated event loop | Same fix (exempt endpoints stay responsive); no probe changes | ✅ |
| 4 | Auth H2 starts the spike at 2–3 replicas | `setup()` bcrypt burst inside the autoscaled window | **Pre-authenticate** the 120 users during the reset (before RESET_WAIT and before any autoscaler exists); tokens in ConfigMap `k6-openloop-auth-tokens`; k6 `setup()` uses them (JWT lifetime 30 min, `config.yaml`; a run uses them for ≈16 min); run not DONE unless k6 logged `PREAUTH_USED` | ✅ Approved, implemented |
| 5 | K1 and H3 handle a lost metric differently (K1 reads 0 → scales down; H3 holds) | KEDA `ignoreNullValues` defaults to true | `ignoreNullValues: "false"` would make K1 hold like H3 | ⏸ **Kept in reserve** (user): autoscaler manifests stay identical; apply only if metric loss reappears |
| 6 | Gradual, oscillating and H1 untested in open loop | Pilot scope | Covered by the campaign gate | ⏸ |

**Rejected alternatives for issue 1 (and why):** scale on gateway/ingress traffic (changes the request path and the
H3/K1 queries); KEDA HTTP add-on (K1 only — breaks the H3-vs-K1 fairness control); an arrival counter (still not
scrapeable from a collapsed pod); uvicorn `--limit-concurrency` (also rejects probes and scrapes).

**Robustness gate (pre-registered 2026-10-06, before any v2 data; `pilot_openloop.py gate --reps N`):**
- **G1 instrument:** dropped = 0, full schedule, verified raw data, k6 exit 0, attempted = offered within 2% — every run.
- **G2 start state:** every autoscaled run has exactly 1 Ready replica at scenario start and at onset; pre-auth tokens
  used when enabled.
- **G3 observability:** no Ready pod unscrapeable (`up = 0`), no autoscaler metric failure in the load window, no
  container restart during the run.
- **G4 calibration:** per service × pattern, B2 error < 1% and window p95 ≤ SLO in every rep; B1 SLO-violation ≥ 210 s
  or error ≥ B2 max + 5 points.
- **G5 per-pod load:** no pod below 20% of the mean per-pod share.
- **G6 reproducibility:** per autoscaled service × pattern × config, replicate SLO-violation seconds within 25% of the
  mean **or within 20 s** (two 10 s bins), **and** error % within 25% **or within 1 point** — the absolute floors were
  chosen by the user to absorb 10 s binning / 15 s control-loop quantization only. No after-the-fact explanations.

**Implementation corrections (2026-10-06 ≈10:20, after smoke run 5; the criteria themselves are unchanged):**
- **G1 "full schedule"** was implemented as k6's global run clock ≥ 720 s. That clock includes `setup()`, and k6 can
  end the scenario at its last scheduled arrival (auth spike: 716.5 s — the rest of the ramp-down holds less than one
  arrival). In v1 the 120 bcrypt logins (`setup()` ≈26–29 s; v1 auth runs end at 12m22.9s–12m25.2s) hid this;
  pre-authentication exposed it and flagged smoke auth H2 rep1, although k6 reached all 15,399 scheduled arrivals
  (the same count as every v1 auth run), 0 dropped, 0 interrupted, exit code 0. G1 now counts arrivals: complete +
  interrupted + dropped ≥ ⌈A⌉ − 1 for the schedule integral A (k6 never fires the arrival that falls exactly on the
  720 s end: 15,399 of 15,400 auth, 54,274 of 54,275 shipping in every run).
- **Analysis cache** (`analysis/cache/<run_id>.npz`) was keyed by run id and file time only. Run ids repeat across the
  result folders, and analysing smoke runs 1–2 at 09:18 overwrote the v1 cache of shipping H3/K1 rep1 with smoke data.
  The cache is now tied to the raw file's md5. Impact: none on reported numbers — re-analysing all 20 v1 runs from
  raw data reproduces `gate.json` (now `gate-v1.json`; written 08:52, before the overwrite) with 0 differences; `summary.json` /
  `tables.md` (05:18) and `pilot-openloop-report.md` (09:16) also predate it.

**G6 rule v2 (chosen by the user 2026-10-06 ≈12:00 UTC — after the smoke, before any campaign data):** replicate
SLO-violation seconds and error % each agree when the gap is **≤ 50% of the mean, or ≤ 30 s / ≤ 2 points**. G1–G5 are
unchanged. Reasons:
- The gap between two reps is dominated by the autoscaler's 15 s loop: in 6 of the 8 rep pairs measured (pilot +
  smoke) the first scale-up came 14.6–15.8 s apart.
- In the fixed system one such cycle produced gaps of up to 27% of the mean (shipping H3 errors), 30 s (auth H2
  SLO-violation) and 1.93 points (auth H2 errors). Rule v1 (25% / 20 s / 1 point) sat at or below that noise; its
  1-point allowance was set without checking what one cycle costs (≈1.5 points on shipping: 42.9 req/s × 15 s of
  43,625 window requests).
- Oscillating peaks are 180 s = 12 cycles apart, so a rep that is late at the first peak is expected to be late at all
  three: absolute gaps can triple, relative ones should not (expectation, not yet measured).
- The defects behind the pilot's divergence are now checked directly: start state (G2), scrape/metric loss and
  restarts (G3).
- Checked on labelled data: rule v2's G6 still rejects pilot v1 (shipping H2 sticky collapse, SLO-violation 170 / 310 s
  = 58%) and passes the smoke; rule v1 rejects both. Accepted trade-off: divergence between 25% and 50% from an
  unknown cause no longer stops the campaign; it shows up as spread in the 5-rep results.
- The smoke stays FAIL on record (`experiment-results-openloop-smoke/analysis/gate-v1.json`); rule v2 is judged only on
  campaign data. `pilot_openloop.py gate --rule v1|v2` (default v2) writes `analysis/gate-<rule>.json`; the pilot's
  original `gate.json` was renamed `gate-v1.json`.
- Run on the v1 pilot data, the gate **fails** on exactly the known problems (G2 auth H2; G3 shipping H3 metric failures
  and the two liveness restarts; G6 the rep disagreements) — evidence it detects these failures.

## 8.10 v2 implementation details

- **Admission control (`internal/middleware/admission_control.py`, identical in both services):** pure ASGI; off unless
  `MAX_INFLIGHT_REQUESTS` > 0 (closed-loop behaviour unchanged); counters `http_requests_shed_total` and gauge
  `http_requests_inflight`; 4 unit tests per service (disabled passes everything; excess gets 503 while capped requests
  wait; probes and `/metrics` bypass a full pod; in-flight released when the handler raises).
- **Placement matters — it must be the OUTERMOST middleware (added last).** First attempt (inside the instrumentation,
  so shed requests would be counted): shipping B1 still collapsed at 105 req/s (goodput 7.50, 77.16% timeouts, only
  15.69% shed) because each rejection still passed the `@app.middleware("http")` gateway check (BaseHTTPMiddleware)
  and the instrumentation, and above ≈80 req/s rejecting alone used the pod's 500 m. Outermost: rejections are almost
  free and `http_requests_total` keeps counting **served** requests — the same signal H3/K1 used in the closed-loop
  campaign; shed requests are counted separately.
- **Code delivery — ConfigMap overlay (user-approved after `az acr build` failed):** ACR Tasks are **not available in
  Indonesia Central** (registry `ecommerce`, Basic SKU; Azure returns "No registered resource provider found for
  location 'indonesiacentral' … registries/listBuildSourceUploadUrl"). Options considered: overlay (chosen), a
  temporary ACR in a supported region + `az acr import`, or Docker on the VM. The overlay keeps the **same `:latest`
  images** as the closed-loop campaign and mounts only `app/main.py` + `admission_control.py` (+ an empty
  `internal/middleware/__init__.py` for shipping, whose image has no such package) from ConfigMap
  `openloop-overlay-<service>`, built from the repo files at run time; its content hash goes into the pod env
  (`OPENLOOP_OVERLAY_SHA`) so changed code forces a rollout and is recorded in metadata. Verified 2026-10-06: every
  `app/` + `internal/` `.py` file in both running images equals repo HEAD (auth 17/17, shipping 10/10); both run
  Python 3.11.15, fastapi 0.109.0, starlette 0.35.1, uvicorn 0.27.0, prometheus-fastapi-instrumentator 6.1.0 — so no
  dependency drift (a rebuild would re-run `pip install` with unpinned transitive dependencies).
- **Runner v2 knobs** (`pilot-config.env`): `LOAD_PROFILE_VERSION=open-loop-arr-v2`, `CODE_OVERLAY`,
  `SERVICE_IMAGE_TAG` (empty = manifest image), `MAX_INFLIGHT_AUTH/_SHIPPING`, `PREAUTH_AUTH_TOKENS`; B1/B2
  Deployments are rendered from the experiment's own manifests with only the overlay mounts and env vars added (v1
  settings render byte-identical manifests); new exports `prom_up.json` (scrape health), `prom_shed_rate.json`,
  `prom_inflight.json` (optional series); metadata records `service_overrides` (image tag, cap, overlay hash) and
  `preauth_tokens`. Runner hardened: ends with `pilot_main "$@"; exit $?` so editing the file during a multi-hour run
  cannot inject commands.
- **Validator fix (2026-10-06):** a pod's last scrape during a scale-down termination was counted as "unscrapeable while
  Ready" (watcher snapshots every 5 s had not yet seen the deletion); a sample now counts only if the pod is still
  seen after it and not deleted within the next 15 s.

## 8.11 v2 calibration ladders (2026-10-06, caps on)

| Ladder (cap) | Rate (req/s) → goodput / shed % / timeouts % / admitted p95 (ms) | Notes |
|---|---|---|
| shipping B1 (48, **inner placement**) | 40 → 40.00 / 0 / 0 / 917 · 50 → 50.00 / 0 / 0 / 929 · 60 → 41.87 / 30.22 / 0 / 1375 · 80 → 40.91 / 48.86 / 0 / 1443 · **105 → 7.50 / 15.69 / 77.16 / 4918** · 140 → 0 / 0 / 100 | Collapse at the planned peak → placement changed |
| shipping B1 (48, **outermost**) | 50 → 49.58 / 0.84 / 0 / 983 (p95 1000) · 60 → 44.43 / 25.94 / 0 / 1264 · 80 → 43.34 / 45.82 / 0 / 1315 · **105 → 42.36 / 59.66 / 0 / 1364** · 140 → 0 / 2.27 / 97.73 · 180 → 0 / 0 / 100 | Scrape failures 0 up to 105; 3 at 140, 6 at 180. One pod still collapses between 105 and 140 (single-worker accept/parse limit) |
| auth B1 (22) | 6 → 6.00 / 0 / 0 (p95 653) · 8 → 8.00 / 0 / 0 (1225) · 10 → 9.61 / 0.44 / 3.44 (3689) · 12 → 11.31 / 3.98 / 1.76 · 16 → 10.64 / 25.42 / 8.06 · 30 → 10.17 / 60.33 / 5.78 | Pre-auth used (120 tokens); 0 scrape failures; goodput holds at 10–11 (v1: 4.1 at 30) |
| shipping B2 (48) | 120 → 0% errors (p95 918) · 160 → 1.26% (0.93 shed, 0.33 timeouts; p95 925) · **200 → 0.09% (p95 932)** · 250 → 15.19% (14.77 shed; goodput 212.03) | 160's errors were one 20 s transient (182 failures at 30–50 s into the step, none before/after, no probe events) — the pod recovered at once |
| auth B2 (22) | **30 → 0% (p95 787)** · 40 → 0.64% (p95 1765) · 50 → 2.47% · 60 → 7.09% · 70 → 15.33% | No collapse; 0 scrape failures |

- **Caps:** auth 22, shipping 48 — derived before testing with the rule ⌈C × p99(C)⌉ from the v1 ladders
  (10 req/s × 2.15 s → 22; 50 req/s × 0.957 s → 48), then verified: no collapse anywhere up to the planned peaks,
  negligible shedding at C (shipping 0.84% at 50 req/s, still < 1% with p95 1000 ≤ 1200).
- **Auth's knee is noisy:** C is 8 req/s now (10 had 3.89% errors) versus 10 in v1; B2 at 40 was healthy in v1 (1156 ms)
  but not now (1765 ms), with almost the same CPU per pod (302 vs 317 m). B2 at 30 is robust in both calibrations
  (p95 853 / 787 ms, about half the SLO).
- **Settings kept for smoke and campaign:** auth 2→30 req/s (**user: keep 30** — 100% of today's measured B2 ceiling
  rather than 75%, but comparable with the pilot on identical load), shipping 10→105 req/s (bounded by the single-pod
  graceful limit, not by the B2 ceiling), SLOs 1500 / 1200 ms, timeout 5 s.

## 8.12 v2 smoke test (done 2026-10-06 — pre-registered gate FAIL on one G6 cell)

- **Runs (9):** auth H2 spike ×2, shipping H2/H3/K1 spike ×2 (the cells that failed the pilot) + shipping B1 spike ×1
  (a full 7-minute hold at 105 req/s; the ladder held it for 2 min). Not campaign data. Seed 20261007.
- **Pass requires (fixed before it ran):** G1, G2, G3, G5 clean; G6 for the four autoscaled cells; the B1 hold graceful
  (no collapse, scrapeable, no restarts). G4 does not apply (no B2 runs).
- **Launched** 2026-10-06 08:31 UTC on `ecommerce-vm` (tmux `smoke`, launcher `~/run-openloop-vm.sh
  experiment-results-openloop-smoke yes`, console `~/smoke-console.log`); expected end ≈11:40 UTC (estimate); the VM
  stops AKS when done (or on give-up).
- **Run 1 — shipping H3 spike (validated clean):** the request-rate metric now rises with the load (10.1 → 20.2 → 42.6
  req/s/pod); H3 scaled 1→2 at +19 s, 2→3 at +50 s, 3→5 at +65 s, all 5 pods Ready by +83 s; load-window goodput
  **98.34 of 103.87 req/s**, errors **5.32%** (fast 503s while scaling, **0 timeouts**); per-pod shares 0.99–1.01.
  Pilot v1, same cell: goodput 0.72 req/s, 99.30% errors, H3 never scaled.
- **Run 1 SLO-violation:** 70 s (pilot same cell: 410 s); errors are all 503 sheds (5.32%).
- **Run 2 — shipping K1 spike (validated clean, 0 critical):** KEDA scaled 1→2 at +38.8 s, 2→3 at +53.8 s, 3→5 at
  +98.8 s; first new pod Ready at +56.8 s; load-window goodput **95.95 of 103.85 req/s**, errors **7.61%** (all 503
  sheds, **0 timeouts**), SLO-violation 70 s; per-pod shares 0.99–1.01. Pilot v1, same cell: 97.99% errors, K1 scaled
  1→2→1 and stayed at 1 replica.
- **Run 3 — auth H2 spike (clean after the G1 correction, §8.9):** pre-auth tokens used, 1 Ready replica at scenario
  start and at onset; first scale-up +34.5 s, first new pod Ready +52.5 s, 5 pods; load-window goodput **26.26 of
  29.67 req/s**, errors **11.48%** (9.90% 503 sheds + 1.59% timeouts), SLO-violation 140 s. Pilot v1, same cell:
  13.79 / 19.70% errors, 140 / 170 s — but v1 started the spike at 2–3 replicas (finding #21).
- **Run 4 — shipping H2 spike (clean):** first scale-up +79.1 s, first new pod Ready +98.1 s, 5 pods; goodput **90.34
  of 103.87 req/s**, errors **13.02%** (all 503s, **0 timeouts**), SLO-violation 100 s. Pilot v1: 24.65 / 32.01%
  errors, 170 / 310 s.
- **Run 5 — shipping B1 hold (clean):** one pod at 105 req/s for the full 7-minute load window: goodput **42.32–43.07
  req/s in every minute** (window mean 42.91), **0.00% timeouts**, 58.69% fast 503s, scrapeable throughout, no
  restarts → graceful; the B1-hold condition is met. Pilot v1, same cell: goodput 0.91 req/s, 99.13% errors.
- **Runs 6–9 (rep 2, all validated clean):** shipping K1 — scale-ups +29.4 / +44.4 / +89.4 s, goodput 97.29 req/s,
  6.33% errors, 0 timeouts, 70 s; shipping H3 — +35.1 / +50.1 / +80.1 s, goodput 96.62, 6.97% errors, 0 timeouts,
  70 s; auth H2 — +49.5 (1→3) / +109.5 / +169.5 s, goodput 26.83 of 29.67, 9.56% errors (1.21% timeouts), 170 s;
  shipping H2 — +79.5 s (1→4) / +199.5 s, goodput 90.45, 12.92% errors, 0 timeouts, 100 s.
- **Finished** 11:31:31 UTC (9/9 DONE first attempt, 1172–1268 s per run); the VM stopped AKS at 11:35:26 (verified
  11:38: `Stopped` / `Succeeded`). Results tarball md5-verified; runs 1–5 byte-identical to the copies committed in
  `0931c62`. Validator: **9 runs, 0 critical, 0 warnings**.

**Gate result (`gate --reps 2`, pre-registered smoke criteria): FAIL — one G6 cell.**

| Criterion | Result |
|---|---|
| G1 instrument, G2 start state, G3 observability, G5 per-pod load | ✅ PASS, 9/9 runs |
| G4 calibration | n/a by design (no B2 runs); the tool prints FAIL for the missing B2 |
| B1 hold (graceful, scrapeable, no restarts) | ✅ met (run 5) |
| G6 auth H2 | ✅ SLO-violation 140 / 170 s (19% of mean); errors 11.48 / 9.56% (18%) |
| G6 shipping H2 | ✅ 100 / 100 s (0%); 12.92 / 13.02% (1%) |
| G6 shipping K1 | ✅ 70 / 70 s (0%); 7.61 / 6.33% (18%) |
| G6 shipping H3 | ❌ 70 / 70 s (0%) ✅, but errors 5.32 / 6.97%: range 1.65 points = 27% of the mean (limit 25% **or** 1 point) |

**Why H3's error rate differs (measured; recorded as an explanation — it does not change the verdict):**
- Rep 2's first scale-up came **15.8 s later** (+35.1 vs +19.3 s — one 15 s HPA sync period); its 3→5 step also came
  14.8 s later (+80.1 vs +65.3 s). Ready pod-seconds in the first 120 s after onset: 324 vs 281.
- Failed requests by phase (rep 1 / rep 2): onset+0–30 s 1,399 / 1,406; +30–60 s **793 / 1,496**; +60–90 s 128 / 140;
  after +90 s 0 / 0. The entire 722-request gap (1.65 points of 43,625 load-window requests) is in the 30–60 s window.
- A similar shift occurs in auth H2 (+34.5 vs +49.5 s, 15.0 s) and K1 (+38.8 vs +29.4 s, 9.4 s); those cells pass
  only because their mean error is higher, so a similar 1.3–1.9-point gap stays under 25% of the mean. Shipping H2 scaled at
  +79.1 / +79.5 s in both reps.
- One 15 s tick at the single-pod stage costs ≈ one pod's goodput × 15 s ≈ 42.9 × 15 ≈ 640 requests ≈ 1.5 points for
  shipping — more than the 1-point error floor that was meant to absorb control-loop quantization (the 20 s
  SLO-violation floor did absorb it). With n = 2, the error test fails on tick-phase luck alone whenever a cell's mean
  error is below roughly 4 × 1.5–1.7 ≈ 6–7%.
- Every structural failure of the pilot is gone in all 9 runs (no collapse, no metric blindness, 1 replica at onset,
  even per-pod load, no scrape failures or restarts), and the primary KPI replicated exactly in the three shipping
  cells (70/70, 70/70, 100/100 s).
- **Consistent effects (n = 2, indicative):** on shipping, request-rate scaling beats CPU scaling — SLO-violation
  70 s (H3, K1) vs 100 s (H2), errors 5.32–7.61% vs 12.92–13.02%, first scale-up +19–39 s vs +79 s; H3 and K1 tie.
  Almost all errors fall in the first 120 s after onset (0–34 failed requests per run in the remaining 300 s).

**Decision (user, 2026-10-06 ≈12:00 UTC): run the 180-run open-loop campaign** ("option 2"; the deadline is not a
constraint) under G6 rule v2 (§8.9), fixed before any campaign data. The smoke stays FAIL on record and is not
re-scored.

## 8.13 Campaign (approved 2026-10-06 with G6 rule v2; launched 12:33 UTC; running)

- 180 runs (`experiment-results-openloop/runlist.txt`: 2 services × 6 configs incl. H1 × 3 patterns × 5 reps), shuffled
  within rep blocks (seed 20261006); positions 1–36 are rep 1 and 37–72 rep 2, each block covering all 36 cells (18 auth
  + 18 shipping) — checked with a dry run (the plan freezes on the first real run).
- **Gate after rep block 2** (72 runs): `gate --reps 2` (G1–G5 + G6 rule v2). Pass → the 72 runs count toward the
  campaign and reps 3–5 follow after the user's go-ahead. Fail → stop; the closed-loop dataset stays primary and the
  open-loop work is reported as a robustness study.
- **Time and cost (estimates from the smoke's measured 1,237.5 s per auth run and 1,188.6 s per shipping run, at
  $0.516/h of AKS):** first 72 runs ≈24.3 h ≈ $12.5; remaining 108 ≈36.4 h ≈ $18.8; total ≈60.7 h ≈ $31.3 (the
  runner's 1,260 s/run planning figure gives 63.0 h). VM cost not included.
- **Unattended on the VM:** `run-openloop-vm.sh experiment-results-openloop yes 72` stops at 72 DONE, archives the
  results and stops AKS (new third argument; runs execute in plan order, so 72 DONE = positions 1–72).
- Settings written into `experiment-results-openloop/pilot-config.env` on 2026-10-06: caps 22 / 48, auth 2→30 and
  shipping 10→105 req/s, SLOs 1500 / 1200 ms — identical to the smoke except the seed.
- **Pre-launch verification (2026-10-06 12:04–12:33 UTC, at the user's request — no stale code or settings):**
  - All 332 tracked files outside the data folders on the VM are byte-identical to the pushed HEAD `d233aba`
    (14 non-runtime files — docs, `.gitignore`, the laptop-only analysis tool — were synced first; the runner never
    calls `pilot_openloop.py`). Campaign config, run list and launcher: identical checksums.
  - Service code running in the pods (image + overlay): auth 18/18 and shipping 12/12 Python files equal HEAD; overlay
    hashes `58d754bd7213` / `5b5de9e30a49` equal the hash of the VM's files; caps 22 / 48. ACR `:latest` last changed
    2026-05-02 (auth) and 2026-04-17 (shipping); deployments use `imagePullPolicy: Always`.
  - Prometheus: `kubectl diff` against `monitoring/prometheus.yaml` — no differences. KEDA, metrics-server, Prometheus
    and prometheus-adapter running; custom, external and resource metrics APIs available; no leftover autoscalers or
    k6 jobs. The 1 m `http_requests_per_second` adapter rule (H3) and the K1 `[1m]` queries match the repo.
  - **Known drift, left in place:** the live prometheus-adapter config still has the rule
    `auth_http_requests_per_second_30s` (added and reverted in the repo on 2026-08-15, never removed from the
    cluster). Nothing references it, and it was present during the closed-loop campaign, the pilot and the smoke;
    the user asked for the safest option, so it was left rather than hand-editing the adapter before a 24 h run.
- **Launched 2026-10-06 12:33:42 UTC** on `ecommerce-vm` (tmux `campaign`, console `~/campaign-console.log`,
  `run-openloop-vm.sh experiment-results-openloop yes 72`). The VM froze the plan (seed 20261006); its order is
  identical to the laptop's dry run (same checksum, 180 lines). Expected checkpoint at launch ≈13:00 UTC on
  2026-10-07 (estimate; the two H1 re-runs added later move it to ≈13:30 — see the progress bullet below).
- **Start-up hiccup (no data affected):** attempt 1 stopped at 12:37:04 in the auth reset — a pod left in phase
  `Failed` (Error, exit 3) by the 11:35 AKS stop kept the runner's "no pod outside Running/Completed" check from ever
  passing (the deployment itself was 1/1 Ready). The dead pod object was deleted at 12:38:41; the launcher's attempt 2
  passed the same check at 12:38:48 and run 1 started. No run had begun, so nothing was recorded. **Before every
  future launch after an AKS start:** delete `Failed` auth/shipping pods (§8.15).
- **H1 changed to 80% CPU, the Kubernetes default target (user decision, 2026-10-06 ≈15:36 UTC; commit `dddd996`
  pushed 15:38; copied to the VM and validated with a server dry run at 15:38).** Reason: H1 stands for "HPA out of the
  box"; its behavior was already the Kubernetes default, but its 70% target was a judgment call (Part 11 §11.6 #1).
  Decided for construct validity, not from H1 results, and possible without a second explanation because the user
  also chose "Replace" (§8.14). Two H1 runs had already run at 70% — plan positions 1 (auth oscillating rep 1) and 9
  (shipping oscillating rep 1). They are archived in `experiment-results-openloop/superseded-h1-70pct/` and marked
  not-done, so the launcher re-runs them at 80% right after position 72 and before it stops AKS; every other H1 run
  (from position 13) runs at 80%. The manifests are read from disk at each config apply, so no running script was
  edited. Done at 15:40 UTC, between runs: both runs' saved HPA objects show `averageUtilization: 70`; the archive
  copies are checksum-identical (26 files each); the state file was backed up to
  `superseded-h1-70pct/pilot-state-before-h1-change.txt` and the two DONE lines removed (7 DONE, positions 1 and 9
  pending again). Confirmed live: position 13 (auth H1 spike rep 1) applied H1 at 16:44:18 UTC and the HPA in the
  cluster read a target of 80%.
- **Run 1 checked end to end** (auth H1 oscillating rep 1, 12:38–12:58, 1242 s; superseded — H1 was still 70%): its metadata records
  `open-loop-arr-v2`, auth 2→30 req/s, timeout 5 s, 225 VUs, no connection reuse, k6 `0.46.0`, overlay
  `58d754bd7213`, cap 22 and 120 pre-auth tokens (k6 logged `PREAUTH_USED tokens=120`); raw data md5-verified,
  exit code 0. Validator: 0 critical, 0 warnings; 10,359 of 10,359 scheduled arrivals; 1 Ready pod at start and at
  onset; first scale-up +64.9 s, 5 pods; load-window errors 21.93% (3.23% timeouts), SLO-violation 160 s.
- **Progress at 17:36 UTC:** 12/72 DONE (positions 2–8 and 10–14), position 15 running; 20.1 min per run on average
  (positions 1–14); no failure since the start-up hiccup. Remaining: positions 15–72 plus the re-runs of 1 and 9 —
  60 runs, ≈20 h; the VM should stop AKS at ≈13:30 UTC on 2026-10-07 (estimate).

## 8.14 Implications for the thesis text

- **BAB 3 generator rationale must change:** closed loop was justified as "open loop drops iterations and inflates
  errors through k6 queuing". With a correctly sized generator that is false (0 drops, server-side failures). The
  honest framing: closed loop measures scaling under self-throttled load; open loop measures scaling under a fixed
  offered load, where slow scaling turns directly into rejected/failed requests.
- **If the open-loop campaign passes:** BAB 3 must describe the admission control (standard load shedding; exact cap
  rule), the auth pre-authentication, the ConfigMap overlay (same images), the open-loop KPIs (§8.2), and the gate.
  The closed-loop dataset becomes a second generator condition rather than being discarded.
  > **Superseded by the user's decision (2026-10-06 ≈15:36 UTC): "Replace".** If the open-loop campaign passes its
  > gate, it is the thesis dataset for BAB 4–5. The closed-loop campaign is methodology background — the evidence
  > for why the generator was switched (BAB 3, details in an appendix) — not a second set of results compared config
  > by config. If the campaign fails its gate, the closed-loop dataset is the thesis dataset and the open-loop work
  > becomes a short robustness section.
- **Disclose regardless of the decision:** the auth `setup()` burst in the closed-loop H1/H2 runs; the closed-loop
  throughput asymmetry (§8.1); that the generator choice changes the between-config spread by more than an order of
  magnitude (§8.7, indicative); the request-rate metric-blindness failure mode and why the v2 services shed load.
- **New candidate finding for BAB 4/5:** pod-exported request-rate metrics fail exactly when needed under overload
  unless the service sheds load (or the metric is measured upstream).

## 8.15 Operations quick reference

```bash
# Ladder / run (from the repo root; Git Bash or Linux)
OPENLOOP_RESULTS_DIR=experiment-results-openloop bash scripts/run-pilot-openloop.sh ladder --service shipping-rate-service --config b1 --rates "50,60,80,105" --max-inflight 48
OPENLOOP_RESULTS_DIR=experiment-results-openloop bash scripts/run-pilot-openloop.sh run --dry-run
OPENLOOP_RESULTS_DIR=experiment-results-openloop bash scripts/run-pilot-openloop.sh run --resume

# Unattended on the VM (stops AKS when done, at the stop-at count, or on give-up)
# After every AKS start, first remove pods the stop left in phase Failed — the runner's reset waits for zero of them:
kubectl get pods -n ecommerce --field-selector=status.phase=Failed --no-headers | grep -E '^(auth-service|shipping-rate-service)-'
kubectl delete pod -n ecommerce <each pod listed above>
tmux new-session -d -s campaign "bash /home/kevin/run-openloop-vm.sh experiment-results-openloop yes 72 > /home/kevin/campaign-console.log 2>&1"
# reps 3-5 after the gate: same command with stop-at 180 (or omitted)

# Analysis (laptop, bundled Python)
PYTHONUTF8=1 PILOT_OPENLOOP_DIR=experiment-results-openloop-smoke tools/python312/python.exe scripts/pilot_openloop.py validate
PYTHONUTF8=1 PILOT_OPENLOOP_DIR=experiment-results-openloop tools/python312/python.exe scripts/pilot_openloop.py gate --reps 2
```

**Costs of this study (estimates):** 2026-10-05/06 session ≈10.4 h of AKS ≈ $5.4 (idle start, 6 ladders, pilot);
2026-10-06 v2 work from ≈06:30 UTC, ≈5.2 h ≈ $2.7 including the smoke test; ACR builds $0 (none ran). The VM
(B2ats_v2) ran throughout. Campaign: AKS running since the 12:23 UTC start, ≈5.2 h ≈ $2.7 by 17:36 UTC; to the
72-run stop ≈25 h ≈ $13; reps 3–5 ≈36 h ≈ $19 more.
