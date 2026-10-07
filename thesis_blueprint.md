# Definitive Thesis Blueprint: HPA vs KEDA Comparative Study

> **Index and executive summary — restructured 2026-10-06.** The full blueprint now lives in
> [`thesis_blueprint/`](thesis_blueprint/). Every section of the former single-file blueprint (2,235 lines) was moved
> there **verbatim**, with its original section numbers (§1–§12) and finding numbers (#1–#16) unchanged so all
> cross-references still resolve; later additions are dated. The single-file version remains in git history (last at
> commit `56bcf8c`). Numbers in this summary are copied from the parts, which give their sources.

---

## Document map

| Part | File | Contents | Former section |
|---|---|---|---|
| 01 | [01-direction-and-findings.md](thesis_blueprint/01-direction-and-findings.md) | Thesis evolution, strengths/risks, must-fix table, what is validated on AKS, **confirmed findings #1–#22**, what it means for the thesis, dataset status | §1 |
| 02 | [02-timeline.md](thesis_blueprint/02-timeline.md) | Full chronological timeline, 2026-04-07 → 2026-10-06 | §1 (timeline) |
| 03 | [03-calibration-deep-dive.md](thesis_blueprint/03-calibration-deep-dive.md) | Closed-loop shipping calibration: why `ramping-vus`, PEAK_VUS = 80, CPU not purely wait-dominant, threshold 5 → 15, pre-flight bug fixes, measured B1/B2 gates | §1 (deep dive) |
| 04 | [04-title-and-scope.md](thesis_blueprint/04-title-and-scope.md) | Approved title and its rationale; scope, assumptions, boundaries | §2–§3 |
| 05 | [05-architecture-and-tooling.md](thesis_blueprint/05-architecture-and-tooling.md) | AKS sizing (3× D4as_v5), pod inventory, resource budget, cost; platform decisions (in-cluster PostgreSQL, ACR, in-cluster k6, Prometheus/Grafana) | §4–§5 |
| 06 | [06-methodology-and-kpis.md](thesis_blueprint/06-methodology-and-kpis.md) | Factorial design, the 6 configurations with YAML, load patterns, protocol, run count; KPIs (closed- and open-loop definitions) | §6–§7 |
| 07 | [07-risks.md](thesis_blueprint/07-risks.md) | Risks 1–12 with mitigations; operational lessons | §8 |
| 08 | [08-open-loop-study.md](thesis_blueprint/08-open-loop-study.md) | **Open-loop study:** motivation, pre-set criteria, tooling, calibration, pilot results and verdict, user decisions, v2 fixes, robustness gate (rules v1 and v2), v2 calibration, smoke result, campaign (running), thesis structure ("Replace"), thesis implications | new |
| 09 | [09-strategy-plan-assessment.md](thesis_blueprint/09-strategy-plan-assessment.md) | Stand-out strategy (narrative, Pareto, timeline figure, decomposition table), project plan and status, final assessment | §9–§11 |
| 10 | [10-chapter-outline.md](thesis_blueprint/10-chapter-outline.md) | BAB 1–5 writing guide (Struktur Perancangan Jaringan) | §12 |
| 11 | [11-provenance-and-validity.md](thesis_blueprint/11-provenance-and-validity.md) | **Defense guide:** where every setting comes from (default / measured / fairness / judgment / pre-registered), validity by type, fairness controls, judgment calls, known weak spots and their handling, evidence that the results are real, ready answers, sources to cite, whether the comparisons are fair (§11.10) | new |
| 12 | [12-deviation-and-analysis-plan.md](thesis_blueprint/12-deviation-and-analysis-plan.md) | **Deviation after the gate FAIL and the pre-registered analysis plan** for the full open-loop dataset: reasons, unchanged settings, data-quality rules, outcomes O1–O5, analyses A1–A6, reporting rules, execution of reps 3–5 | new |

---

## Thesis at a glance

- **Title (approved by Pak Cahya):** *"Analisis Pengaruh Jenis Metrik Penskalaan dan Mekanisme Autoscaler (HPA vs KEDA)
  terhadap Responsivitas dan Efisiensi Resource Aplikasi Microservices pada Kubernetes"* (Part 04).
- **Design:** controlled factorial experiment — 6 configurations × 3 load patterns × 5 repetitions × 2 services =
  **180 runs**. B1 = fixed 1 replica, B2 = fixed 5; H1 = HPA with Kubernetes defaults — CPU 80% and default behaviour
  (the closed-loop background campaign ran H1 at 70%; Part 11 §11.2 D); H2 = HPA CPU 50%
  (aggressive behaviour); **H3 = HPA on request rate via prometheus-adapter (the fairness control that isolates metric
  type from engine)**; K1 = KEDA Prometheus scaler. H2/H3/K1 share the behaviour block (scale-up 0 s, 5 pods/15 s;
  scale-down 30 s, 100%/15 s). Thresholds auth 5, shipping 15 req/s/pod; 1 m rate window; 15 s sync/polling;
  min 1 / max 5 (Part 06).
- **Services:** auth-service = CPU-bound control (bcrypt); shipping-rate-service = wait-dominant fan-out to
  carrier-mock; product-service = exploratory appendix (dependency-limited by its database) (Part 01 #5–#11).
- **Load patterns:** gradual, spike, oscillating — each a 12-minute k6 schedule (2 m warm-up, 7 m pattern, 3 m
  ramp-down), `noConnectionReuse: true`.
- **Datasets ("Replace", decided 2026-10-06):** the thesis dataset was to be the **open-loop campaign**
  (`ramping-arrival-rate`, auth 2→30 and shipping 10→105 req/s, per-pod load shedding) if it passed its robustness
  gate, with the **closed-loop campaign** (`ramping-vus`, auth 1→12 VUs, shipping 10→80 VUs; complete) as methodology
  background and fallback (Part 08 §8.14). **The gate failed on 2026-10-07** after rep blocks 1–2 (72 runs); the user
  continued as a documented deviation, so the open-loop campaign remains the thesis dataset, with repeatability as a
  measured outcome and the analysis plan fixed before reps 3–5 (Part 12).
- **Platform:** AKS `ecommerce-aks` (RG `ecommerce`, Indonesia Central, 3× Standard_D4as_v5, Kubernetes 1.33.7), KEDA
  AKS add-on, prometheus-adapter (Helm), in-cluster Prometheus, k6 as Kubernetes Jobs; runs driven from
  `ecommerce-vm` (Part 05). Runner protocol: reset (`RESET_WAIT` 120 s) → apply + stabilize (90 s) → readiness →
  k6 (12 min) → `EXPORT_WAIT` 180 s → export.

---

## Current status (2026-10-07, 14:00 UTC)

| Track | Status |
|---|---|
| **Closed-loop final dataset** | ✅ 180/180 runs (2026-08-15 → 08-17, 58 h 49 m), all valid Prometheus exports, 177/180 at 0.00% error; `validate-results.sh` 0/0/0, `deep_validate.py` 0 critical (19 stale heuristic warnings on auth B1). Under "Replace" it was the fallback if the open-loop campaign failed its gate. The gate failed on 2026-10-07, but the user continued as a documented deviation (Part 12), so it stays **methodology background**. (Part 01 #13, Dataset Status; Part 08 §8.13–§8.14) |
| **Open-loop pilot v1** | ✅ 20 runs (2026-10-05/06). Generator stable (0 dropped). Pre-set rule verdict **GO** via the criterion-4 explanation clause; strict reading **STAY**. (Part 08 §8.7) |
| **User decisions** | Switch to a full 180-run open-loop campaign **only if it is robust** (Part 08 §8.8). After the smoke: run the campaign under G6 rule v2; thesis structure **"Replace"**; **H1 = 80%** (Kubernetes default) (Part 08 §8.9, §8.13, §8.14). |
| **v2 fixes + calibration** | ✅ Admission control (both services), auth pre-authentication, robustness gate G1–G6; recalibrated 2026-10-06. (Part 08 §8.9–§8.11) |
| **v2 smoke test** | ✅ Done 2026-10-06 08:31–11:31 UTC (AKS stopped 11:35). 9/9 runs clean; B1 hold graceful; SLO-violation seconds replicate. **Pre-registered gate FAIL on one cell** (shipping H3 error rate 5.32 / 6.97%, one 15 s HPA cycle apart). (Part 08 §8.12) |
| **Open-loop campaign** | ✅ Rep blocks 1–2 done: 72/72 at 2026-10-07 13:31 UTC (H1 = 80%; positions 1 and 9 re-run), AKS stopped 13:33:57, all raw files checksum-verified. **Pre-registered gate (rule v2): FAIL** — G1–G4 pass in all 72 runs; G5 fails in 1 run; G6 fails in 3 of 24 cells, all CPU-based (request-rate cells reproducible 12/12; finding #23). Pre-registered consequence: stop. **User decision (2026-10-07): continue with reps 3–5 as a documented deviation** — the open-loop campaign stays the thesis dataset; analysis plan in Part 12, pushed before any new run; launch awaits the go-ahead (≈36 h ≈ $19, estimate). (Part 08 §8.13, Part 12) |
| **Analysis (Phase 4)** | Waits for the gate; runs on the thesis dataset (the open-loop campaign if it passes): Wilcoxon tests and effect sizes, time-to-scale extraction, Resource Cost Index / Pareto, figures (`thesis-figures/` PNGs are from superseded data). (Part 09 §10) |
| **Writing** | BAB 1–3 drafted (`Skripsi_Ignatius_Kevin_Wijaya.docx`, last edited 2026-06-06). Under "Replace", BAB 3 must present the open-loop method (generator, load shedding, pre-login, gate, H1 = 80%) with the closed-loop campaign as the reason for switching; its old generator rationale and auth arrival-rate profile are out of date (Part 08 §8.14, Part 10 notes, Part 11). BAB 4–5 wait for the campaign. |

---

## Headline results — closed-loop final dataset (Part 01, findings #13–#16; methodology background — the open-loop campaign is the thesis dataset, Part 12)

p95 latency in ms, mean ± population SD over 5 reps (2026-08-15 → 08-17):

| Config | Ship gradual | Ship spike | Ship oscillating | Auth gradual | Auth spike | Auth oscillating |
|---|---|---|---|---|---|---|
| B1 | 3218 ± 22 | 3324 ± 22 | 3272 ± 15 | 3376 ± 79 | 4560 ± 102 | 3134 ± 102 |
| B2 | 917 ± 0 | 917 ± 0 | 916 ± 0 | 1134 ± 12 | 1452 ± 21 | 1154 ± 27 |
| H1 | 920 ± 2 | 1101 ± 177 | **2656 ± 486** | 1164 ± 22 | 1496 ± 24 | 1170 ± 19 |
| H2 | 918 ± 1 | 993 ± 109 | 3008 ± 409 | **1132 ± 16** | 1486 ± 85 | **1160 ± 32** |
| H3 | 917 ± 0 | 987 ± 64 | 3096 ± 22 | 1160 ± 22 | **1462 ± 57** | 1188 ± 25 |
| K1 | **916 ± 0** | **941 ± 10** | 2748 ± 596 | 1150 ± 20 | 1476 ± 38 | 1260 ± 25 |

- **Headline (#14):** the best autoscaler closes ≥ 99% of the B1→B2 gap in five of six conditions; every autoscaler
  closes ≥ 92%. **The single failure is shipping (wait-dominant) under oscillating load** (best: H1, 26% of the gap;
  the four autoscalers close 7.5–26%). The proposed service-time mechanism is only partly verified: auth stays at or
  near `maxReplicas` through its troughs, so the auth/shipping contrast is confounded (validation note under #14).
- **Secondary effects (#15):** metric (request rate vs CPU) and engine (KEDA vs HPA) separate only on shipping spike —
  request rate ≈ 10% better (H3 vs H1 −10.4%), KEDA a further ≈ 5% with ≈ 6× lower SD (K1 941 ± 10 vs H3 987 ± 64).
  Elsewhere within ±2.5%, except auth oscillating (HPA better, H3 1188 vs K1 1260) and shipping oscillating (all
  failing). The old "request rate −49% on gradual" claim was a connection-pinning artifact (#12).
- **Validity gates (measured B1/B2 p95 ratio):** shipping 3.51× / 3.62× / 3.57×, auth 2.98× / 3.14× / 2.72× (Part 03).
- **Closed-loop caveats found in October:** auth `BASE_VUS=1` delivers 11.6–15.9 req/s, not ≈6 (Part 01 correction);
  auth `setup()`'s 120 bcrypt logins run right before the warm-up and can pre-scale CPU HPAs (#21).

---

## Headline — open-loop study (Part 08; findings #17–#22)

- **Pilot v1 (2026-10-05/06, 20 runs, spike):** auth 2→30 req/s (SLO 1.5 s), shipping 10→105 req/s (SLO 1.2 s), 5 s
  timeout, k6 0.46.0.
  - 0 dropped iterations; attempted = offered within 0.02 req/s (#17).
  - Load-window errors: B1 auth 85.84%, shipping 99.14%; B2 0.00% (p95 887/843 and 919/917 ms).
  - **Shipping H3/K1 never scaled** (98.56–99.18% errors): the pod-exported request-rate metric went blind when the
    single pod collapsed (#19). Shipping H2 28.33%.
  - Auth: request rate beat CPU (errors H3 8.90%, K1 9.11%, H2 16.75%; first scale-up 21–39 s vs 51–66 s) (#20).
  - H2/H3/K1 spread **20.3% (auth) / 41.5% (shipping) of the B1→B2 gap** vs **0.77% / 2.17%** in closed loop (#18).
  - Rule verdict **GO** via the poll-phase explanation (auth H3 40%, shipping H2 58% rep disagreement); strict
    reading **STAY**.
- **v2 (2026-10-06):** per-pod admission control as the outermost middleware (cap 22 auth / 48 shipping, 503 for the
  excess, probes and `/metrics` exempt), delivered by ConfigMap overlay on the unchanged images because ACR Tasks are
  unavailable in Indonesia Central; auth tokens pre-authenticated during the reset; robustness gate G1–G6 with
  replicate rule "±25% or ≤ 20 s / ≤ 1 error point" (rule v1, judged the smoke; the campaign uses rule v2: 50% or
  ≤ 30 s / ≤ 2 points).
  - One shipping pod is now graceful up to 105 req/s (goodput 42.36, 0 timeouts) but collapses between 105 and 140.
  - Smoke runs 1–2: shipping H3 scales 1→5 within 83 s, goodput 98.34 of 103.87 req/s (pilot: 0.72); shipping K1
    reaches 5 pods by +98.8 s, goodput 95.95 of 103.85 (pilot: 97.99% errors); 0 timeouts in both (#22).
  - Smoke runs 3–5: shipping H2 goodput 90.34 of 103.87, 13.02% errors, 0 timeouts (pilot: 24.65 / 32.01% errors);
    auth H2 11.48% errors from 1 replica at onset; the shipping B1 pod holds 105 req/s for 7 min at 42.32–43.07 req/s
    goodput per minute, 0 timeouts (pilot: collapse) (#22).
  - Smoke verdict: all 9 runs clean, but the pre-registered gate fails on one G6 cell — shipping H3 errors 5.32 /
    6.97% (27% of the mean; limit 25% or 1 point), from a first scale-up one 15 s HPA cycle later in rep 2. On
    shipping, request-rate scaling (70 s, 5.32–7.61% errors) beats CPU scaling (100 s, 12.92–13.02%) in both reps (#22).
- **Campaign (from 2026-10-06 12:33 UTC):** 180 runs (2 services × 6 configs × 3 patterns × 5 reps), gate after rep
  blocks 1–2 (72 runs) under G6 rule v2 (50% or ≤ 30 s / ≤ 2 points), committed before any campaign data. Pre-launch
  check: all 332 tracked files outside the data folders on the VM equal the pushed HEAD; code in the pods equals HEAD. H1 set to the Kubernetes
  default 80% (positions 1 and 9, run at 70%, archived and re-run). Rep blocks 1–2 finished 2026-10-07 13:31 UTC.
  - **Gate: FAIL.** Measurement sound (G1–G4 pass in all 72 runs), but repeatability failed in 3 of 12 CPU-based
    cells and in none of the 12 request-rate cells. In auth oscillating H2 rep 1 the HPA's lagging CPU reading made it
    scale in anti-phase to the load (≈50% errors in every peak; rep 2: 16.28% overall) (#23, Part 08 §8.13).
  - Seconds over SLO (rep 1/rep 2), shipping spike: K1 70/70, H3 80/70, H2 110/90, H1 140/100; shipping gradual:
    H3 and K1 0/0, H1 70/60; auth gradual: K1 40/40, H3 50/50, H2 100/70, H1 140/70.

---

## Decision log

| Date | Decision | Reason | Detail |
|---|---|---|---|
| 2026-04-13/14 | Auth/product CPU request 100m → 250m; H3/K1 threshold 50 → 5 (auth) | Tiny requests made CPU HPA unfairly eager; 50 req/s was unreachable from Prometheus' observed rate | Part 01 #2–#4, Part 02 |
| 2026-04-16 | Core non-CPU service pivots from product-service to the new shipping-rate-service; product kept as appendix | Product's single database became the bottleneck (scaling the wrong tier) | Part 01 #6–#11, Part 02 |
| 2026-04-17 | Shipping: `ramping-vus`, PEAK_VUS = 80, threshold 15 req/s/pod | Calibration ladder; threshold must stay silent at warm-up | Part 03 |
| (title) | Title v5 with "Efisiensi Resource" approved | Reflects the two-factor design; Pak Cahya's wording | Part 04 |
| (platform) | 3× D4as_v5; in-cluster PostgreSQL, ACR, in-cluster k6, in-cluster Prometheus/Grafana; KEDA add-on; prometheus-adapter via Helm | Headroom for unbiased benchmarking; constant DB; no LB/network noise | Part 05 |
| 2026-08-15 | `noConnectionReuse: true` everywhere; auth → closed-loop `ramping-vus` (1→12 VUs); `setup()` login-first; auth rate window back to 1 m | Connection pinning starved new pods; open-loop meltdowns; constant 120-failure floor; 30 s window under-sampled | Part 01 #12, #16 |
| 2026-08-15 | Re-run all 180 runs (not only burst patterns) | Internal consistency after the generator change | Part 01 #12, Part 02 |
| 2026-10-05 | Pilot an open-loop generator; pin k6 0.46.0 for both services; leave AKS running; long runs on the VM | Decide with data whether open loop is viable now; reproducible generator | Part 08 §8.1–§8.3 |
| 2026-10-05 | Open-loop settings: auth base 2 (not 4), peak 30, SLO 1.5 s; shipping base 10, peak 105 ("best path"), SLO 1.2 s | H2's CPU target binds the auth base; shipping 2.5 × C conflicts with the B2 margin, and B1 already fails at 60 | Part 08 §8.5 |
| 2026-10-05 | Let the pilot continue after seeing metric blindness in run 1 | It is the failure mode the pilot exists to detect; pre-set criteria capture it | Part 08 §8.6 |
| 2026-10-06 | Stop AKS only after the pilot fully finished; add laptop SSH key to the VM | User instructions; result transfer | Part 08 §8.3 |
| 2026-10-06 | **Switch the campaign to open loop only if robust** | User | Part 08 §8.8 |
| 2026-10-06 | Approve admission control, gate with absolute floors, keep KEDA `ignoreNullValues` in reserve | Root-cause fix; quantization-aware reproducibility test; keep autoscaler manifests identical | Part 08 §8.9 |
| 2026-10-06 | ConfigMap code overlay instead of an image rebuild | ACR Tasks unavailable in Indonesia Central; identical images avoid dependency drift | Part 08 §8.10 |
| 2026-10-06 | Admission control must be the outermost middleware | Inner placement still collapsed at 105 req/s | Part 08 §8.10–§8.11 |
| 2026-10-06 | Keep auth peak at 30 req/s; run the smoke test on the VM and stop AKS after | Comparable with the pilot; B2 at 30 is healthy with margin; unattended run | Part 08 §8.11–§8.12 |
| 2026-10-06 | Restructure the blueprint into an index + parts | User request; the single file had grown to 2,235 lines | this file |
| 2026-10-06 | Stop ignoring `*.md`; commit and push the October work (tooling, services, docs, open-loop data); leave `Thesis.docx` uncommitted | User: keep the docs in the repo; the repo is public, so the thesis draft is committed only on request | this file |
| 2026-10-07 | **Continue past the gate FAIL as a documented deviation:** run reps 3–5; the open-loop campaign is the thesis dataset; repeatability becomes a measured outcome; analysis plan fixed and pushed before any rep 3–5 data | G1–G4 passed in all 72 runs; the G5/G6 failures trace to the HPA's lagging CPU reading (system behavior); open loop is the realistic load model; 2 reps cannot characterize the variability | Part 12 |
| 2026-10-06 | **Thesis structure "Replace":** if the open-loop campaign passes its gate it is the thesis dataset; the closed-loop campaign becomes methodology background (why the generator was switched), not a second result set; it stays the fallback if the gate fails | The user's original decision was to switch; one dataset keeps the thesis on HPA vs KEDA | Part 08 §8.14 |
| 2026-10-06 | **H1 = 80% CPU** (the Kubernetes default target) for the campaign, from position 13; positions 1 and 9 (run at 70%) archived and re-run at 80% before the gate | H1 stands for HPA out of the box; 70% was an undocumented judgment call; decided for construct validity, not from H1 results (`dddd996`) | Part 08 §8.13, Part 11 §11.6 #1 |
| 2026-10-06 | After the smoke FAIL: run the 180-run open-loop campaign ("option 2"; deadline not a constraint) under G6 rule v2 — 50% of the mean or ≤ 30 s / ≤ 2 points — fixed before any campaign data; smoke stays FAIL | One 15 s autoscaler cycle, the normal gap between reps (6 of 8 pairs), produced up to 27% / 30 s / 1.93 points; G2/G3 now catch the pilot's defects directly; rule v2 still rejects pilot v1 | Part 08 §8.9, §8.12–§8.13 |

---

## Corrections and contradictions recorded (2026-10-05/06)

- Auth `BASE_VUS=1` throughput: **11.6–15.9 req/s**, not ≈6 (Part 01 "validated on AKS"; same stale comment in
  `k6-auth-job.yaml`).
- Finding #16 and the "why `ramping-vus`" rationale blamed open-loop failures on the executor / k6 queuing; a
  correctly sized open-loop generator drops nothing and the failures are server-side (Part 01 #16 note, Part 03 note).
- Closed-loop peak throughput figures quoted in the open-loop brief were off: shipping B1 25.2–25.4 req/s (not ≈48),
  auth B1 12.0–12.9 (not ≈16), auth B2 44.6–46.7 (not ≈51); shipping B2 112.4–112.7 matched ≈114 (Part 08 §8.4).
- A base rate below the H3/K1 threshold does not guarantee every autoscaler starts at 1 replica — H2's CPU target binds
  for auth (Part 08 §8.5).
- BAB 2.1.8 / BAB 3 generator justification must be rewritten (Part 10 notes, Part 08 §8.14).
- Open-loop analysis tool, two implementation bugs fixed (criteria unchanged): G1 "full schedule" used k6's run clock
  (which includes `setup()`) and falsely flagged smoke auth H2 rep 1 once pre-auth made `setup()` instant — now an
  arrival count; the analysis cache was keyed by run id only and served smoke data for two v1 runs — now tied to the
  raw file's md5; no reported number was affected (v1 re-analysis: 0 differences) (Part 08 §8.9).
- Cluster vs repo drift found before the campaign: the live prometheus-adapter config still carries the
  `auth_http_requests_per_second_30s` rule that the repo reverted on 2026-08-15. Unused by every manifest and present
  in all datasets so far; left in place (Part 08 §8.13).
- H1 (70% CPU) was described as "the most common production config" without a source; Kubernetes' default target is
  80% (API reference; confirmed by a server dry run on the campaign cluster) and its walkthrough uses 50%. Resolved for
  the thesis dataset: H1 now uses 80% (`dddd996`); the closed-loop background campaign ran 70% (Part 06 note, Part 11
  §11.2 D and §11.6 #1).
- Prometheus' default scrape interval is 1 minute; the 15 s used here is a project setting chosen to match the 15 s HPA
  loop, not a platform default (Part 11 §11.2 E).
- G6 rule v1's 1-point error allowance was meant to absorb control-loop timing but was never derived from it: one 15 s
  cycle costs ≈1.5 points on shipping (1.66 measured in the smoke). Replaced for the campaign by rule v2 (Part 08 §8.9).

---

## Open items and next steps

1. **Reps 3–5 (decided 2026-10-07, documented deviation):** the user reviews Part 12; it is then committed and pushed
   before any new run. With the user's go-ahead: start AKS, delete pods left `Failed` by the stop, check the VM against
   HEAD, run positions 73–180 (`run-openloop-vm.sh experiment-results-openloop yes`, ≈36 h ≈ $19, estimate).
2. **After reps 3–5:** fetch and verify, apply the data-quality rules (Part 12 §12.2), then analyses A1–A6.
3. **Phase 4 analysis** on the thesis dataset: Wilcoxon tests and effect sizes, time-to-scale from `k8s-events.txt`,
   Resource Cost Index and Pareto, decomposition table, regenerated figures; add the k6-vs-Prometheus cross-check to
   the validator (descriptive only, Part 11 §11.7).
4. **Writing:** rewrite BAB 3 around the open-loop method (generator, load shedding, pre-login, gate, H1 = 80%) with
   the closed-loop campaign as the reason for switching; use Part 11 for provenance and sources; draft BAB 4–5 after
   the campaign.
5. **Research-data to-dos (Part 11 §11.7):** export the Azure Activity Log and cost records privately (90-day
   retention; the August entries expire around mid-November); archive a DOI snapshot at submission; write the
   reproducibility section.
6. **Housekeeping:**
   - All October work, including the G6 rule v2, the H1 change and these blueprint updates, is committed and pushed.
   - `.gitignore` no longer ignores `*.md` (only `*.pdf`); the blueprint parts and `pilot-openloop-report.md` are
     versioned. `Thesis.docx` (repo root) stays untracked unless the user asks — the repository is public.
   - `ecommerce-vm` runs the campaign — deallocate it only after the campaign; the laptop SSH key is authorised on it.
   - The live prometheus-adapter config still has the unused `auth_http_requests_per_second_30s` rule (Part 08 §8.13).
   - `deep_validate.py` heuristics still assume the retired auth open-loop profile.
   - Shipping closed-loop metadata records `load_profile.version = "wait-bound-v1"` although those runs used
     `noConnectionReuse`.

---

## Section-number map (for references in older notes and documents)

| Old reference | Now in |
|---|---|
| §1 (re-analysis, findings, dataset status) | Part 01 |
| §1 timeline | Part 02 |
| §1 shipping calibration deep dive ("PEAK_VUS deep-dive", measured gates) | Part 03 |
| §2 title, §3 scope | Part 04 |
| §4 AKS architecture, §5 platform/tooling | Part 05 |
| §6 methodology, §7 KPIs | Part 06 |
| §8 risks | Part 07 |
| §9 strategy, §10 timeline plan, §11 assessment | Part 09 |
| §12 chapter outline (BAB 1–5) | Part 10 |
| findings #1–#22 | Part 01 |
| open-loop study | Part 08 |
| provenance, validity, defense Q&A, sources | Part 11 |
| deviation after the gate, analysis plan | Part 12 |
