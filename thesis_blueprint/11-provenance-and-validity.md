# Thesis Blueprint — Part 11: Provenance, Validity and Defense Q&A

> Part of the thesis blueprint — index and executive summary: [thesis_blueprint.md](../thesis_blueprint.md).
> New part, written 2026-10-06. Purpose: answer the questions a supervisor or examiner asks about the experiment —
> *where does this value come from, why this value, is it valid, and how do we know the results are real?* Every value
> is traced to a repository file, a measurement or a document; figures marked (estimate) are estimates. Sources are in
> §11.9 — check edition, volume and page details against the original before citing them.

---

## 11.0 The short answer

"Every setting in the experiment comes from one of five sources: a platform default we left unchanged, a value measured
in our own calibration runs, a fairness rule that holds a value equal across configurations, a disclosed design choice,
or a decision rule written down before the data it judges. Each value is recorded in the repository with its reason,
and checks built into every run show the settings did what they were meant to do."

## 11.1 Five kinds of source, and how to justify each

| Code | Source | What to say | Evidence to show |
|---|---|---|---|
| **[D]** | Platform or tool default, left unchanged | "We used the documented default." | Kubernetes, KEDA, k6 documentation |
| **[M]** | Measured in this project | "Chosen by a stated rule from our calibration data." | Ladder data and results (Parts 03, 08) |
| **[F]** | Fairness control | "Held equal across configurations so only the variable under test differs." | Identical manifest fields |
| **[J]** | Judgment (design choice) | "Chosen for a stated reason, fixed in advance, applied identically; the conclusions either do not depend on it or are limited accordingly." | Rationale in Parts 04/06, limitations |
| **[P]** | Pre-registered rule | "Written and committed before the data it judges." | Git commit and timestamp |

A judgment call is not a weakness in itself. It becomes one only if it is hidden, changed after seeing the results, or
applied unequally. §11.5 lists every judgment call with its alternatives.

## 11.2 Provenance register

### A. Experimental design

| Setting | Value | Src | Reason and evidence |
|---|---|---|---|
| Design | 2 services × 6 configs × 3 patterns × 5 reps = 180 runs | J | Full factorial: the H2-vs-H3 contrast isolates the metric, H3-vs-K1 the engine (Part 06). Factorial design and replication: Jain (1991). |
| Services | auth-service (CPU-bound control), shipping-rate-service (wait-dominant) | J | Opposite workload types, so the metric question has a control and a test case (Part 06). Product-service moved to an appendix after its database became the bottleneck (Part 01 #6–#11). |
| Repetitions | 5 per cell | J | Repeated measurement so spread and significance can be reported (Papadopoulos et al.; Arcuri & Briand 2011). |
| Run order | Shuffled within each rep block, fixed seed (campaign 20261006, smoke 20261007) | J | Prevents time-of-day or cluster-drift effects from lining up with one config (Jain 1991); the seed makes the order reproducible. |
| Isolation | One service autoscaled at a time; the others fixed at 1 replica; Cluster Autoscaler off; 3 fixed nodes | F/J | Removes cascading and node-scaling confounds (Part 04 boundaries). |

### B. Platform

| Setting | Value | Src | Reason and evidence |
|---|---|---|---|
| Cluster | AKS, 3× Standard_D4as_v5, Kubernetes 1.33.7 | J | Enough headroom that pods never wait for a node: 57% of requested CPU still free with the tested service at 5 replicas (Part 05). |
| Images | Same `:latest` images for every run (`imagePullPolicy: Always`); open-loop code delivered by a ConfigMap overlay | J | ACR Tasks unavailable in Indonesia Central; identical images avoid dependency drift. Code inside the running pods verified file by file against git before the campaign (Part 08 §8.13). |

### C. Pods

| Setting | Value | Src | Reason and evidence |
|---|---|---|---|
| CPU request | 250m (both services) | M/F | With 100m, H1's 70% target fired at 70m of real CPU, making CPU-based HPA unfairly eager; raised on 2026-04-13/14 after live tests (Part 01 #2, Part 02). CPU utilization is measured against the request (Kubernetes resource docs). |
| CPU limit, memory | 500m; auth 128/256 Mi, shipping 256/512 Mi | J | Resource budget (Part 05). |
| Probes | readiness `/ready` every 15 s, 6 misses; shipping liveness `/health` every 60 s, 10 misses | J | Lenient, so a busy pod is not taken out of service or restarted by its own probes; probe and back-off problems were fixed after the first shipping sweep (Part 02, 2026-04-18→21). |

### D. Autoscaler configurations

| Setting | Value | Src | Reason and evidence |
|---|---|---|---|
| B1 | 1 fixed replica | J | Lower bound; must be clearly overloaded (gate G4). |
| B2 | 5 fixed replicas | J/F | Upper bound = the autoscalers' ceiling at full cost; must be healthy (G4). |
| Replica range | min 1, max 5 for H1/H2/H3/K1 | F | Same start and ceiling for every autoscaler (Part 04). |
| H1 target | CPU 80% (thesis dataset, from 2026-10-06; commit `dddd996`) | D | Kubernetes' own default target: the API reference states that an HPA without metrics gets 80% average CPU utilization (§11.9). Verified on the campaign cluster (v1.33.7) on 2026-10-06: a server-side dry run of an HPA with no metric came back with `averageUtilization: 80` and `minReplicas: 1`. So H1 is HPA with Kubernetes defaults throughout. The closed-loop background campaign ran H1 at 70%. See §11.6 #1. |
| H1 behavior | none set → Kubernetes defaults | D | Scale-up: no stabilization, the larger of +100% or +4 pods per 15 s; scale-down: 300 s stabilization, up to 100% per 15 s (Kubernetes HPA docs). |
| H2 | CPU 50%; scale-up 0 s window, +5 pods/15 s; scale-down 30 s window, 100%/15 s | J/F | "Best-case CPU HPA": lower target leaves headroom, fastest allowed reaction. The same behavior block is reused by H3 and K1 so behavior never differs between them. |
| H3 | Request rate per pod via prometheus-adapter, `rate(http_requests_total[1m])`, AverageValue 5 (auth) / 15 (shipping) | F/M | Same metric, data source, window and threshold as K1, so H3 vs K1 differs only in the engine (Part 06). |
| K1 | KEDA Prometheus trigger, `sum(rate(http_requests_total{job=…}[1m]))`, threshold 5 / 15; polling 15 s; cooldown 30 s; same behavior block as H2 | F | Polling matches the HPA's 15 s loop; cooldown matches H2/H3's 30 s scale-down window. KEDA's own defaults are 30 s / 300 s (KEDA docs). |
| HPA loop, tolerance | 15 s, 10% | D | kube-controller-manager defaults (Kubernetes HPA docs). |
| H3/K1 thresholds | 5 req/s (auth), 15 req/s (shipping) per pod | M | Documented calibration procedure (Part 06): measure the per-pod rate Prometheus actually observes; set the threshold where scale-out should begin; same value for H3 and K1. Shipping: one pod saw 13.3 req/s at warm-up and 16.6 at peak, so 15 fires near capacity but stays quiet at warm-up (Part 03, 2026-04-17). Auth: the earlier threshold of 50 was never reached; set to 5 (2026-04-13/14). Kept unchanged for open loop — §11.6 #2. |
| Rate window | 1 minute, shared by H3 and K1 | F | A 30 s auth-only window was tried and reverted on 2026-08-15 (`cf466b4`) to keep one shared window. |

### E. Metrics pipeline

| Setting | Value | Src | Reason and evidence |
|---|---|---|---|
| Prometheus scrape interval | 15 s | J | Prometheus' own default is 1 minute; 15 s matches the 15 s HPA loop so each decision sees fresh data. |
| Request counter | `http_requests_total` from the service's instrumentation = requests the service served | J | Same meaning in both datasets. Load-shedding rejections are not counted because the limiter sits outside the instrumentation (Part 08 §8.10). |
| Adapter rule, KEDA query | 1-minute rate in both | F | Identical data for H3 and K1. |
| CPU metric for H1/H2 (kubelet → metrics-server) | AKS-managed, left unchanged; on this cluster the HPA's CPU reading changed about once a minute | D/M | Measured 2026-10-09: median 61.4 s between changes over the 60 H1/H2 campaign runs (82% of gaps 50–70 s), while the HPA evaluates every 15 s. A property of the platform, reported as such: it is the lag behind finding #23 (Part 08 §8.13). |

### F. Load generation

| Setting | Value | Src | Reason and evidence |
|---|---|---|---|
| Tool | k6 0.46.0, pinned for both services | J | The closed-loop jobs used different k6 images; pinning one version makes the generator identical (Part 08 §8.3). |
| Model (campaign) | Open loop: `ramping-arrival-rate` | J | Real users do not wait for each other; a closed-loop generator slows down when the server slows down and hides overload (Schroeder et al. 2006). Measured: closed-loop B1 served only 25.2–25.4 req/s on shipping against B2's 112.4–112.7 (Part 08). The offered load is identical for every config. |
| Model (closed-loop dataset) | `ramping-vus`; auth 1→12 VUs, shipping 10→80 VUs | M | Ladders: shipping PEAK_VUS 80 had 0% errors, CPU not yet throttled, and the largest B1/B2 contrast without errors or throttling (Part 03); auth PEAK_VUS 12 from its own ladder (Part 02, 2026-08-15; harness `32f253d`). |
| Rate-setting rules | C = highest rate one pod sustains with p95 ≤ SLO and < 1% errors; base below the H3/K1 threshold so every autoscaler starts at 1 replica; peak ≈ 70–80% of B2's healthy ceiling and ≥ 2.5 × C | J | Written in the pilot brief before any open-loop data (Part 08 §8.2). |
| Auth rates | base 2, peak 30 req/s | M | At 4 req/s one pod's CPU reached 147 m (59% of request) and H2 would scale during warm-up; at 2 req/s it was 78–83 m (31–33%). Peak 30 = 75% of the v1 B2 ceiling (40) and ≥ 2.5 × C (25); B2 was healthy at 30 in both calibrations (p95 853 / 787 ms), while 40 failed in v2 (1765 ms); the user kept 30 (Part 08 §8.5, §8.11). |
| Shipping rates | base 10, peak 105 req/s | M | Base: 54 m CPU (22%), below the 15 req/s threshold. Peak: 75% of B2's healthy ceiling of 140. The ≥ 2.5 × C rule (125) was relaxed because B1 already fails completely from 60 req/s; user decision "pick the best path" (Part 08 §8.5). |
| SLOs | auth 1500 ms, shipping 1200 ms | M | Rule from the brief: propose from B2 latencies. Auth ≈ closed-loop B2 spike p95 (1452 ms); shipping ≈ 1.3 × closed-loop B2 p95 (917 ms). |
| Request timeout | 5 s | J | From the pilot brief: a request slower than 5 s counts as failed (k6's own default is 60 s). |
| VUs | ⌈1.5 × peak × 5 s⌉ = 225 / 788 | J/M | Little's law: concurrent requests = arrival rate × time in system, with the timeout as the worst case, plus 50% margin. Result: 0 dropped requests in every run. |
| Connection reuse | off (`noConnectionReuse`) | M | With keep-alive, traffic stayed pinned to the first pod: 20 of 20 autoscaled shipping spike runs had one busy pod and idle others (finding #12). |
| Request mix | auth: 70% `GET /auth/me`, 30% `POST /auth/login`, 120 users; shipping: quote with 1–4 items, 200–2,500 g, 3 zones, 35% express | J | Weighted, realistic mix; identical to the closed-loop jobs (Part 10 BAB 3 outline). |
| Pre-login | 120 auth users logged in during the reset | M | Logging in inside the run scaled H2 before the spike (finding #21). |
| Stage shapes | 2 min base; gradual 5 min ramp + 2 min hold; spike 10 s jump + 6 min 50 s hold; oscillating 80 s peaks and bases with 10 s transitions; 3 min ramp-down; 12 min total | J | Three archetypes — steady growth, sudden burst, periodic load (Part 06); identical in both datasets. |

### G. Load shedding (open-loop campaign only)

| Setting | Value | Src | Reason and evidence |
|---|---|---|---|
| Mechanism | Per-pod cap on requests in flight; the excess gets an immediate 503; outermost middleware; `/metrics`, `/health`, `/ready` exempt | M | Without it, one pod collapsed under open-loop overload and its request-rate metric went blank, so H3/K1 never scaled (finding #19). Standard overload practice (Beyer et al. 2016, ch. 21–22). |
| Cap | ⌈C × p99 at C⌉ → auth 10 × 2.15 s → 22; shipping 50 × 0.957 s → 48 | M | Little's law: requests in flight at the point where errors start. Verified on the v2 ladders: no shedding at or below C, shipping graceful up to 105 req/s (Part 08 §8.11). |
| Placement | Outermost | M | Placed inside the other middleware it still collapsed at 105 req/s (goodput 7.50 req/s, 77.16% timeouts) (Part 08 §8.10). |

### H. Measurement and KPIs

| Setting | Value | Src | Reason and evidence |
|---|---|---|---|
| KPI window | k6 time 120–540 s | J/P | Excludes the warm-up and the ramp-down; covers the whole load phase of every pattern. |
| Latency | End-to-end including connection setup | J | With connection reuse off, every request connects; that is part of what a user waits for. |
| Failed requests | Counted as infinite latency | J | Conservative: a failed request can never count as fast. |
| Seconds over SLO | Number of 10 s bins whose p95 exceeds the SLO, × 10 | J/P | p95 as the tail-latency measure (Dean & Barroso 2013; SLOs: Beyer et al. 2016, ch. 4). |
| Error % | Includes 503 rejections and timeouts | J | Every request the user did not get answered in time is an error. |

### I. Run protocol

| Setting | Value | Src | Reason and evidence |
|---|---|---|---|
| Between runs | Remove autoscalers, back to 1 pod, delete k6 jobs, pre-login (auth), wait 120 s; apply config, wait 90 s; `/ready` check; after k6 wait 180 s, then export | J | Same waits as the closed-loop campaign (`RESET_WAIT`, `STABILIZE_WAIT`, `EXPORT_WAIT` in `run-experiment.sh`): equal start state, a metric baseline, and the scale-down captured. |

### J. Decision rules

| Rule | Value | Src | Reason and evidence |
|---|---|---|---|
| Pilot criteria 1–5 | incl. reps within ±25% "or explained by autoscaler poll phase" | P | From the user's pilot brief, set before the pilot ran (Part 08 §8.2). |
| Gate G1–G5 | G1: attempted = offered within 2%, 0 dropped, all scheduled requests sent; G4: B1 ≥ 210 s over SLO (half the 420 s window) or errors ≥ B2's max + 5 points, B2 < 1% errors and p95 ≤ SLO; G5: no pod below 20% of the mean share | P | Fixed 2026-10-06 ≈05:46 UTC, before any v2 data (Part 08 §8.9). The 20% floor comes from the pilot brief. |
| G6 rule v1 | 25% of the mean, or ≤ 20 s / ≤ 1 point | P | 25% from the brief; 20 s = two 10 s bins; the 1-point floor was not derived. Judged the smoke test (FAIL, `gate-v1.json`). |
| G6 rule v2 | 50% of the mean, or ≤ 30 s / ≤ 2 points | P | Chosen by the user after the smoke and before campaign data; committed in `6ef8f89` at 12:13:17 UTC and pushed before the campaign started at 12:33:42 UTC. Reason: one 15 s autoscaler cycle, the normal gap between reps (6 of 8 pairs), produced gaps up to 27%, 30 s and 1.93 points (Part 08 §8.9). Pre-registration practice: Nosek et al. (2018). |

## 11.3 Validity, type by type

| Validity type | The question | How this study answers it | Evidence |
|---|---|---|---|
| **Construct** | Do the configs and KPIs measure what they claim? | Configs are defined by their manifests, and every run saves the objects actually deployed (`hpa-status.yaml`, `keda-status.yaml`, HPA timeline). KPIs were defined before the data. | Run folders; Parts 06, 08 |
| **Internal** | Is a difference caused by the config and not something else? | Fairness controls (§11.4); identical offered load; reset to 1 pod; shuffled order; one service at a time; G2 checks the start state and G5 the load spread in every run. | Gate results |
| **Manipulation check** | Is the load in the range where autoscaling matters? | G4 requires B1 overloaded and B2 healthy in every service × pattern. Closed-loop measured B1/B2 p95 ratios: 2.72–3.62× (Part 03). | Gate G4; Part 03 |
| **Measurement** | Did the instruments measure correctly? | G1 (no dropped requests, offered = attempted), k6 resource headroom, checksums, and agreement between independent sources (§11.7). | Validator output |
| **Statistical conclusion** | Are the differences larger than run-to-run noise? | 5 reps, spread reported; exact Mann–Whitney tests with A12 effect sizes and Holm correction, fixed before reps 3–5 (Part 12 §12.4; Arcuri & Briand 2011); after the G6 FAIL, repeatability is measured as an outcome (A4). | Phase 4 analysis |
| **External** | How far do the results generalize? | Stated limitations: one cluster size, two synthetic services, fixed thresholds, max 5 replicas, 12-minute runs, a simulated carrier delay, load shedding in the open-loop variant. | BAB 5 limitations |

## 11.4 Fairness controls — what is held equal, and why

- Same replica range (1–5) for every autoscaler; B2 equals the shared ceiling.
- H2, H3 and K1 share one scaling-behavior block, so differences between them come from the metric or the engine.
- H3 and K1 share the threshold, the Prometheus data source and the 1-minute window; KEDA polls on the HPA's 15 s rhythm and
  its cooldown equals the 30 s scale-down window.
- Same pod resources, probes, images and code for every config of a service.
- Same offered load: the open-loop schedule is identical for every config of a service and pattern.
- Same start: every run begins from 1 pod after the same reset; G2 verifies it.
- Connection reuse off, so new pods receive traffic; G5 verifies the spread.

## 11.5 Judgment calls — role, alternatives, consequence

| Choice | Role | Alternatives | Why this one | What depends on it |
|---|---|---|---|---|
| H2 at 50% + fast behavior | Best-case CPU HPA | Other targets, slower policies | Lower target leaves headroom; fastest documented policy; identical behavior to H3/K1 | The H2-vs-H3 contrast compares "CPU at 50%" with "request rate at the calibrated threshold" (§11.6 #2) |
| Max 5 replicas | Shared ceiling | Higher | Fits the cluster with headroom; equal for all | B2's cost; ceiling effects at peak |
| Three patterns | Load coverage | Others (e.g. diurnal) | Growth, burst and periodic load are the classic cases | Generality of the conclusions |
| 5 s timeout | Failure bound | k6's 60 s default | A user-facing bound | Error % includes timeouts |
| 5 repetitions | Precision | 3 or 10 | ≈60 h per open-loop campaign (estimate; actual ≈61.6 h) | Test power: with 5 vs 5 the smallest two-sided p is 0.0079, so only complete or near-complete separation is significant (Part 12 §12.4) |
| Gate tolerances | Stop rule | — | Derived from the control-loop timing (rule v2) | Only whether the campaign continues, not the reported numbers |

## 11.6 Known weak spots and how they are handled

1. **H1's description — resolved.** Part 06 called H1 (70%) "the most common production config" without a source,
   and Kubernetes' actual default target is 80%. **Handling (user decision, 2026-10-06):** H1 now uses 80%, so it is
   HPA with Kubernetes defaults throughout (`dddd996`). This was possible without a second explanation because the
   thesis uses the open-loop campaign as its only results dataset ("Replace", Part 08 §8.14); the closed-loop campaign
   (H1 at 70%) appears only as methodology background. The two H1 runs already done at 70% are archived and re-run
   at 80% before the gate (Part 08 §8.13). No conclusion about metric or engine rests on H1 in any case.
2. **Thresholds not re-calibrated for the open-loop campaign.** Auth's 5 req/s per pod was set on 2026-04-13 while
   auth still used an open-loop arrival-rate profile (a saturated pod showed only about 9–12 req/s, so the earlier 50
   could never be reached); shipping's 15 was set on 2026-04-17 with the closed-loop generator. The pilot brief kept
   thresholds fixed and calibrated the load around them instead. **Why not re-calibrate now:** the original rule —
   fire near one pod's capacity — would put shipping's threshold near 45 req/s, above the ≈43 req/s an overloaded,
   load-shedding pod still serves (the metric counts served requests), so H3/K1 could stop scaling exactly when needed;
   and the thresholds were fixed before any campaign data, while H3/K1 runs had already run. **Handling:** the
   calibration intent still holds.
   - Quiet at base: 2 < 5 and 10 < 15 req/s; G2 found exactly 1 Ready pod at scenario start and at onset in all 120
     autoscaled campaign runs (checked 2026-10-09) and in the 8 autoscaled smoke runs. In the closed-loop dataset, auth's
     base load (11.6–15.9 req/s) was above 5, so open loop meets this intent better.
   - Crossed before a pod saturates: 5 is 62.5% of one auth pod's capacity (8 req/s) and 15 is 30% of one shipping pod's
     (50 req/s).
   - Identical for H3 and K1, so the engine comparison is unaffected.
   - Re-tuning after seeing open-loop data would be a post-hoc choice.
   - Future work: an open-loop-native calibration, e.g. setting each request-rate threshold where H2's 50% CPU target
     fires, would compare how fast each metric reacts at equal trigger points.

   **Disclose:** the H2-vs-H3 contrast compares the configs as defined. H2's 50% CPU target corresponds to roughly
   3.3 req/s per auth pod and 23 req/s per shipping pod (estimates, linear from the measured base-load CPU), so CPU is
   the earlier trigger on auth and request rate the earlier one on shipping. During a spike the CPU reading itself lags
   (shipping H2 first scaled at +79 s in the smoke), so timing differences are not only about target levels.
3. **Load shedding changes the system under test** (open-loop campaign only). **Handling:** report it as part of the
   system under test; it is standard practice; the same rule and cap derivation apply to both services and every
   config; the closed-loop dataset runs without it.
4. **The G6 rule was changed after the smoke.** **Handling:** the smoke stays a FAIL (`gate-v1.json`); rule v2 was fixed
   and committed before any campaign data, with measured reasons (Part 08 §8.9).
5. **Cluster vs repository drift:** an unused 30 s auth rule remains in the live prometheus-adapter config (reverted in
   the repository on 2026-08-15). Nothing references it, and it was present in every dataset (Part 08 §8.13).
6. **The campaign continued after its pre-registered gate failed** (2026-10-07). **Handling:** the FAIL stays on
   record; the reasons are documented (G1–G4 passed everywhere; the G5/G6 failures trace to the HPA's lagging CPU
   reading, a property of the system); repeatability became a measured outcome; the analysis plan was fixed and pushed
   before any rep 3–5 data; nothing else changed (Part 12).

## 11.7 Is it real? Authenticity and reproducibility evidence

No study can prove absolutely that nothing was invented. What examiners accept is **traceability, agreement between
independent sources, reproducibility, and timestamps the author does not control.**

1. **Raw data, not only summaries.** Each run stores every request (time, latency, status) — 54,274 per shipping spike
   run — plus Prometheus exports, Kubernetes events, pod and HPA timelines, the k6 log and metadata: about 26 files per
   run, public on GitHub with the scripts that produce every table. Re-analysis reproduces the recorded results: on
   2026-10-06 all 20 pilot runs re-analysed from raw data gave 0 differences from the stored gate results.
2. **Independent sources agree.** Requests k6 saw succeed (client side) compared with requests the service itself
   counted (server side, Prometheus), shipping spike runs:

   | Shipping spike runs | k6 successes vs service's own count |
   |---|---|
   | Pilot B2, reps 1 and 2 | 54,274 vs 54,235 (−0.07%) and 54,274 vs 54,224 (−0.09%) |
   | Pilot B1 and H2, 4 runs | −2.21% to +2.75% |
   | Smoke B1 and the six autoscaled runs (H2, H3, K1 × 2) | −1.65% to +0.19% |
   | Pilot H3 and K1, 4 runs (pod collapsed, metric blank) | −27.96% to +14.63% |

   The large gaps occur only in the pilot's H3 and K1 runs, where the overloaded pod's metrics went blank (finding
   #19). The two auth smoke runs were not part of this check.
3. **Integrity checks.** Checksums are computed inside the k6 pod at capture and verified after transfer; the code hash
   is recorded in every pod and run; image digests and dates come from ACR.
4. **Timestamps the author cannot edit.** Azure Activity Log (every AKS start and stop), Azure billing (AKS hours),
   GitHub push records, ACR image dates.
5. **Decisions before data, failures included.** Rules are committed before the data they judge, and the record keeps
   the failures: the pilot's ambiguous verdict, the smoke FAIL, two analysis-tool bugs (Part 08 §8.9, §8.12).
6. **Anyone can re-run it.** Manifests, scripts and configs are in the repository; one run takes about 20 minutes and
   about $0.17 of AKS (estimate).

**Done (2026-10-09):** the Azure Activity Log of both thesis resource groups (12 July → 9 October; the earliest event
kept is from 15 August) and the daily billed cost of those resource groups were exported to a private folder outside
the repository, with a README listing the files and their SHA-256:
- `activity-log_ecommerce_2026-07-12_to_2026-10-09.json` — `e092e2e8fe81794514b48a65b62b096c81441004800c82cb52546246982a0b95`
- `activity-log_MC_ecommerce_ecommerce-aks_indonesiacentral_2026-07-12_to_2026-10-09.json` — `455134f2b1d05cd92cf7b5c0a5a34b63432ec9525264b78bc31c2b97992f630e`
- `cost-daily_thesis-resource-groups_2026-07-12_to_2026-10-09.json` — `3b3cdb763f6ef1c4f5446346c7c22541b95503ef3dbfd65622f8d9ca4828c6a6`

Azure's record holds every AKS start and stop of both campaigns: closed loop, start 15 August 03:55:43 and stop
17 August 22:34:35 UTC; open loop, four start/stop pairs from 5 October 14:53:04 to 9 October 02:50:36 UTC. The dataset
is tagged `openloop-dataset-v1` (an annotated tag on `c1e72e2`, pushed 2026-10-09 09:20 UTC).

The repository cleanup that the DOI waits for is done (2026-10-09): CI is green on every service (run 37928949340), the
repository has a README that leads with the results, and it was renamed `k8s-autoscaling-hpa-vs-keda` (the old
`e-commerce` URL redirects; commit SHAs and the tag are unchanged).

**Archived with a DOI (2026-10-09).** Release `v1.0.0` (an annotated tag on `01aff4e`, CI green, published 12:33:22
UTC) was archived by Zenodo's GitHub integration as a 1.189 GB zip, MD5 `e65f3b2128eb6ee92ead1a3c9bf50895`, with the
metadata from `CITATION.cff`:
- **version DOI 10.5281/zenodo.23263355**, the exact snapshot to cite in the thesis;
- concept DOI 10.5281/zenodo.23263354, which always resolves to the latest version.

The data in the release is identical to the dataset tag `openloop-dataset-v1`; only CI, the README, the citation file
and these notes changed in between.

**Still to do:** a "research data and reproducibility" section in BAB 3 or an appendix that cites the version DOI.

## 11.8 Ready answers to common questions

| Question | Short answer | Detail |
|---|---|---|
| Why is H1 80%? | It is Kubernetes' own default target, and H1 also keeps Kubernetes' default scaling behavior: H1 is HPA "out of the box". (The closed-loop background campaign used 70%; it was corrected for the thesis dataset.) | §11.2 D, §11.6 #1 |
| Why is H2 50% with fast scaling? | It is the best case for CPU scaling: more headroom and the fastest allowed reaction. H3 and K1 use exactly the same behavior. | §11.2 D |
| Why 5 and 15 req/s per pod? | Calibrated per service by a documented procedure: quiet at base load, crossed before a pod saturates, identical for H3 and K1. | §11.2 D, §11.6 #2 |
| Why do H3 and K1 share the threshold? | So the only difference between them is the engine (HPA vs KEDA). | §11.4 |
| Why max 5 replicas, and B2 = 5? | One ceiling for every config; B2 shows the best performance at the highest cost; 5 fits the cluster with headroom. | §11.2 B, D |
| Why these three patterns? | Steady growth, a sudden burst and periodic load are the classic cases for reactive autoscaling. | §11.2 F |
| Why open loop, and what about the closed-loop campaign? | Open loop keeps the offered load fixed and exposes overload (Schroeder et al. 2006). The earlier closed-loop campaign showed that its generator slowed down with the server and hid overload — that is why the thesis switched. It is methodology background, not a second set of results. | Part 08 §8.14 |
| Why a 5 s timeout and p95? | 5 s bounds what a user waits for; p95 captures the slow tail that averages hide. | §11.2 F, H |
| Why 5 repetitions in shuffled order? | To measure run-to-run spread and to stop time effects from lining up with one config. | §11.2 A |
| Isn't load shedding changing the system? | Yes, and it is reported as part of the system under test: it is standard overload protection, applied identically to every config. Without it the pilot showed pods collapsing and metrics going blank. | §11.6 #3 |
| Why did the gate rule change? | The smoke showed the original error allowance was smaller than one autoscaler cycle's effect. The new rule was fixed and committed before any campaign data; the smoke stays a FAIL. | §11.2 J, §11.6 #4 |
| How do we know the results are real? | Raw data for every request, independent sources that agree, checksums, third-party timestamps, rules fixed before data, and anyone can re-run it. | §11.7 |
| Why did you continue after the gate failed? | The checks that test the measurement (G1–G4) passed in every run. What failed was repeatability of CPU-based HPA, and the HPA timelines show why: its CPU reading lags the load, so its outcome depends on timing. That is a real property of the system, so we measured it with the full 5 repetitions instead of stopping — documented, with the analysis plan fixed before the new runs. | §11.6 #6, Part 12 |
| Is the comparison fair? | Within a service and pattern, yes: the same load, pods, start, limits and shuffled order, checked in every run. H3 vs K1 isolates the engine, H2 vs H3 the metric (each at its own target). Across services, compare relative outcomes, not raw numbers. | §11.10 |

## 11.9 Sources worth citing

Check edition, volume and page details against the original before citing.

| Source | Supports | Used for |
|---|---|---|
| Kubernetes documentation, "Horizontal Pod Autoscaling" (kubernetes.io) | Scaling algorithm, 15 s loop, 10% tolerance, default scaling behavior, stabilization windows | H1–H3 definitions; §11.2 D |
| Kubernetes documentation, "HorizontalPodAutoscaler Walkthrough" | Example CPU target of 50% | H1/H2 target discussion |
| Kubernetes API reference, "HorizontalPodAutoscaler" (autoscaling/v2), field `spec.metrics`: "If not set, the default metric will be set to 80% average CPU utilization." (kubernetes.io/docs/reference/kubernetes-api/workload-resources/horizontal-pod-autoscaler-v2/) | The 80% default CPU target | H1 = 80% |
| `kubectl autoscale` reference: with no target given, "a default autoscaling policy will be used" (the API default above); the current flag is `--cpu` (older releases: `--cpu-percent`) | kubectl applies the same default | H1 = 80% |
| Kubernetes "HorizontalPodAutoscaler Walkthrough": `kubectl autoscale deployment php-apache --cpu=50% --min=1 --max=10` | 50% is an example value, not the default | H1 vs H2 discussion |
| Kubernetes documentation, "Resource Management for Pods and Containers" | CPU utilization is relative to the request | CPU-request fairness fix |
| KEDA documentation: ScaledObject specification; Prometheus scaler (keda.sh) | `pollingInterval`, `cooldownPeriod` and their defaults; threshold semantics; HPA behavior pass-through | K1 definition |
| prometheus-adapter documentation (github.com/kubernetes-sigs/prometheus-adapter) | Custom Metrics API, rule configuration | H3 metric pipeline |
| Prometheus documentation: configuration; `rate()` | Default 1-minute scrape interval; per-second rate over a window | Scrape interval; 1-minute window |
| Grafana k6 documentation: open and closed models; `ramping-arrival-rate`; dropped iterations; `noConnectionReuse`; HTTP params | Generator model, executor semantics, VU pre-allocation, timeout default | §11.2 F |
| Schroeder, B., Wierman, A., & Harchol-Balter, M. (2006). Open versus closed: A cautionary tale. *NSDI '06*. | Why the generator model changes results | Open-loop decision |
| Little, J. D. C. (1961). A proof for the queuing formula L = λW. *Operations Research*, 9(3). | Concurrency = rate × time in system | VU sizing; load-shedding caps |
| Beyer, B., Jones, C., Petoff, J., & Murphy, N. R. (Eds.) (2016). *Site Reliability Engineering*. O'Reilly. Ch. 4 (SLOs), ch. 21 (Handling Overload), ch. 22 (Cascading Failures). | SLO concept; load shedding | SLO KPI; admission control |
| Dean, J., & Barroso, L. A. (2013). The tail at scale. *Communications of the ACM*, 56(2). | Why tail latency (p95/p99) matters | p95 KPI |
| Herbst, N. R., Kounev, S., & Reussner, R. (2013). Elasticity in cloud computing: What it is, and what it is not. *ICAC '13*. | Defining and measuring elasticity (under/over-provisioning) | Framing autoscaler KPIs |
| Jain, R. (1991). *The Art of Computer Systems Performance Analysis*. Wiley. | Factorial design, replication, randomization | §11.2 A |
| Papadopoulos, A. V., et al. Methodological principles for reproducible performance evaluation in cloud computing. *IEEE Transactions on Software Engineering*. | Repetitions, reporting variability, publishing data and code | §11.2 A, §11.7 |
| Arcuri, A., & Briand, L. (2011). A practical guide for using statistical tests to assess randomized algorithms in software engineering. *ICSE '11*. | Non-parametric tests, effect sizes, number of repetitions | Phase 4 analysis |
| Mann, H. B., & Whitney, D. R. (1947). On a test of whether one of two random variables is stochastically larger than the other. *Annals of Mathematical Statistics*, 18(1). *(added 2026-10-09)* | Rank-sum test for two independent samples | Part 12 A2 |
| Holm, S. (1979). A simple sequentially rejective multiple test procedure. *Scandinavian Journal of Statistics*, 6(2). *(added 2026-10-09)* | Multiple-comparison correction | Part 12 A2 (3 contrasts per family) |
| Vargha, A., & Delaney, H. D. (2000). A critique and improvement of the CL common language effect size statistics of McGraw and Wong. *Journal of Educational and Behavioral Statistics*, 25(2). *(added 2026-10-09)* | The A12 effect size | Part 12 A2 |
| Nosek, B. A., Ebersole, C. R., DeHaven, A. C., & Mellor, D. T. (2018). The preregistration revolution. *PNAS*, 115(11). | Fixing analysis rules before seeing data | Gate rules |
| Wilkinson, M. D., et al. (2016). The FAIR guiding principles for scientific data management and stewardship. *Scientific Data*, 3. | Findable, accessible, reusable research data | Data archive and DOI |
| Wijaya, I. K. (2026). *Kubernetes autoscaling: HPA vs KEDA, CPU vs request rate* (Version 1.0.0) [Software]. Zenodo. https://doi.org/10.5281/zenodo.23263355 *(added 2026-10-09)* | The archived data, code and analysis of this thesis | BAB 3 reproducibility section; data availability statement |

## 11.10 Is the comparison fair? (added 2026-10-07)

A comparison is fair when the conditions being compared differ only in the factor under study, everything else is
held equal or randomized, and the outcome is measured the same way.

**The main comparison — the six configurations within one service and one pattern — is fair:**

| Held equal | How | Checked by |
|---|---|---|
| Offered load | Open loop: the identical arrival schedule for every config of a service × pattern (e.g. 54,274 requests for shipping spike), whatever the server does | G1: attempted = offered within 2%, 0 dropped |
| Pods | Same image, code overlay, CPU/memory, probes and load-shedding cap for every config. B1 and B2 manifests differ only in the replica count (1 vs 5); autoscaled configs deploy the B1 manifest plus their autoscaler | Overlay hash and cap recorded in every run's metadata |
| Start state | Every run starts from 1 pod after the same reset; auth users are logged in before the run | G2 |
| Scaling limits | min 1 / max 5 for every autoscaler; B2 = the same 5 pods, permanently | Manifests |
| Scaling behavior | H2, H3 and K1 share one behavior block | Manifests |
| H3 vs K1 metric | Same Prometheus counter, same 1-minute window, same threshold; same HPA controller makes the final decision | Manifests |
| Traffic spread | Connection reuse off, so new pods receive traffic | G5 |
| Measurement | Same KPIs, KPI window (120–540 s) and SLO per service | Validator |
| Time and order | Order shuffled within each rep block; 5 reps; drift spreads across configs instead of hitting one | Frozen plan |
| Environment | Same cluster, nodes and monitoring; one service autoscaled at a time | Pre-launch check |

**What each contrast isolates:**
- **H3 vs K1 → engine only** (HPA + prometheus-adapter vs KEDA): the cleanest contrast in the design.
- **H2 vs H3 → metric** (CPU vs request rate), each at its own target (see caveat 1).
- **H1 vs H2 → default vs tuned HPA**: a package — target (80% vs 50%) and behavior both differ, by design.
- **B1 and B2 → the bounds.** G4 confirms the load sits between them (B1 overloaded, B2 healthy), so the
  autoscalers have room to differ.

**What is not compared directly, and why that is still fair:**
- **Across services**, the workload type differs on purpose, so the loads (2→30 vs 10→105 req/s), SLOs, thresholds and
  caps differ too. Each service was calibrated by the same rules (one-pod capacity C, B2's healthy ceiling, base below
  the threshold, peak rule; §11.2 F). Compare **normalized** outcomes — the share of the B1→B2 gap each config closes,
  rankings, and the direction of the metric and engine effects — not raw latency or error counts.
- **Across patterns**, the shapes and volumes differ (auth: 10,359–15,399 requests per run). Compare configs within a
  pattern; across patterns, use the same normalized measures.

**Caveats to disclose:**
1. **Different trigger levels.** H2's 50% CPU target corresponds to roughly 3.3 req/s per auth pod and 23 per shipping
   pod (estimates), against request-rate thresholds of 5 and 15. The "metric effect" is therefore each metric at its
   calibrated or standard target, not at an equalized trigger point (§11.6 #2).
2. **H1 vs H2 differs in two things** (target and behavior); report it as default vs tuned, not as a single factor.
3. **Load shedding is part of the system.** It applies to every config, but it caps what a request-rate metric can see
   (it counts served requests), which is a property of H3 and K1 under overload (§11.6 #3).
4. **Two H1 runs ran outside their shuffled position** (re-run at 80% after position 72; Part 08 §8.13).
5. **Five repetitions detect only large differences.** Report effect sizes and spread with every test (Arcuri & Briand
   2011).

**Short answer for the supervisor:** "Within each service and load pattern, the six configurations are compared under
identical conditions: the same offered load, the same pods, the same starting state, the same limits, and runs in
shuffled order, with checks in every run confirming it. H3 versus K1 isolates the engine and H2 versus H3 the metric,
each metric at its own calibrated target. The two services are calibrated by the same rules but run different loads by
design, so across services we compare relative outcomes such as the share of the B1-to-B2 gap closed, not raw
latencies."
