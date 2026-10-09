# Thesis Blueprint — Part 09: Stand-Out Strategy, Timeline Plan and Final Assessment (§9–§11)

> Part of the thesis blueprint — index and executive summary: [thesis_blueprint.md](../thesis_blueprint.md).
> Sections moved verbatim from the single-file blueprint on 2026-10-06; original section numbers (§N) and finding numbers (#N) are kept so every cross-reference still resolves. Later additions are marked with their date.

---

## 9. Make-It-Stand-Out Strategy

### Strategy 1: The "Metric-Workload Fit" Narrative + Controlled Proof

Frame the entire thesis around one central story:

> "CPU-based autoscaling is Kubernetes' default, and the usual assumption is that request-rate signals fix its weaknesses on non-CPU workloads. Using a controlled factorial design that separates metric-type effects from engine effects, this thesis shows that the answer is conditional: on a CPU-bound control neither factor matters; on a wait-dominant service both matter only under spike load (request rate ~10%, KEDA a further ~5% with far lower variance); and one workload × load-pattern condition — a wait-dominant service under oscillating load — defeats every configuration tested."

This narrative is more nuanced and academically stronger than simply "KEDA beats HPA." The thesis structure becomes:

1. **BAB 1:** There's a problem — CPU-based HPA doesn't work for all service types
2. **BAB 2:** Literature confirms this limitation but few studies isolate WHY (metric? engine? both?)
3. **BAB 3:** We design a controlled factorial experiment that isolates the variables
4. **BAB 4:** Results quantify when metric type and engine architecture contribute — and show the conditions where neither does
5. **BAB 5:** Practitioners need not switch metric or engine for CPU-bound or gradually varying load; request rate (and KEDA) pay off under spiky load on wait-dominant services; fast oscillation on a wait-dominant service is a limitation none of the tested configurations solves

The H3 config is what makes this narrative possible. Without it, you can only say "KEDA is better." With it, you can say "here's exactly WHY and WHICH FACTOR contributes HOW MUCH."

### Strategy 2: Cost-Performance Pareto Analysis

For every configuration, compute the resource cost index. Then plot:

```
X-axis: Resource Cost Index ($)
Y-axis: p95 Latency (ms)

Each point = one configuration (average of 5 runs)
Color = method (blue=HPA-CPU, orange=HPA-RPS, green=KEDA, gray=baseline)
Shape = load pattern (circle=gradual, triangle=spike, square=oscillating)
```

Draw the **Pareto frontier**: configurations where no other config is both cheaper AND faster. With 6 configs × 3 load patterns = 18 data points per service, the Pareto plot will clearly show clusters:
- Shipping-rate-service (post-fix 180-run data): on **gradual** all four autoscalers collapse onto the B2 floor (916–920 ms) — a single Pareto cluster where only cost separates them; on **spike** a genuine frontier emerges (K1 941 ms < H3 987 < H2 993 < H1 1101, all ≈3× better than B1 3324); on **oscillating** every config is dominated, sitting at 2656–3096 ms against a 916 ms floor — plot these as a failure cluster, not a frontier
- Auth-service: every autoscaler is within ~3% of B2 on **all three** patterns except K1 oscillating (+9.2%) (gradual 1132–1164 ms, spike 1462–1496, oscillating 1160–1260), so the Pareto plot is a tight cluster per pattern with K1 oscillating as the one outlier — CPU-based HPA is fully competitive on the CPU-bound control, as predicted. The earlier contamination caveat no longer applies: after the ramping-vus migration every auth run is 0.00% error (finding #16)
- Product-service can be shown separately as an exploratory contrast where downstream DB saturation can distort or even reverse apparent app-tier autoscaling gains

This is academically impressive (multi-objective optimization vocabulary) and practically useful (a decision-maker can pick their cost-performance preference).

### Strategy 3: Annotated Scaling Timeline Visualization

For the most interesting runs, create synchronized multi-panel time-series showing ALL 4 autoscaling methods on the same chart. On the post-fix data the two best candidate figures are **shipping-rate-service spike** (the only condition where metric and engine separate) and **shipping-rate-service oscillating** (the only condition every autoscaler fails), with **auth-service oscillating** as the contrast panel:

```
Panel 1: Observed request rate / delivered throughput
Panel 2: Active Pod Count — 4 overlaid lines (H1, H2, H3, K1)
Panel 3: p95 Latency — 4 overlaid lines
Panel 4: CPU Utilization — 4 overlaid lines
```

The visual story must match the post-fix evidence (time-to-scale is not yet extracted):
- **Shipping spike:** p95 ranks K1 941 ± 10 < H3 987 ± 64 < H2 993 ± 109 < H1 1101 ± 177 ms against B2 917 ms; the replica panels should show whether K1's lower variance comes from earlier or steadier scale-up.
- **Shipping oscillating:** replica count runs out of phase with the load — the four autoscalers average 1.9–2.8 replicas during peaks but 3.6–4.2 during troughs — and p95 stays at 2656–3096 ms against a 916 ms floor.
- **Auth oscillating (contrast):** the autoscalers already sit at 2–4 replicas at base load and stay at or near 5 replicas through the troughs, so p95 stays within ~3% of B2 for H1–H3 and +9.2% for K1 (finding #14 validation note).

An examiner sees this ONE chart and immediately understands the entire thesis. It's the most compelling evidence you can produce.

### Strategy 4: The "Decomposition Table" (Unique Deliverable)

Produce a summary table that no other S1 thesis has:

| Service Type | Metric Effect (H3 vs H1) | Engine Effect (K1 vs H3) | Combined Effect (K1 vs H1) |
|-------------|------------------------|-------------------------|---------------------------|
| shipping-rate-service — gradual | (917−920)/920 = **−0.3%** | (916−917)/917 = **−0.1%** | (916−920)/920 = **−0.4%** |
| shipping-rate-service — spike | (987−1101)/1101 = **−10.4%** | (941−987)/987 = **−4.7%** | (941−1101)/1101 = **−14.5%** |
| shipping-rate-service — oscillating | (3096−2656)/2656 = **+16.6%** | (2748−3096)/3096 = **−11.2%** | (2748−2656)/2656 = **+3.5%** |
| auth-service — gradual | (1160−1164)/1164 = **−0.3%** | (1150−1160)/1160 = **−0.9%** | (1150−1164)/1164 = **−1.2%** |
| auth-service — spike | (1462−1496)/1496 = **−2.3%** | (1476−1462)/1462 = **+1.0%** | (1476−1496)/1496 = **−1.3%** |
| auth-service — oscillating | (1188−1170)/1170 = **+1.5%** | (1260−1188)/1188 = **+6.1%** | (1260−1170)/1170 = **+7.7%** |

*All values are 5-rep means from the post-fix 180-run dataset (2026-08-15/17, commit `7fde0a2`). Negative = improvement. Percentages are computed from the rounded means shown (from unrounded means: shipping-spike metric −10.3%, shipping-gradual engine −0.0%). Every pre-2026-08-15 value in earlier revisions of this table was a connection-pinning artifact — see finding #12.*

**Interpretation — the decomposition is now mostly null, and that IS the result:**
- **Four of six rows are within ±2.5% on the metric axis.** Once every pod actually receives traffic, metric choice stops mattering. The old table's headline −48.7% on shipping gradual does not survive: H1 and H3 now differ by 3 ms.
- **Shipping spike is the one row where the decomposition works as designed:** metric contributes **−10.4%**, engine a further **−4.7%**, combined **−14.5%**. Read alongside the stability figures (K1 ± 10 ms vs H3 ± 64 ms), this is the strongest evidence in the thesis that engine architecture matters independently of metric.
- **Shipping oscillating inverts (+16.6% metric):** request-rate is *worse* than CPU here. But note all four configs are 2.7–3.1 s against a 916 ms floor, so this row compares degrees of failure, not degrees of success. Report it with finding #14's gap-closed framing rather than as a metric recommendation.
- **Honest framing for BAB 5:** the decomposition's value has shifted from "how much improvement comes from the metric" to **"under what conditions does either factor matter at all"** — the answer being: only where autoscaling is stressed — shipping spike, and (as a failure) shipping oscillating. The proposed explanation — service time long relative to the load-change period — remains a hypothesis: the two-service contrast is confounded because auth stays at or near `maxReplicas` through its troughs (finding #14 validation note), so it cannot by itself isolate service time.

---

## 10. Realistic Timeline (7-8 Months)

With 7-8 months available, the timeline shifts from "compressed sprint" to "deliberate, high-quality execution." This extra time is valuable — it allows thorough piloting, careful debugging, iterative analysis, and multiple advisor review cycles.

### Phase 1: Foundation & Literature (Weeks 1-6)

| Week | Activities | Deliverables |
|------|-----------|-------------|
| 1-2 | Literature review: HPA, KEDA, autoscaling in Kubernetes. Read 15-20 papers. Draft BAB 2 skeleton. | Annotated bibliography, BAB 2 outline |
| 3 | AKS cluster creation, ACR image push, verify all deployments work on AKS including shipping-rate-service and carrier-mock-service | Working cluster with the thesis services deployed |
| 4 | Install KEDA (AKS add-on) + prometheus-adapter (Helm). Verify both are running. | KEDA + adapter operational |
| 5 | Implement wait-dominant shipping-rate-service and mock carrier endpoints. Rewrite k6 scripts for auth + shipping workloads. | Working shipping prototype, validated k6 scripts |
| 6 | Add resource requests to monitoring pods. Present the thesis pivot (auth + shipping core matrix, product exploratory appendix) to advisor for approval. | Advisor approval on revised scope |

### Phase 2: Pilot & Calibration (Weeks 7-10)

| Week | Activities | Deliverables |
|------|-----------|-------------|
| 7 | Configure KEDA ScaledObject, test Prometheus scaler triggers. Debug any query issues. | Working KEDA scaling |
| 8 | Configure prometheus-adapter rules, verify H3 custom metric appears in Kubernetes API. Debug. | Working `kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1` |
| 9 | Calibrate thresholds: run baseline tests at various RPS, determine saturation point, set H3 and K1 thresholds to the same value for auth and shipping. | Documented calibration results |
| 10 | Full pilot runs: 6-12 experiments across auth-service and shipping-rate-service. Validate data collection pipeline, scoped exporters, and shipping-aware analysis scripts. | Validated experiment pipeline |

### Phase 3: Experiments (Weeks 11-16) — ✅ COMPLETE (final post-fix re-run 2026-08-15 → 08-17)

All 180 runs have been executed and stored in `experiment-results/`. Campaign history:

| Task | Status | Notes |
|------|--------|-------|
| Original 180-run campaign (May–June 2026, incl. the 2026-05-23 K1 re-run) | ⛔ Superseded | Connection pinning (finding #12); recoverable from git history before commit `d30afc0` |
| Fixes: `noConnectionReuse`, auth → closed-loop `ramping-vus`, `setup()` failure floor | ✅ Done | 2026-08-15, commits `7fde0a2`, `2bbdb1f`, `a39b1f2` |
| Final 180-run re-run (both services) | ✅ Complete | 2026-08-15 → 08-17, 58 h 49 m; `validate-results.sh` 0/0/0, `deep_validate.py` 0 critical (19 auth-B1 heuristic warnings) |

### Phase 4: Analysis & Visualization (Current Phase)

| Task | Activities | Deliverables |
|------|-----------|-------------|
| 4a | Descriptive statistics (mean, median, SD, CI) for all KPIs across all 36 cells (all clean). p95 and error-rate means are already computed (findings #13–14). | Summary statistics tables |
| 4b | Time-to-scale extraction from `k8s-events.txt` (load-onset epoch → first `SuccessfulRescale` event) | time-to-scale per config/pattern/rep |
| 4c | Statistical testing (Wilcoxon signed-rank: H1 vs H3, H3 vs K1, H1 vs K1). Compute effect sizes. | Significance test results |
| 4d | Pareto frontier computation and cost analysis. Build the decomposition table (metric effect vs engine effect). | Pareto plots, decomposition table |
| 4e | Regenerate all figures from the post-fix dataset (`thesis-figures/`, dated 2026-06-12, is superseded), then create annotated timeline visualizations, comparison bar charts and the recommendation matrix. | All thesis figures |

### Phase 4b: Open-Loop Study (added 2026-10-06 — Part 08)

| Task | Status | Notes |
|------|--------|-------|
| Open-loop pilot v1 (20 runs, spike) | ✅ Done 2026-10-05/06 | Rule verdict GO via the criterion-4 explanation; strict reading STAY |
| v2 fixes (admission control, auth pre-auth, robustness gate) + v2 calibration | ✅ Done 2026-10-06 | ConfigMap overlay on the existing images (ACR Tasks unavailable in Indonesia Central) |
| v2 smoke test (9 runs) | ✅ Done 2026-10-06 08:31–11:31 UTC | 9/9 runs clean; pre-registered gate (rule v1) FAIL on one G6 cell (shipping H3 error rate) |
| G6 rule v2 + campaign config | ✅ Fixed and pushed 2026-10-06 (`6ef8f89`, `b35bee1`) before any campaign data | 50% of the mean or ≤ 30 s / ≤ 2 points |
| 180-run open-loop campaign with gate after rep block 2 | ✅ **Complete 2026-10-09 (180/180)**; gate after rep blocks 1–2 FAIL (G5 1 run; G6 3 of 24 cells, all CPU-based), continued as a documented deviation (Part 12); G1–G4 pass in all 180 runs | ≈61.6 h ≈ $31.8 of AKS in total (estimate); Phase 4 follows the analysis plan in Part 12 |

**Effect on Phase 4/5:** BAB 4 analysis of the closed-loop dataset can proceed in parallel. If the open-loop campaign passes, BAB 3/4 gain a second generator condition (Part 08 §8.14); if not, the open-loop pilot and smoke results are reported as a robustness study.

> **Superseded (2026-10-06, "Replace" — Part 08 §8.14):** if the campaign passes its gate, Phases 4a–4e run on the
> open-loop campaign and the closed-loop dataset becomes methodology background; if it fails, they run on the
> closed-loop dataset and the open-loop work becomes a robustness section.

### Phase 5: Writing (Weeks 21-28)

| Week | Activities | Deliverables |
|------|-----------|-------------|
| 21-22 | BAB 1 (Introduction) + BAB 3 (Methodology) | Draft chapters 1, 3 |
| 23-24 | BAB 4 (Results and Analysis) — the heaviest chapter, with all figures and tables | Draft chapter 4 |
| 25 | BAB 2 (Literature Review) — finalize based on experiment insights | Draft chapter 2 |
| 26 | BAB 5 (Conclusions, Recommendations, Future Work) | Draft chapter 5 |
| 27 | Advisor review — submit full draft, receive feedback | Advisor feedback |
| 28 | Final revisions, formatting, reference checking, abstract | Final thesis |

**Total: ~28 weeks (7 months).** Leaves 1 month buffer if on 8-month schedule.

**Status (2026-10-05):** BAB 1–3 and front matter are drafted (`Skripsi_Ignatius_Kevin_Wijaya.docx`, last edited 2026-06-06). BAB 3 still describes the retired auth arrival-rate profile and the 5.56× gate and needs revision for the post-fix methodology; BAB 4–5 are pending the Phase 4 analysis.

> **Update (2026-10-06, "Replace"):** if the open-loop campaign passes, BAB 3 is rewritten around the open-loop method
> (generator, load shedding, pre-login, gate, H1 = 80%) with the closed-loop campaign as the reason for switching; Part
> 11 gives the provenance and sources for every setting. BAB 4–5 wait for the campaign.

**Key advantages of the extended timeline:**
1. **2 full weeks for prometheus-adapter** (Week 8-9) — the highest-risk component gets dedicated time
2. **4 weeks for experiments** — no rushing, spread across multiple sessions
3. **4 weeks for analysis** — thorough statistical work, not rushed calculations
4. **8 weeks for writing** — multiple advisor review cycles, professional quality
5. **Multiple buffer weeks** — absorbs any slippage without cascading

---

## 11. Final Assessment

### Rating: **9 / 10**

### Why 9

**What makes it strong:**

1. **Controlled factorial design.** The H3 config (HPA + request-rate via prometheus-adapter) transforms this from a simple tool comparison into a proper scientific experiment. The 2×2 design (engine × metric) isolates each variable's contribution. This is the single most important improvement — it makes the thesis methodologically defensible against any reviewer objection.

2. **Paradigm comparison, not parameter tuning.** Comparing reactive CPU-based scaling against event-driven request-rate scaling is a fundamentally more interesting research question than tuning thresholds.

3. **The workload-fit finding is genuine and practical.** The experiment will empirically show when CPU-based HPA is sufficient, when request-rate scaling is needed, and how much of the improvement comes from the metric versus the engine. The factorial design still reveals WHETHER the fix is the metric (H3 vs H1) or the engine (K1 vs H3) — a nuanced finding that no other S1 thesis provides.

4. **The decomposition table is a unique deliverable — and its null rows are the finding.** The post-fix data quantifies exactly when each factor matters: four of six conditions are within ±2.5% on the metric axis (it does not matter), while shipping spike shows metric −10.4%, engine −4.7%, combined −14.5%. "Metric and engine choice are irrelevant unless autoscaling is stressed (here: spike load on the wait-dominant service)" is a directly actionable rule for practitioners, and a more defensible claim than a single headline percentage; the service-time explanation for the oscillating failure still needs verification (finding #14 validation note).

5. **Multi-dimensional analysis.** Combining performance, efficiency, and cost into a Pareto analysis with Pareto frontiers and dollar-cost equivalents elevates this above descriptive empiricism.

6. **Real application, real cloud.** Testing on an actual microservices app on AKS (not a synthetic benchmark) gives external validity.

7. **Statistical rigor.** 5 repetitions, Wilcoxon signed-rank significance testing, 95% confidence intervals. This is uncommon at S1 level.

8. **Annotated timeline visualizations.** The synchronized multi-panel charts with H1/H2/H3/K1 overlaid on the same plot produce undeniable visual evidence. Examiners remember these.

**What prevents it from being 10:**

1. **No new tool or algorithm.** You are comparing and decomposing existing tools' behavior, not creating something new. The contribution is empirical analysis with controlled methodology, not algorithmic invention. This is the hard ceiling for empirical S1 work — reaching 10 would require building a custom autoscaler or proposing a novel scaling algorithm.

2. **Single application domain.** The findings are validated on one e-commerce application. Generalizability to other domains (streaming, batch processing, ML inference) would require additional experiments beyond S1 scope.

### Concise Summary

This thesis compares Kubernetes autoscaling strategies using a controlled factorial design: HPA with CPU metric, HPA with request-rate metric (via prometheus-adapter), and KEDA with request-rate metric. By testing on two microservices with deliberately contrasting workload profiles (wait-dominant external dependency vs CPU-dominant authentication) on AKS, it isolates the contribution of **metric type** from **engine architecture** to scaling effectiveness. Across 180 controlled core experiments with statistical rigor, it measures latency, error rate, scaling speed, and resource cost, producing a decomposition of improvement factors and a Pareto-optimal cost-performance analysis. Product-service remains as an exploratory case-study about the limits of app-tier autoscaling when the true bottleneck sits in a downstream database.

**Budget:** ~$75 | **Timeline:** 28 weeks (7 months) | **Risk:** Medium (prometheus-adapter + KEDA setup) | **Score:** 9/10

### Final Recommendation

**Proceed with this plan.** The thesis is well-scoped, well-budgeted, methodologically rigorous, technically deep, and career-relevant. The 7-8 month timeline provides ample buffer for the two highest-risk components (KEDA setup in Weeks 7-8, prometheus-adapter in Weeks 8-9).

**Fallback strategy** (if prometheus-adapter proves unworkable after 1 week of debugging):
- Drop H3, revert to 5-config design → still 8.5/10
- The thesis still compares HPA vs KEDA effectively; you just acknowledge the metric-vs-engine question as a limitation and future work
- This fallback is low-probability (prometheus-adapter is mature and well-documented) but having it means you can never end up with nothing

---
