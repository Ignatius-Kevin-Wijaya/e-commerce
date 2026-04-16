# Definitive Thesis Blueprint: HPA vs KEDA Comparative Study

---

## 1. Re-analysis of the Current Thesis Direction

### What changed since the prior analyses

The thesis has evolved through five iterations:
1. **Original outline** (5.5/10): HPA-on vs HPA-off — confirmation experiment, no novelty
2. **Revised scope** (8/10): HPA threshold × scaling policy matrix — added depth but remained within reactive scaling paradigm
3. **First KEDA blueprint** (8.5/10): HPA vs KEDA — paradigm comparison, but had a fairness flaw (changing two variables at once: engine AND metric type)
4. **Factorial-design blueprint** (9/10): HPA (CPU) vs HPA (request-rate via prometheus-adapter) vs KEDA (request-rate) — **controlled factorial design** that isolates the metric-type effect from the engine-architecture effect
5. **Current validated state** (this revision, 9.25/10): same factorial design, but now grounded by AKS recovery findings and the implemented thesis-direction pivot: auth-service has been recalibrated fairly as the **CPU-dominant control**, product-service is retained as an **exploratory dependency-limited case**, and the final non-CPU counterpart is now an AKS-validated **wait-dominant shipping-rate-service** that gives a cleaner app-tier autoscaling comparison than product-service could provide

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

### What has now been validated on AKS (as of April 16, 2026)

- **Auth-service is now a calibrated CPU-bound control.** The original auth load was too aggressive, the original request-rate threshold was unreachable for H3/K1, and the original `100m` CPU request made CPU HPA unfairly eager. Those issues have now been corrected and verified live on AKS.
- **Shipping-rate-service is now implemented and live-verified as the final wait-dominant comparison workload.** The service fans out to mock carriers, mostly waits on outbound quote latency, is routed through the API gateway, and has already passed local and AKS smoke validation.
- **Product-service should no longer be described as the final non-CPU thesis service.** It is a mixed DB-backed workload, and once the dataset/load become interesting enough the single `product-db` can become the true bottleneck. In that regime, scaling the app tier may not help and can even make outcomes worse.
- **Threshold calibration is service-specific, not global.** H3 and K1 must share the same threshold within a given service, but the correct auth threshold and the correct product threshold do not need to be the same number. Both services currently calibrate to `5`, but that equality is an outcome of measurement, not a methodological requirement.
- **CPU-request fairness matters academically.** HPA CPU scales on `usage / request`, not `usage / limit`, so an unrealistically tiny CPU request can make H1/H2 look stronger than they really are. This is now explicitly part of the methodology.
- **Seed size and downstream capacity must be calibrated together.** More product rows are not automatically "better" for the thesis. The April 15 ladder showed that changing product seed size can move the system from "too easy" to "DB-bottlenecked" without ever passing through a clean app-tier autoscaling regime unless dependency capacity is controlled too.
- **The strongest final direction is now auth-service + the implemented wait-dominant shipping-rate-service.** This preserves the factorial design while removing the biggest confound from the non-CPU side of the comparison.
- **The thesis remains stronger, not weaker, after the pivot.** Product-service is still useful as an exploratory finding about downstream bottlenecks and the limits of app-tier autoscaling, but it should no longer anchor the final head-to-head matrix.

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

12. **Shipping-rate-service has already passed the minimum AKS readiness bar for the final core matrix.** The gateway route works end-to-end, the shipping k6 gradual smoke (`5 -> 20` RPS) completed with about `0.33%` failures and `p95 ≈ 929ms`, and both H3 and K1 scaled from `1 -> 2` after calibrating the request-rate threshold from `15` to `5`.

### Recovery and Calibration Timeline (April 7-16, 2026)

| Date | Event | Confirmed Finding / Result |
|------|-------|----------------------------|
| **2026-04-07** | First 36-run pilot across both services | Revealed systemic issues: auth-service overload, product-service reset contamination, and broken H3 custom metrics. Data served as pilot validation, not final thesis evidence. |
| **2026-04-08** | Deep verification report (`thesis_deep_analysis.md`) | Formalized the recovery plan: fix auth load, repair metrics path, fix cluster reset, and re-evaluate product workload realism before any full pilot. |
| **By 2026-04-13** | Latest recovery commit already present in repo | Auth path improved with mixed `/auth/me` + `/auth/login` workload, bcrypt offloaded in-app, relaxed probes, and experiment reset fixes. Product workload already used search/pagination-heavy `/products` against a seeded larger catalog. |
| **2026-04-13** | Auth baseline calibration ladder revisited | Single-pod auth baseline remained poor even at modest peak loads: roughly `40.73%` failures at peak `20`, `55.87%` at peak `30`, and `62.73%` at peak `40`, confirming the older auth profile was not suitable as a shared thesis workload. |
| **2026-04-13** | Auth H3/K1 threshold investigation | Old auth threshold `50 req/s` was shown to be miscalibrated: the `20 -> 40 RPS` auth test could not cross it, and Prometheus only observed roughly `~9-12 req/s` when the pod was already saturated. |
| **2026-04-13** | Auth fairness fixes applied and verified | Shared auth workload defaults changed to `10 -> 40`, auth H3/K1 threshold changed to `5`, and live AKS H3 smoke scaled `1 -> 5`, proving request-rate scaling was functional once calibrated correctly. |
| **2026-04-13** | Auth CPU-request fairness fix | Auth CPU request was raised from `100m` to `250m` in deployment and baseline manifests. Live AKS smokes then showed H1, H2, H3, and K1 all scaling sensibly under the same workload, with cluster cleanup verified afterward. |
| **2026-04-14** | Product-service live re-analysis | Live AKS product DB was confirmed at `10,020` products and about `9.3 MB`. Warm search queries remained relatively fast, showing the workload is real and DB-backed, but not yet a pure downstream-I/O bottleneck. |
| **2026-04-14** | Product CPU-request fairness fix | Product CPU request was raised from `100m` to `250m`. Live H1 and H2 smokes showed H1 scaling later and H2 scaling earlier, confirming the old `100m` request had been unfair but also confirming CPU HPA still retains signal on the current product workload. |
| **2026-04-14** | Product seed-intensity calibration implemented | Product seeding was parameterized and used to grow the catalog to `5000` items/category, producing `50,020` total products and about `47 MB` of product data. The heavier dataset increased representative search-query cost to about `86.7 ms` for the count query and about `96.9 ms` cold / `92.7 ms` warm for the page query. |
| **2026-04-14** | Product H1 smoke on the 50k dataset | Under the same spike smoke, H1 stayed at `1` replica and only showed about `15-26%` of its `70%` CPU target, indicating that CPU HPA had largely lost signal at this higher DB intensity. |
| **2026-04-14** | Product H3/K1 threshold investigation | The old product request-rate threshold `50 req/s` was also shown to be miscalibrated: H3 stayed at `1` replica while Prometheus exposed only roughly `~10-12 req/s` from the saturated pod. |
| **2026-04-14** | Product H3/K1 recalibration and live verification | Lowering the product request-rate threshold to `5` caused both H3 and K1 to scale successfully on the same 50k-product dataset, creating the clearest current separation between CPU-based and request-rate-based autoscaling for product-service. |
| **2026-04-15** | Corrected `experiment-first` results analyzed | Auth-service looked mostly thesis-usable, but product-service at `20 -> 200` remained invalid: all 18 product runs collapsed heavily, including `B2`, `H3`, and `K1`. This showed that the first corrected sweep was a diagnostic success, not a product-side acceptance result. |
| **2026-04-15** | Product dependency ladder on the `~50k` dataset | Live AKS ladder runs showed `B2 spike 5 -> 20` still failed at `88.04%`, and even `B2 spike 2 -> 10` still failed at `76.26%`. That confirmed the `~50k` regime was too DB-bottlenecked for a fair app-tier autoscaler comparison. |
| **2026-04-15** | Product seed reduced to `~30k` then `~20k` | Reducing the catalog to `30,020` products improved `B2 spike 2 -> 10` to `39.72%` failures. Reducing again to `20,020` products made `B2 spike 2 -> 10` completely healthy (`0%` failures), proving seed size is a critical control knob. |
| **2026-04-15** | Product boundary bracket at `~20k` | On `20,020` products, `B2 spike 4 -> 15` failed at `31.62%`, `B2 spike 3 -> 12` failed at `20.82%`, and `B2 spike 2 -> 11` failed at `8.75%`. This showed the usable product regime lies near a narrow boundary rather than a broad stable zone. |
| **2026-04-15** | Cross-config comparison at `~20k`, `2 -> 11` spike | The most important finding: `B1` stayed healthy (`0%` failed), but `B2` (`8.75%`), `H1` (`13.09%`, 1 replica), and `K1` (`12.42%`, 3 replicas) all degraded. This is strong evidence that the database, not the app tier, dominated behavior in that regime. |
| **2026-04-16** | Thesis direction decision after option analysis | The final core comparison was formally pivoted away from product-service. Auth-service remains the CPU-dominant control, shipping-rate-service was chosen as the final non-CPU comparison service, and product-service was retained as an exploratory case about downstream bottlenecks and scaling the wrong tier. |
| **2026-04-16** | Shipping-rate-service implemented and verified | `shipping-rate-service` and `carrier-mock-service` were implemented, routed through `api-gateway`, deployed on AKS, and verified locally plus in-cluster via real `POST /shipping/quotes` requests returning multi-carrier quote aggregates. |
| **2026-04-16** | Shipping load and autoscaler smoke calibration | Shipping k6 smoke at gradual `5 -> 20` RPS completed with about `8549` requests, `0.33%` failures, and `p95 ≈ 929ms`. H3 and K1 were first shown to read the shipping metric path correctly, then recalibrated from threshold `15` to `5`, after which both scaled `shipping-rate-service` from `1 -> 2` on AKS. |
| **Current interpretation** | Post-pivot validated state | Auth-service is now a defensible CPU-bound control, and shipping-rate-service is now the implemented and smoke-validated wait-dominant comparison service. Product-service remains academically useful, but as a dependency-sensitive DB-backed case study rather than part of the final controlled matrix. |

### What This Means For The Thesis

- **The original strong claim that "CPU HPA should clearly fail on product-service" is too strong.** Product-service should no longer be treated as the final non-CPU counterpart in the core matrix.
- **The strongest thesis contribution is now a two-part story.** First, auth-service validates the CPU-dominant control case. Second, the product experiments document a real-world validity lesson: app-tier autoscaling comparisons break down when a downstream dependency dominates.
- **This makes the thesis more credible, not weaker.** A refuted or nuanced hypothesis is still a valid research contribution, especially because the factorial design isolates metric choice from autoscaler engine choice.
- **Methodological calibration is now part of the contribution.** Fair CPU requests, service-specific request-rate thresholds, same-workload comparisons, and a dependency-isolation gate explain why earlier results were misleading and why the corrected runs are more defensible.
- **The final controlled comparison should now be auth-service vs shipping-rate-service.** This preserves the original thesis objective, but with a much cleaner non-CPU workload whose bottleneck is deliberate wait on outbound dependency calls rather than an overloaded in-cluster database.
- **Product-service remains in the thesis as a case-study, not as wasted work.** It provides a realistic counterexample showing that autoscaling app pods does not fix every performance problem.

### One Important Caution

These findings are strong, but they are still **pre-final-matrix findings**, not the final full auth+shipping dataset. Shipping-rate-service is now implemented and smoke-calibrated, but the full `B1/B2/H1/H2/H3/K1` matrix should only be trusted after a fresh `experiment-first` sweep passes with the updated auth+shipping scripts, exporters, and validators. Product-service runs should not be mixed into the final core statistical analysis; they should be reported separately as exploratory or appendix results.

---

## 2. Final Thesis Theme and Title Recommendation

### Final Recommended Title

> **"Analisis Pengaruh Jenis Metrik Penskalaan dan Mekanisme Autoscaler (HPA vs KEDA) terhadap Responsivitas dan Efisiensi Biaya Aplikasi Microservices pada Kubernetes"**

### Title Evolution

This title has been refined through 4 iterations:

| Iteration | Title Approach | Issue |
|-----------|---------------|-------|
| v1 | "...HPA-on vs HPA-off..." | Binary, no novelty |
| v2 | "...Konfigurasi Threshold dan Scaling Policy pada HPA..." | HPA-only, narrow scope |
| v3 | "...Penskalaan Reaktif Berbasis CPU (HPA) dan Event-Driven Berbasis Request Rate (KEDA)...pada Azure Kubernetes Service" | Framed as 2-way HPA vs KEDA comparison — doesn't reflect H3 (HPA + request-rate), 27 words, double parenthetical, over-specifies platform |
| **v4 (current)** | "...Jenis Metrik Penskalaan dan Mekanisme Autoscaler (HPA vs KEDA)...pada Kubernetes" | ✅ Reflects factorial design (two independent variables), 18 words, clean, generalizable |

### Why This Title — Decision by Decision

**1. "Analisis Pengaruh" instead of "Analisis Komparatif"**

"Analisis Komparatif" (comparative analysis) implies a simple A-vs-B comparison — which is what this thesis USED to be before H3 was added. Now the thesis studies the **effect** of two independent variables (metric type and engine mechanism) through a controlled factorial design. "Analisis Pengaruh" (effect analysis) correctly signals: "we are measuring the effect of X on Y," which is what factorial experiments do. It's more scientifically precise.

**2. "Jenis Metrik Penskalaan" — the first independent variable**

This phrase captures the metric-type factor: CPU utilization (H1/H2) vs request rate (H3/K1). It tells the reader: "this thesis tests whether the CHOICE of scaling metric matters." Without this, H3's existence would be invisible from the title.

"Penskalaan" (scaling) is added to clarify these are metrics used FOR autoscaling decisions — not general application metrics.

**3. "Mekanisme Autoscaler (HPA vs KEDA)" — the second independent variable**

This captures the engine factor: HPA controller vs KEDA operator. The parenthetical "(HPA vs KEDA)" names the specific tools, which is critical — these are the keywords examiners and indexers will search for.

"Mekanisme" (mechanism) is more precise than "Arsitektur" (architecture) for what's being compared. The thesis compares HOW each autoscaler works (controller-loop vs event-driven polling), not system architecture in general.

**4. Two output dimensions, not three**

The previous title had "Responsivitas, Efisiensi Resource, dan Biaya Operasional" — three outputs. But "Efisiensi Resource" (are pods wasting CPU?) and "Biaya Operasional" (how much does it cost in dollars?) are closely related: wasting resources IS the cause of high cost. They can be merged into **"Efisiensi Biaya"** (cost efficiency) without losing meaning. The thesis still MEASURES all three things (latency, utilization, dollar cost) — the title just groups them into two clean categories:
- **Responsivitas** = p95 latency, error rate, time-to-scale (performance)
- **Efisiensi Biaya** = Resource Cost Index, pod utilization ratio (cost/efficiency)

**5. "Aplikasi Microservices" instead of "Layanan Microservices"**

"Layanan" means "services." "Microservices" already means "micro-services." So "Layanan Microservices" = "microservices services" — redundant. "Aplikasi Microservices" (microservices application) is correct and refers to the e-commerce application being tested.

**6. "pada Kubernetes" instead of "pada Azure Kubernetes Service"**

AKS is the experiment environment, not a research variable. Every core component of the thesis — HPA algorithm, KEDA operator, prometheus-adapter, Prometheus, k6 — works identically on GKE, EKS, or bare-metal Kubernetes. Including "Azure" in the title:
- Misleads about scope (readers may think findings are Azure-specific)
- Wastes 2 words of title budget
- Limits generalizability claims in BAB 5
- Over-emphasizes the hosting choice when the thesis is about autoscaling behavior

"Kubernetes" IS essential because HPA and KEDA are Kubernetes-specific concepts. A reader needs to know this is about K8s autoscaling.

AKS is still properly credited in BAB 3.2.1 (research environment description) and BAB 4.1 (system specifications) — where it belongs.

**7. Single parenthetical, not double**

The v3 title had two parentheticals: `(CPU Utilization vs Request Rate)` and `(HPA vs KEDA)`. This is visually cluttered. The current title has one: `(HPA vs KEDA)`. The metric specifics (CPU vs request rate) are implied by "Jenis Metrik Penskalaan" and explicitly detailed in BAB 1.2 (Rumusan Masalah).

### Title Scorecard

| Criteria | Score |
|----------|-------|
| Reflects factorial design (two independent variables)? | ✅ "Jenis Metrik" + "Mekanisme Autoscaler" |
| Reflects H3's existence (the key innovation)? | ✅ Two separate factors imply a crossover config |
| Mentions HPA and KEDA by name? | ✅ "(HPA vs KEDA)" |
| Mentions what's measured? | ✅ "Responsivitas dan Efisiensi Biaya" |
| Mentions the domain? | ✅ "Aplikasi Microservices" |
| Mentions the platform? | ✅ "Kubernetes" |
| Not too long? | ✅ 18 words (ideal: 15-22) |
| Not too vague? | ✅ HPA/KEDA named, scaling metrics referenced |
| Generalizable? | ✅ All Kubernetes, not vendor-locked |
| Searchable keywords? | ✅ HPA, KEDA, Microservices, Kubernetes, Autoscaler |

**Overall: 9.5/10.** The 0.5 it loses: doesn't explicitly mention workload-type contrast (I/O-bound vs CPU-bound). Adding "dengan Karakteristik Beban Berbeda" would push to 22 words — acceptable but less punchy. This contrast is better introduced in BAB 1.

### Alternative Titles

**Alt 1 (Adding workload-type contrast — 22 words):**
> "Analisis Pengaruh Jenis Metrik Penskalaan dan Mekanisme Autoscaler (HPA vs KEDA) terhadap Responsivitas dan Efisiensi Biaya Aplikasi Microservices dengan Karakteristik Beban Berbeda pada Kubernetes"

*Adds "dengan Karakteristik Beban Berbeda" to signal the I/O-bound vs CPU-bound contrast. Longer but more complete. Use this if your advisor values completeness over conciseness.*

**Alt 2 (Emphasizing the experimental methodology — 20 words):**
> "Studi Eksperimental Pengaruh Jenis Metrik dan Mekanisme Autoscaling terhadap Performa Penskalaan Horizontal Aplikasi Microservices CPU-Bound dan I/O-Bound pada Kubernetes"

*Starts with "Studi Eksperimental" to immediately signal quantitative research. Mentions both workload types. Doesn't name HPA/KEDA in the title (they'd be in BAB 1). Use this if your department values methodology framing over tool specificity.*

**Alt 3 (Shorter, punchier — 16 words):**
> "Analisis Pengaruh Jenis Metrik Autoscaling pada HPA dan KEDA terhadap Performa Penskalaan Microservices pada Kubernetes"

*Shortest option at 16 words. Sacrifices the cost dimension ("Efisiensi Biaya") and focuses solely on performance. Use this if your advisor prefers concise titles, with the cost analysis positioned as a secondary contribution in BAB 1.*

---

## 3. Scope Definition

### In Scope

| Item | Detail |
|------|--------|
| Autoscaling methods compared | HPA (CPU-based), HPA (request-rate via prometheus-adapter), KEDA (request-rate, Prometheus scaler) |
| Services tested (core matrix) | shipping-rate-service (implemented and AKS-validated wait-dominant external dependency), auth-service (CPU-bound) |
| Exploratory case-study retained | product-service (mixed read-heavy / DB-backed, dependency-limited in current AKS regime) |
| Platform | Azure Kubernetes Service, Free Tier |
| Load patterns | Gradual ramp, sudden spike, oscillating |
| Baselines | Fixed under-provisioned (1 replica), fixed over-provisioned (5 replicas) |
| KPIs | Latency (p95), error rate, scaling speed, resource cost, pod-count stability |
| Statistical method | 5 repetitions, Wilcoxon signed-rank, 95% CI |
| Cost analysis | Pod-seconds × CPU-request × AKS pricing → dollar-cost per scenario |

### Out of Scope

| Item | Why excluded |
|------|-------------|
| Cluster Autoscaler | Confounds HPA/KEDA analysis — isolate pod-level scaling only |
| Vertical Pod Autoscaler (VPA) | Different scaling dimension (vertical vs horizontal) — separate thesis |
| Memory-based HPA | Adds a third variable; CPU vs request-rate is sufficient contrast |
| Custom Kubernetes controller/operator | Too much engineering for S1; use existing tools |
| Predictive/ML-based scaling | Requires ML expertise and custom implementation — out of S1 scope |
| Scale-to-zero (KEDA) | Powerful feature but introduces cold-start confound; mentioned as future work |
| All 5 services simultaneously | Cascading HPA/KEDA confounds — test one service at a time |
| Multi-cluster or federation | Irrelevant at this scale |

### Assumptions

1. Kubernetes metrics-server provides accurate CPU utilization data at 15-second resolution
2. Prometheus scrape interval (15s) provides sufficient time resolution for request-rate metrics
3. AKS node hardware (D4as_v5) provides consistent, non-burstable CPU performance
4. Controlled downstream-call latency inside AKS is an acceptable experimental proxy for external dependency wait in production microservices
5. The e-commerce-inspired service patterns (authentication, shipping quote lookup, payment/product/cart flows) are representative of typical web-based microservices

### Boundaries

- **One service under autoscaling at a time.** Other services run at fixed `replicas: 1`. This isolates the variable.
- **minReplicas ≥ 1** for both HPA and KEDA. No scale-to-zero. This ensures fair comparison (both start from same baseline).
- **maxReplicas = 5** for both methods. Same scaling ceiling.
- **Cluster Autoscaler disabled.** Node count is fixed at 3. If pods go `Pending`, this is a finding (capacity limit), not an error.
- **Each experiment run: 12 minutes** (2 min warm-up, 7 min test, 3 min cooldown). Consistent across all configurations.
- **Core statistical analysis covers auth-service and shipping-rate-service only.** Product-service results are retained separately as an exploratory dependency-limited case-study and should not be pooled into the main 180-run matrix.

---

## 4. AKS Architecture Decision

### Recommendation: **3× Standard_D4as_v5** ✅

### Why D4as_v5, not D2as_v5

The prior analysis recommended D2as_v5 for a pure HPA experiment. The shift to HPA vs KEDA changes the resource equation — more infrastructure pods are required (KEDA, prometheus-adapter), and the D4as_v5 provides the headroom needed for unbiased benchmarking.

### Cluster Capacity

| Per Node (D4as_v5) | Value |
|---------------------|-------|
| Total CPU | 4000m |
| kubelet reserved | ~100m |
| System reserved | ~40m |
| **Allocatable CPU** | **~3860m** |
| **3 Nodes Total Allocatable** | **~11580m** |

**AKS Free Tier control plane** (API server, etcd, scheduler, controller-manager) runs on Azure's managed infrastructure — NOT on your nodes. Zero CPU cost to you.

### Complete Pod Inventory — Verified from Codebase Manifests

Every pod listed below is sourced from the actual YAML files in your repository. Estimated values (for components installed at runtime) are marked with `~`.

#### Layer 1: AKS System Pods (Managed by AKS, always running)

These pods are automatically deployed by AKS and consume from the allocatable pool.

| Pod | Replicas | CPU Request | CPU Limit | Source |
|-----|----------|-----------|---------|--------|
| kube-proxy | 3 (DaemonSet) | 100m × 3 = 300m | — | AKS default |
| CoreDNS | 2 | ~100m × 2 = ~200m | — | AKS default |
| CoreDNS autoscaler | 1 | ~20m | — | AKS default |
| metrics-server | 1 | ~100m | ~200m | AKS default |
| cloud-node-manager | 3 (DaemonSet) | ~50m × 3 = ~150m | — | AKS default (Azure CNI) |
| **Subtotal** | | **~770m** | | |

*Note: Exact values may vary by AKS/Kubernetes version. Verify after cluster creation with `kubectl top pods -n kube-system`.*

#### Layer 2: Databases (Always running, 1 replica each)

| Pod | CPU Request | CPU Limit | Memory Request | Source |
|-----|-----------|---------|---------------|--------|
| auth-db (PostgreSQL) | 250m | 500m | 256Mi | [`postgres/auth-db.yaml`](file:///home/kevin/Projects/e-commerce/infrastructure/kubernetes/postgres/auth-db.yaml) |
| product-db (PostgreSQL) | 250m | 500m | 256Mi | [`postgres/product-db.yaml`](file:///home/kevin/Projects/e-commerce/infrastructure/kubernetes/postgres/product-db.yaml) |
| order-db (PostgreSQL) | 250m | 500m | 256Mi | [`postgres/order-db.yaml`](file:///home/kevin/Projects/e-commerce/infrastructure/kubernetes/postgres/order-db.yaml) |
| redis | 100m | 250m | 128Mi | [`redis/deployment.yaml`](file:///home/kevin/Projects/e-commerce/infrastructure/kubernetes/redis/deployment.yaml) |
| **Subtotal** | **850m** | **1750m** | **896Mi** | |

#### Layer 3: Application Services (Fixed at 1 replica during experiments)

During experiments, only ONE service is under autoscaling. All others run at `replicas: 1`.

| Pod | CPU Request | CPU Limit | Memory Request | Source |
|-----|-----------|---------|---------------|--------|
| api-gateway | 200m | 1000m | 256Mi | [`gateway/deployment.yaml`](file:///home/kevin/Projects/e-commerce/infrastructure/kubernetes/gateway/deployment.yaml) |
| auth-service | 250m | 500m | 128Mi | [`auth/deployment.yaml`](file:///home/kevin/Projects/e-commerce/infrastructure/kubernetes/auth/deployment.yaml) |
| product-service | 250m | 500m | 128Mi | [`product/deployment.yaml`](file:///home/kevin/Projects/e-commerce/infrastructure/kubernetes/product/deployment.yaml) |
| cart-service | 100m | 500m | 128Mi | [`cart/deployment.yaml`](file:///home/kevin/Projects/e-commerce/infrastructure/kubernetes/cart/deployment.yaml) |
| order-service | 100m | 500m | 128Mi | [`order/deployment.yaml`](file:///home/kevin/Projects/e-commerce/infrastructure/kubernetes/order/deployment.yaml) |
| payment-service | 100m | 500m | 128Mi | [`payment/deployment.yaml`](file:///home/kevin/Projects/e-commerce/infrastructure/kubernetes/payment/deployment.yaml) |
| frontend | 100m | 500m | 128Mi | [`frontend/deployment.yaml`](file:///home/kevin/Projects/e-commerce/infrastructure/kubernetes/frontend/deployment.yaml) |
| **Subtotal (all 7 at 1 replica)** | **1100m** | **4000m** | **1024Mi** | |

*Note: The current Kubernetes manifests already run the application services at `replicas: 1`, which matches the experiment requirement to isolate the autoscaling variable.*

#### Layer 4: Monitoring Stack (Always running)

| Pod | CPU Request | CPU Limit | Memory Request | Source |
|-----|-----------|---------|---------------|--------|
| prometheus | 100m | 500m | 256Mi | [`monitoring/prometheus.yaml`](file:///home/kevin/Projects/e-commerce/infrastructure/kubernetes/monitoring/prometheus.yaml) |
| grafana | 50m | 200m | 128Mi | [`monitoring/grafana.yaml`](file:///home/kevin/Projects/e-commerce/infrastructure/kubernetes/monitoring/grafana.yaml) |
| loki | 50m | 200m | 128Mi | [`monitoring/loki.yaml`](file:///home/kevin/Projects/e-commerce/infrastructure/kubernetes/monitoring/loki.yaml) |
| promtail | 50m × 3 = 150m | 200m × 3 = 600m | 64Mi × 3 = 192Mi | [`monitoring/promtail.yaml`](file:///home/kevin/Projects/e-commerce/infrastructure/kubernetes/monitoring/promtail.yaml) (DaemonSet, 3 pods) |
| **Subtotal (current)** | **350m** | **1500m** | **704Mi** | |

**Status:** The AKS monitoring manifests now declare resource requests and limits. This removes the earlier BestEffort-eviction confound from Prometheus/Grafana/Loki and keeps the monitoring layer aligned with the thesis methodology.

#### Layer 5: Thesis Infrastructure (KEDA + prometheus-adapter)

These are installed at runtime and their resource requests are estimated from default Helm/AKS-addon values.

| Pod | CPU Request | CPU Limit | Memory Request | Source |
|-----|-----------|---------|---------------|--------|
| keda-operator | ~200m | ~500m | ~256Mi | AKS KEDA add-on |
| keda-metrics-apiserver | ~100m | ~300m | ~128Mi | AKS KEDA add-on |
| keda-admission-webhooks | ~50m | ~100m | ~64Mi | AKS KEDA add-on |
| prometheus-adapter | ~100m | ~250m | ~128Mi | Helm chart |
| **Subtotal** | **~450m** | **~1150m** | **~576Mi** | |

#### Layer 6: Load Test Tool (Temporary — only during test runs)

| Pod | CPU Request | CPU Limit | Memory Request | Source |
|-----|-----------|---------|---------------|--------|
| k6 Job | 500m | 1500m | 512Mi | [`load-testing/k6-job.yaml`](file:///home/kevin/Projects/e-commerce/infrastructure/kubernetes/load-testing/k6-job.yaml), [`load-testing/k6-auth-job.yaml`](file:///home/kevin/Projects/e-commerce/infrastructure/kubernetes/load-testing/k6-auth-job.yaml) |

#### Layer 7: Autoscaled Pods (Peak — tested service scales to 5 replicas)

The tested service starts at 1 replica (already counted in Layer 3) and can scale to 5. The additional 4 pods are:

| Additional Pods | CPU Request | CPU Limit | Memory Request |
|----------------|-----------|---------|---------------|
| +4 pods of tested service (assuming `250m` request, matching auth-service and shipping-rate-service) | 1000m | 2000m | 512Mi |

### Peak Resource Budget (Worst Case)

This is the total when the tested service is at maxReplicas (5), k6 is running, and all other pods are active. Monitoring uses the fixed values (after adding resource requests).

| Category | CPU Requests | CPU Limits |
|----------|------------|----------|
| AKS system pods | ~770m | ~1200m |
| Databases (3× PostgreSQL + Redis) | 850m | 1750m |
| App services (7 pods at 1 replica, baseline) | 1100m | 4000m |
| Monitoring stack (after fix) | 350m | 1500m |
| KEDA + prometheus-adapter | ~450m | ~1150m |
| k6 Job | 500m | 1500m |
| Autoscaled pods (+4 additional) | 1000m | 2000m |
| **TOTAL** | **~5020m** | **~13100m** |

### Headroom Analysis

| Metric | Value | Status |
|--------|-------|--------|
| Cluster allocatable | 11580m | |
| Total CPU requests (peak) | ~5020m | |
| **Request headroom** | **~6560m (57%)** | ✅ Strong — scheduler still has ample room to place pods |
| Total CPU limits (peak) | ~13100m | |
| **Limit oversubscription** | **~1520m (13%)** | ✅ Acceptable for bursty workloads, but watch contention during concurrent peaks |

**What the numbers mean:**

1. **Request headroom of 57%** means the Kubernetes scheduler can place every pod without any `Pending` issues. Even if you doubled the autoscaled replicas to `maxReplicas: 10`, you'd still have ~3760m headroom.

2. **Limit oversubscription of 13%** means that in the theoretical worst case where every single pod hits its CPU limit simultaneously, there would be some throttling. In practice, this rarely happens because:
   - Databases are idle unless queried (~50m actual usage, not 500m)
   - Non-tested services at 1 replica with no traffic use ~10-20m each
   - Monitoring tools use ~30-50m actual each
   - Only the tested service + k6 are CPU-active during tests

3. **vs D2as_v5 (3 nodes × 1900m = 5700m allocatable):** Requests alone (3820m) would consume 67% of the total capacity, leaving only 1880m headroom — tight for burst. Limit oversubscription would be 6400m (>100%), causing severe throttling during spike tests. **D2as_v5 is not viable for this experiment.**

### Why This Math Matters for Fair Comparison

1. **Fair comparison requires equal resource availability.** If HPA tests run fine but KEDA tests suffer because KEDA's operator pods consume CPU that causes throttling, the comparison is biased against KEDA.
2. **KEDA's metrics-apiserver must be responsive.** If it's CPU-starved, metric delivery to KEDA's controller is delayed, making KEDA appear slower than it actually is.
3. **Prometheus must not miss scrapes.** Both H3 (HPA + custom metric) and K1 (KEDA) depend on Prometheus data. If Prometheus is undersized or misconfigured and starts missing scrapes, both methods receive stale data — invalidating the comparison.

### Cost Analysis

```
3× D4as_v5 at $0.172/hr each = $0.516/hr total

Setup/debugging (KEDA + prometheus-adapter):  40 hours = $20.64
Experiment runs:                              45 hours = $23.22 (180 runs × 15 min)
Pilot runs & calibration:                     15 hours = $7.74
Re-runs (30% buffer):                         14 hours = $7.22
Extra analysis/debug:                         20 hours = $10.32
──────────────────────────────────────────────────────────────
Total compute:                               ~134 hours = $69.14
Fixed costs (PVC: 3×5Gi + 10Gi + 1Gi):                   ~$5.00
ACR Basic (container registry):                            $5.00
──────────────────────────────────────────────────────────────
GRAND TOTAL:                                             ~$80
Remaining from $150/month credit:                        ~$70
```

**$80 is well within budget.** You have ~$70 of buffer for mistakes, extended debugging sessions, or additional experiment configurations.

### AKS Create Command

```bash
az aks create \
  --resource-group thesis-rg \
  --name thesis-aks \
  --node-count 3 \
  --node-vm-size Standard_D4as_v5 \
  --node-osdisk-type Ephemeral \
  --tier free \
  --location southeastasia \
  --network-plugin azure \
  --generate-ssh-keys \
  --no-wait
```

After creation, install KEDA and prometheus-adapter:
```bash
# Step 1: Install KEDA via AKS add-on (simplest, Microsoft-managed)
az aks update --resource-group thesis-rg --name thesis-aks --enable-keda

# Step 2: Install prometheus-adapter via Helm (required for H3 config)
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus-adapter prometheus-community/prometheus-adapter \
  --namespace monitoring \
  --set prometheus.url=http://prometheus.monitoring.svc.cluster.local \
  --set prometheus.port=9090
```

After cluster creation, verify AKS system pod resource usage:
```bash
# Check what AKS system pods are consuming
kubectl top pods -n kube-system
kubectl get pods -n kube-system -o custom-columns="NAME:.metadata.name,CPU_REQ:.spec.containers[*].resources.requests.cpu"
```

Recommend **AKS add-on for KEDA** (simplicity, thesis credibility) and **Helm for prometheus-adapter** (only installation method available).

---

## 5. Platform and Tooling Decisions

### Decision 1: PostgreSQL — **In-cluster pods** ✅

| Factor | Azure Database for PostgreSQL | PostgreSQL in Pods |
|--------|------------------------------|-------------------|
| Cost | $25–100/month | $0 extra |
| Experiment relevance | DB is NOT the variable under test | Same |
| Reproducibility | Shared resource, can have latency variance | Fully controlled within cluster |
| Thesis credibility | Slightly more "real" | Sufficient — DB is constant across all experiments |
| Complexity | SKU selection, firewall rules, connection strings | Already configured and working |

**Decision:** PostgreSQL in pods. The database is a **constant** in this experiment (same DB for all autoscaling methods). Using managed DB adds cost and latency variance without improving the comparison. In-cluster DB ensures the only variable is the autoscaling method.

### Decision 2: Container Registry — **ACR** ✅

| Factor | ACR (Azure Container Registry) | GHCR (GitHub Container Registry) |
|--------|-------------------------------|----------------------------------|
| Cost | $5/month (Basic) — covered by $150/month Azure credit | Free (public or private repos) |
| Pull speed from AKS | ✅ Fast (same Azure network, no cross-cloud egress) | Slightly slower (cross-cloud pull) |
| AKS integration | ✅ Native: `az aks update --attach-acr` — one command | Requires imagePullSecret configuration |
| Experiment impact | Faster pod startup = faster reset between runs | Slightly slower resets |
| Setup | `az acr create` + `az aks update --attach-acr` | Already configured in your CI |

**Decision:** ACR. With $150/month Azure credit, the $5/month ACR Basic cost is negligible. ACR provides same-network pull speed (faster pod startups during the 180-run experiment), native AKS integration with a single `az aks update --attach-acr` command (no imagePullSecret needed), and keeps the entire infrastructure within Azure — simpler to manage and debug.

```bash
# Create ACR
az acr create --resource-group thesis-rg --name thesisacr --sku Basic

# Attach ACR to AKS (allows AKS to pull images without secrets)
az aks update --resource-group thesis-rg --name thesis-aks --attach-acr thesisacr

# Build and push images (repeat for every service image used in the experiment)
az acr login --name thesisacr
docker tag shipping-rate-service thesisacr.azurecr.io/shipping-rate-service:latest
docker push thesisacr.azurecr.io/shipping-rate-service:latest
```

### Decision 3: Load Testing — **k6 inside the cluster** ✅

| Factor | External k6 (your laptop / separate VM) | k6 as Kubernetes Job |
|--------|----------------------------------------|---------------------|
| Network path | External → AKS Load Balancer → Service | Internal → Service DNS |
| Load Balancer needed? | Yes ($18+/month) | No |
| Network latency | Adds internet/LB latency to measurements | Measures pure service latency |
| Experiment control | Affected by your internet connection | Fully controlled within cluster |
| Cost | LB cost + egress | $0 — runs on existing nodes |

**Decision:** k6 inside the cluster as a Kubernetes Job. This eliminates the Load Balancer cost, removes external network variance from measurements, and provides the cleanest latency data. The repo now contains dedicated manifests for the auth, product, and shipping workloads (`k6-auth-job.yaml`, `k6-job.yaml`, `k6-shipping-job.yaml`).

**Important:** Assign resource requests to the k6 pod (`500m CPU, 512Mi memory` in the current manifests) to prevent it from being CPU-starved during peak load.

### Decision 4: Observability — **Prometheus + Grafana in-cluster** ✅

| Factor | Azure Monitor | Prometheus + Grafana in pods |
|--------|---------------|------------------------------|
| Cost | $50+/month (ingestion-based) | $0 — already deployed |
| Metric granularity | 1-minute minimum | 15-second scrape interval |
| Custom queries | Kusto (learning curve) | PromQL (already known) |
| KEDA integration | Requires Azure Monitor scaler | Native Prometheus scaler |
| Data export | Complex (Log Analytics → CSV) | Direct PromQL → JSON/CSV |

**Decision:** Prometheus + Grafana in-cluster. This is mandatory — KEDA's Prometheus scaler needs an in-cluster Prometheus instance to read metrics from. Azure Monitor would require a different KEDA scaler (azure-monitor), which is less documented and adds complexity. Your existing Prometheus setup is already scraping all services.

**Critical fix needed:** Add resource requests to monitoring pods (Prometheus: 100m CPU, Grafana: 50m, Loki: 50m). Without requests, they can be evicted under load, corrupting experiment data.

### Decision Summary

| Component | Choice | Why |
|-----------|--------|-----|
| Database | PostgreSQL in pods | Constant (not the variable), free, already working |
| Registry | ACR | Native AKS integration, fast pulls, covered by Azure credit |
| Load testing | k6 in-cluster Job | Eliminates LB cost and network noise |
| Observability | Prometheus + Grafana in pods | Required for KEDA, better resolution, free |
| KEDA installation | AKS add-on | Simplest, officially supported |
| prometheus-adapter | Helm chart | Required for H3 (HPA + custom request-rate metric) |
| Access to Grafana | `kubectl port-forward` | No public IP or LB needed |

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
        averageValue: "5"    # Same threshold as K1 KEDA — critical for fairness
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
      threshold: "5"       # Same threshold as H3 — critical for fairness
```

**Fairness note:** H3 and K1 use the same service-specific threshold, the same Prometheus data source, and the same scaling-policy intent. The ONLY difference is the autoscaling engine (HPA controller vs KEDA operator). This is what makes the comparison scientifically controlled.

### Load Patterns (Independent Variable #2)

| Pattern | Description | k6 Configuration | Why |
|---------|-------------|-------------------|-----|
| **Gradual Ramp** | Linear increase from a service-specific calibrated base RPS to a calibrated peak RPS over 5 minutes | `ramping-arrival-rate` with 1 ramp stage | Tests how smoothly autoscaling follows predictable growth |
| **Sudden Spike** | Service-specific calibrated baseline → instant jump to calibrated peak at t=2min | Step function with `constant-arrival-rate` | Tests reaction speed — the worst case for reactive HPA |
| **Oscillating** | Alternating between calibrated baseline and calibrated peak every 90 seconds | Multiple ramp stages with sharp transitions | Tests scaling stability — does the system thrash (scale up/down repeatedly)? |

**Calibration note:** Auth-service is now close to frozen at `10 -> 40` RPS. Shipping-rate-service is now implemented and smoke-calibrated with a manifest default of `10 -> 60` RPS, a verified gradual smoke at `5 -> 20` RPS, and a shared H3/K1 threshold of `5`. The dependency-isolation gate still applies before the final matrix is frozen, but the shipping path is no longer a design placeholder.

### Services Under Test (Independent Variable #3)

| Service | Workload Type | Why It's Different for This Experiment |
|---------|--------------|---------------------------------------|
| **shipping-rate-service** | Wait-dominant external-dependency workload | The hot path asynchronously fans out to three carrier quote endpoints, each with controlled delay and small payloads. This keeps the service mostly waiting on downstream responses with minimal local CPU, making it the deliberate non-CPU counterpart to auth-service. |
| **auth-service** | CPU-bound (bcrypt hashing) | CPU correlates with load → HPA works well → KEDA may offer no advantage. This is the "control" scenario. |

**Working hypothesis:** On auth-service, CPU-based HPA should remain competitive because the service is genuinely CPU-bound. On shipping-rate-service, request-rate autoscaling (H3/K1) should outperform CPU-based HPA (H1/H2) because the service is dominated by outbound wait rather than local compute. Product-service is retained as a supporting case-study showing a separate but important lesson: **when the dominant bottleneck lives in a downstream dependency, app-tier autoscaling may not help and can even worsen outcomes.**

### Experimental Protocol

1. **Dependency-isolation gate (before freezing any service profile):** Verify that the fixed overprovisioned control (`B2`) is healthy and meaningfully better than the fixed underprovisioned control (`B1`) under the same workload. If `B2` is no better, or is worse, classify the regime as downstream-limited and either raise dependency capacity or treat it as a separate case-study instead of a clean app-tier comparison.
2. **Cluster state reset:** Before each run, delete the previous autoscaler (HPA or ScaledObject), set deployment to `replicas: 1`, wait 60 seconds for stabilization, verify no residual pods
3. **Apply configuration:** Deploy the test config (HPA/KEDA/fixed replicas)
4. **Wait for stabilization:** 30 seconds for metrics to baseline
5. **Warm-up:** 2 minutes at the service-specific calibrated base load, data excluded from analysis
6. **Test execution:** 7 minutes of the designated load pattern at the service-specific calibrated peak behavior
7. **Cooldown observation:** 3 minutes at 0 RPS, observe scale-down behavior
8. **Data export:** Pull Prometheus metrics via PromQL, export k6 results to JSON
9. **Total per run:** ~12 minutes active + ~2 minutes setup = ~14 minutes

### Total Experiment Runs

| Component | Count |
|-----------|-------|
| Autoscaling configs | 6 (B1, B2, H1, H2, H3, K1) |
| Load patterns | 3 (gradual, spike, oscillating) |
| Repetitions | 5 |
| Services (core matrix) | 2 |
| **Total runs** | **6 × 3 × 5 × 2 = 180** |
| **Time per run** | ~15 minutes (including setup/reset) |
| **Total experiment time** | ~45 hours |
| **AKS cost** | 45 × $0.516 = ~$23.22 |

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

### How KPIs Are Interpreted

The central analysis combines primary KPIs into a **trade-off assessment:**

- **Performance winner:** Lowest p95 latency + lowest error rate + fastest time-to-scale
- **Cost winner:** Lowest resource cost index while meeting SLO thresholds
- **Balanced winner:** Best position on the Pareto frontier (latency vs cost)

If HPA and KEDA produce similar latency but KEDA uses fewer pod-minutes (because it scales more precisely), KEDA wins on efficiency. If HPA (CPU) underperforms on shipping-rate-service while H3 (HPA with request-rate) DOES trigger more appropriately, the conclusion is: **the metric type matters more than the HPA engine alone.** If KEDA still outperforms H3 despite using the same metric, KEDA's architecture provides additional value. Product-service remains separately useful here: if `B2`, `H3`, or `K1` are worse than `B1` under the same product workload, that should be interpreted as evidence of a downstream bottleneck and the limits of app-tier autoscaling, not as a simple "autoscaler X lost" result.

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

k6 generates HTTP requests at a specified rate. Even at the current thesis profiles (`10 -> 40` for auth, `10 -> 60` default for shipping), k6 still needs steady CPU to maintain concurrent HTTP connections, serialize bodies, and record timing metrics in real time.

If k6 doesn't get enough CPU, it silently under-delivers the offered load. Your "60 RPS spike" can quietly become a lower-throughput test without any obvious application-side crash.

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
#   Stop-AzAksCluster -ResourceGroupName "thesis-rg" -Name "thesis-aks"
#   Schedule: daily at 00:00 WIB

# Option 2: Simple cron reminder (less reliable but still helpful)
# On your phone: set a DAILY alarm at 11pm: "STOP AKS CLUSTER"

# Option 3: Check-before-sleep script
# Save this as ~/stop-aks.sh
az aks stop --resource-group thesis-rg --name thesis-aks --no-wait
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

4. **Threshold drift.** Shipping H3/K1 initially looked healthy but were still too conservative at threshold `15`. If the manifests, blueprint, or validator drift back to that value, the thesis will reintroduce a calibration bug that has already been solved.

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

## 9. Make-It-Stand-Out Strategy

### Strategy 1: The "Metric-Workload Fit" Narrative + Controlled Proof

Frame the entire thesis around one central story:

> "CPU-based autoscaling is Kubernetes' default, but its effectiveness depends on how strongly CPU correlates with user load. This thesis shows that the decisive factor is not the autoscaler brand alone, but the fit between workload regime and scaling metric. Using a controlled factorial design, it separates metric-type effects from engine effects and shows when request-rate scaling is necessary, when CPU is sufficient, and when both remain competitive on mixed workloads."

This narrative is more nuanced and academically stronger than simply "KEDA beats HPA." The thesis structure becomes:

1. **BAB 1:** There's a problem — CPU-based HPA doesn't work for all service types
2. **BAB 2:** Literature confirms this limitation but few studies isolate WHY (metric? engine? both?)
3. **BAB 3:** We design a controlled factorial experiment that isolates the variables
4. **BAB 4:** Results reveal the relative contribution of metric type vs engine architecture
5. **BAB 5:** Practitioners should select autoscaling *metric* based on service workload profile, and *engine* based on operational requirements

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
- Shipping-rate-service should show the clearest non-CPU separation: H3/K1 are expected to dominate H1/H2 when wait, not CPU, tracks overload
- All methods may cluster more closely for auth-service — proof that CPU works for CPU-bound services
- Product-service can be shown separately as an exploratory contrast where downstream DB saturation can distort or even reverse apparent app-tier autoscaling gains

This is academically impressive (multi-objective optimization vocabulary) and practically useful (a decision-maker can pick their cost-performance preference).

### Strategy 3: Annotated Scaling Timeline Visualization

For the most interesting runs (spike load pattern, shipping-rate-service), create synchronized multi-panel time-series showing ALL 4 autoscaling methods on the same chart:

```
Panel 1: Incoming RPS (from k6) — same for all
Panel 2: Active Pod Count — 4 overlaid lines (H1, H2, H3, K1)
Panel 3: p95 Latency — 4 overlaid lines
Panel 4: CPU Utilization — 4 overlaid lines
```

The visual story becomes undeniable:
- **H1/H2 lines** (blue): Pod count stays at 1. CPU stays at 25%. Latency explodes to 3000ms. HPA never triggers.
- **H3 line** (orange): Pod count increases at t=135s. Latency recovers by t=155s. HPA + request-rate works.
- **K1 line** (green): Pod count increases at t=130s (5s faster?). Latency recovers by t=150s. KEDA + request-rate works.

An examiner sees this ONE chart and immediately understands the entire thesis. It's the most compelling evidence you can produce.

### Strategy 4: The "Decomposition Table" (Unique Deliverable)

Produce a summary table that no other S1 thesis has:

| Service Type | Metric Effect (H3 vs H1) | Engine Effect (K1 vs H3) | Combined Effect (K1 vs H1) |
|-------------|------------------------|-------------------------|---------------------------|
| Wait-dominant external dependency (shipping) | -60% latency | -10% latency | -65% latency |
| CPU-bound (auth) | -5% latency | -3% latency | -8% latency |

*(Numbers are hypothetical — replace with actual measured values)*

This table answers definitively: "How much improvement comes from the metric? How much from the engine?" No other thesis at this level performs this decomposition.

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

### Phase 3: Experiments (Weeks 11-16)

| Week | Activities | Deliverables |
|------|-----------|-------------|
| 11-12 | Run shipping-rate-service experiments: 90 runs (6 configs × 3 patterns × 5 reps). ~4-5 hours/day over 5-6 days. | 90 raw data files |
| 13-14 | Run auth-service experiments: 90 runs. Same schedule. | 90 raw data files |
| 15 | Review all core-matrix data. Re-run failed/anomalous runs. Prepare product-service exploratory appendix from the earlier calibration findings. | Clean, complete core dataset (180 files) + exploratory appendix notes |
| 16 | Buffer week for unexpected issues, additional re-runs, or extended debugging. | Finalized dataset |

### Phase 4: Analysis & Visualization (Weeks 17-20)

| Week | Activities | Deliverables |
|------|-----------|-------------|
| 17 | Descriptive statistics (mean, median, SD, CI) for all KPIs across all configs. | Summary statistics tables |
| 18 | Statistical testing (Wilcoxon signed-rank: H1 vs H3, H3 vs K1, H1 vs K1). Compute effect sizes. | Significance test results |
| 19 | Pareto frontier computation and cost analysis. Build the decomposition table (metric effect vs engine effect). | Pareto plots, decomposition table |
| 20 | Create annotated timeline visualizations. Create comparison bar charts and recommendation matrix. | All thesis figures |

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

4. **The decomposition table is a unique deliverable.** Quantifying "60% of the improvement comes from the metric, 10% from the engine" is something industry practitioners can directly act on. It's also something examiners have never seen from an S1 student.

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

## 12. Thesis Chapter Outline — Struktur Perancangan Jaringan

This section maps every BAB and sub-section from your university's "Perancangan Jaringan" thesis structure to the specific content from this blueprint. Use this as your writing guide — when you sit down to write a section, this tells you exactly what goes there.

---

### BAB 1 PENDAHULUAN

#### 1.1 Latar Belakang

**What to write:** Build the narrative in this order:

1. **Microservices adoption is growing** — organizations are migrating from monolithic architectures to microservices for scalability and independent deployment (cite 2-3 industry reports or papers).

2. **Kubernetes is the standard orchestration platform** — it automates deployment, scaling, and management of containerized applications. HPA (Horizontal Pod Autoscaler) is Kubernetes' built-in autoscaling mechanism (cite Kubernetes documentation, 1-2 papers).

3. **The problem: HPA uses CPU as default scaling metric** — but not all microservices maintain a stable relationship between CPU usage and user-perceived load. Strongly I/O-bound services can be overloaded while CPU stays low, while mixed DB-backed services may still keep enough CPU correlation for HPA to remain partly effective. This is the broader "metric-to-workload fit" problem.

4. **KEDA as an alternative** — KEDA (Kubernetes Event-Driven Autoscaling) is a CNCF graduated project that enables scaling based on event sources including HTTP request rate via Prometheus. It addresses the metric mismatch by using application-level signals instead of resource-level signals.

5. **The research gap** — few studies compare HPA and KEDA on real applications with controlled methodology. Even fewer isolate WHETHER the improvement comes from the metric type or the autoscaling engine itself. This thesis addresses that gap using a controlled factorial experiment design.

6. **Why this matters** — choosing the wrong autoscaling strategy wastes cloud resources (over-provisioning) or degrades user experience (under-provisioning). A systematic comparison helps practitioners make informed decisions.

**Length:** 2-3 pages.

#### 1.2 Rumusan Masalah

**What to write:** 3 research questions derived from the gap:

1. Bagaimana perbandingan responsivitas (p95 latency, error rate, time-to-scale) antara penskalaan berbasis CPU (HPA) dan penskalaan berbasis request rate (KEDA) pada layanan microservices dengan karakteristik beban yang berbeda, yaitu wait-dominant external dependency dan CPU-dominant?

2. Seberapa besar kontribusi relatif dari jenis metrik (CPU vs request rate) dibandingkan dengan arsitektur engine autoscaling (HPA vs KEDA) terhadap efektivitas penskalaan, diuji melalui desain faktorial terkontrol dengan HPA + custom metric (prometheus-adapter) sebagai variabel kontrol?

3. Bagaimana trade-off antara biaya resource dan performa (Pareto frontier) pada masing-masing konfigurasi autoscaling untuk kedua jenis layanan?

#### 1.3 Hipotesis (Skripsi penelitian)

**What to write:**

1. Pada auth-service yang CPU-dominant, penskalaan berbasis CPU (H1 dan H2) diperkirakan tetap kompetitif karena CPU berkorelasi kuat dengan beban bcrypt. Pada shipping-rate-service yang wait-dominant, penskalaan berbasis request rate (H3 dan K1) diperkirakan mengungguli H1 dan H2 karena beban utama berasal dari waktu tunggu terhadap dependency eksternal, bukan dari komputasi lokal.

2. Jenis metrik (CPU vs request rate) memberikan kontribusi yang lebih besar terhadap peningkatan responsivitas dibandingkan arsitektur engine autoscaling (HPA vs KEDA).

3. Terdapat konfigurasi autoscaling yang Pareto-optimal (biaya terendah untuk performa tertinggi), dan konfigurasi tersebut berbeda tergantung karakteristik beban layanan.

#### 1.4 Ruang Lingkup

**What to write:** Summarize from blueprint Section 3 (Scope Definition):
- Platform: Azure Kubernetes Service (AKS), Free Tier, Southeast Asia region
- Cluster: 3× Standard_D4as_v5 (4 vCPU, 16GB RAM each)
- Application: E-commerce microservices extended with one thesis-specific `shipping-rate-service` as the wait-dominant comparison workload
- Services under test (core matrix): shipping-rate-service (wait-dominant), auth-service (CPU-dominant)
- Exploratory appendix service: product-service (mixed read-heavy / DB-backed, dependency-limited in current AKS regime)
- Autoscaling methods: HPA (CPU), HPA (request-rate via prometheus-adapter), KEDA (request-rate via Prometheus scaler)
- Baselines: Fixed 1 replica, Fixed 5 replicas
- Load patterns: Gradual ramp, Sudden spike, Oscillating
- Exclusions: Cluster Autoscaler, VPA, memory-based HPA, scale-to-zero, all 5 services simultaneously

#### 1.5 Tujuan dan Manfaat

**What to write:**

**Tujuan:**
1. Mengukur dan membandingkan responsivitas HPA (CPU-based) dan KEDA (request-rate-based) pada layanan microservices dengan karakteristik beban yang berbeda.
2. Mengisolasi kontribusi jenis metrik vs arsitektur engine autoscaling terhadap efektivitas penskalaan melalui desain eksperimen faktorial terkontrol.
3. Menganalisis trade-off biaya-performa dan mengidentifikasi konfigurasi Pareto-optimal untuk setiap jenis layanan.

**Manfaat:**
- *Praktis:* Memberikan panduan bagi DevOps/SRE dalam memilih strategi autoscaling berdasarkan karakteristik beban layanan.
- *Akademis:* Mengisi gap penelitian tentang perbandingan terkontrol antara reactive dan event-driven autoscaling pada aplikasi cloud-native.

#### 1.6 Metode Penelitian

**What to write:** Brief summary (1 paragraph, details in BAB 3):
- Metode: Eksperimental kuantitatif dengan desain faktorial terkontrol
- Teori: dari BAB 2 (Kubernetes autoscaling, KEDA, Prometheus metrics)
- Penerapan: dibahas mendetail di BAB 3
- Reference the 6-config × 3-pattern × 5-rep × 2-service core design (180 runs), plus a separate exploratory appendix for product-service calibration findings

#### 1.7 Sistematika Penulisan

**What to write:** Standard table of contents summary — 1 paragraph per BAB explaining what it covers.

---

### BAB 2 TINJAUAN REFERENSI

#### 2.1 Teori yang Berkaitan dengan Jaringan

##### 2.1.1 Teori Jaringan Komputer → **Teori Container Orchestration dan Kubernetes**

**What to write:**
- Container technology (Docker): what it is, how it isolates processes, image model
- Kubernetes architecture: control plane (API server, scheduler, controller-manager, etcd), data plane (kubelet, kube-proxy, container runtime)
- Key concepts: Pod, Deployment, Service, Namespace, ReplicaSet
- How Kubernetes manages containerized applications at scale
- **Length:** 2-3 pages with architecture diagram

##### 2.1.2 Teori OSI dan TCP/IP Layers → **Teori Komunikasi Antar-Service pada Kubernetes**

**What to write:**
- Kubernetes networking model: every Pod gets its own IP, pods can communicate directly
- Service types: ClusterIP, NodePort, LoadBalancer
- DNS-based service discovery in Kubernetes (CoreDNS)
- How HTTP/REST communication works between microservices (gateway → services, product-service → PostgreSQL, shipping-rate-service → mock carrier endpoints)
- Network policies and traffic flow within a cluster
- **Length:** 1-2 pages

##### 2.1.3 Teori Protokol yang Digunakan → **Teori Protokol HTTP/REST, Prometheus, dan Kubernetes API**

**What to write:**
- HTTP/REST: the protocol your microservices use for inter-service communication
- Prometheus scraping protocol: how Prometheus pulls metrics via HTTP GET to `/metrics` endpoint
- Kubernetes API: how HPA and KEDA interact with the API server to read metrics and adjust replica counts
- Custom Metrics API: how prometheus-adapter bridges Prometheus metrics into the Kubernetes metrics pipeline
- **Length:** 1-2 pages

##### 2.1.4 Teori Devais yang Digunakan → **Teori Virtual Machine dan Node pada Cloud Kubernetes**

**What to write:**
- Azure Virtual Machines: what D-series VMs are, vCPU vs physical CPU, non-burstable vs burstable (B-series)
- Specifically: Standard_D4as_v5 specifications (4 vCPU, 16GB RAM, AMD EPYC, ephemeral OS disk)
- Why non-burstable VMs are critical for benchmarking (B-series credit system would invalidate CPU measurements)
- AKS node pools: how Kubernetes maps VMs to nodes, allocatable vs total resources (kubelet + system reservation)
- **Length:** 1-2 pages with specification table

##### 2.1.5 Teori dan Metode Perancangan Jaringan → **Teori Perancangan Arsitektur Kubernetes Cluster**

**What to write:**
- How to design a Kubernetes cluster: node sizing methodology (resource requests + limits + system overhead)
- Resource management concepts: requests vs limits, QoS classes (Guaranteed, Burstable, BestEffort)
- Capacity planning: calculating total allocatable CPU/memory, headroom for burst traffic
- AKS-specific design considerations: Free tier vs Standard, node OS disk types, network plugin selection
- **Length:** 1-2 pages

##### 2.1.6 Teori dan Metode Analisis untuk Menganalisis Hasil Pengukuran → **Metode Analisis Statistik**

**What to write:**
- Descriptive statistics: mean, median, standard deviation, percentiles (p50, p95, p99)
- Confidence intervals: 95% CI interpretation for experimental measurements
- Non-parametric significance testing: Wilcoxon signed-rank test — why non-parametric (can't assume normal distribution of latency data), how it works, when to reject H0
- Effect size measurement: how to quantify the magnitude of difference (not just "is it significant" but "how much")
- Multi-objective optimization: Pareto frontier definition, dominance relation, how to identify Pareto-optimal configurations
- **Length:** 2-3 pages (this is critical methodology — examiners will scrutinize this)

##### 2.1.7 Teori dan Metode Fact Finding → **Studi Literatur dan Identifikasi Masalah**

**What to write:**
- Literature review methodology: how you searched for prior studies (keywords, databases, selection criteria)
- Key findings from literature: HPA limitations documented in prior work, KEDA studies, autoscaling comparison papers
- Gap identification: what prior studies covered (HPA tuning, KEDA features) vs what they missed (controlled factorial comparison, metric-type isolation, cost analysis)
- **Length:** 1-2 pages

##### 2.1.8 Teori dan Metode Pengukuran dan Tools → **Tools Pengukuran dan Monitoring**

**What to write (detailed per tool):**

**k6 (Load Testing Tool):**
- What it is: open-source load testing tool by Grafana Labs
- How it works: scenario-based testing with JavaScript, supports ramping-arrival-rate, constant-arrival-rate
- Metrics it produces: `http_req_duration`, `http_req_failed`, `http_reqs`, `vus`
- Why chosen: runs as Kubernetes Job (in-cluster), eliminates network variance, scriptable

**Prometheus (Metrics Collection):**
- What it is: CNCF graduated time-series database for monitoring
- How it works: pull-based scraping at configurable intervals (15s)
- Key metrics: `container_cpu_usage_seconds_total`, `kube_pod_status_ready`, `kube_deployment_status_replicas`, `http_requests_total`
- PromQL: the query language for aggregating and analyzing metrics

**Grafana (Visualization):**
- What it is: observability platform for dashboards
- How it's used: creating the annotated scaling timeline visualizations (Strategy 3)

**prometheus-adapter:**
- What it is: bridges Prometheus metrics into Kubernetes Custom Metrics API
- Why needed: allows HPA to use request-rate as a scaling metric (H3 config)

**kubectl + metrics-server:**
- What it is: Kubernetes CLI + built-in resource metrics pipeline
- How it's used: monitoring CPU/memory utilization via `kubectl top`

**Length:** 3-4 pages (cover each tool with purpose, mechanism, and role in your experiment)

#### 2.2 Teori yang Terkait Tema Penelitian (Tematik) → **Teori Autoscaling pada Kubernetes**

**What to write:**
- **Horizontal Pod Autoscaler (HPA):**
  - Architecture: metrics-server → API server → HPA controller → deployment
  - Control loop: 15-second default interval
  - Scaling algorithm: `desiredReplicas = ceil(currentReplicas × (currentMetric / desiredMetric))`
  - Metric types: Resource (CPU/memory), Pods (custom), Object (external)
  - Behavior policies: stabilizationWindowSeconds, scaling policies (Pods, Percent)
  - Limitations: reactive only, CPU-centric by default, requires prometheus-adapter for custom metrics

- **KEDA (Kubernetes Event-Driven Autoscaling):**
  - Architecture: KEDA operator → ScaledObject → external event source → deployment
  - How it differs from HPA: event-driven polling, Prometheus scaler reads PromQL directly, scale-to-zero capability
  - ScaledObject specification: triggers, pollingInterval, cooldownPeriod, thresholds
  - Prometheus scaler: how it queries Prometheus and maps results to scaling decisions
  - KEDA as CNCF graduated project: maturity, adoption, AKS native integration

- **Comparison framework:**
  - Reactive (HPA) vs Event-driven (KEDA)
  - Resource metrics vs Application metrics
  - The theoretical basis for why metric type matters for different workload profiles

**Length:** 4-5 pages (this is your core theoretical framework — must be thorough)

#### 2.3 Teori dan Metode Evaluasi yang Digunakan → **Metode Evaluasi Cost-Performance**

**What to write:**
- Resource Cost Index formula: `Σ(active_pods × duration_seconds × cpu_request) × price_per_cpu_second`
- How AKS pricing translates to per-pod-second cost
- Pareto frontier analysis: theory and application to multi-objective optimization
- The decomposition methodology: isolating metric effect (H3 vs H1) from engine effect (K1 vs H3)
- What constitutes a "better" configuration: SLO-based evaluation (e.g., p95 < 500ms AND error rate < 1%)
- **Length:** 2-3 pages

#### 2.4 Studi Hasil Penelitian yang Berkaitan → **Penelitian Terdahulu tentang Autoscaling Kubernetes**

**What to write:**
- Review 5-8 prior studies on Kubernetes autoscaling
- For each: cite, summarize methodology, summarize findings, identify limitations
- Show the gap: no study does all of (a) controlled factorial design, (b) real application, (c) metric-type isolation, (d) cost analysis
- Conclude with how YOUR study addresses each gap
- **Format:** Table comparing prior studies on dimensions: method, application type, metrics compared, statistical rigor, cost analysis
- **Length:** 3-4 pages

---

### BAB 3 METODE PENELITIAN

#### 3.1 Kerangka Berpikir

**What to write:** A visual flowchart showing:

```
[Masalah: CPU-based HPA may misfit services whose CPU weakly correlates with user load]
         ↓
[Pertanyaan: Is it the metric type or the engine?]
         ↓
[Desain: Controlled factorial experiment (2×2 + baselines)]
         ↓
[Implementasi: 6 configs × 3 loads × 5 reps × 2 services = 180 runs]
         ↓
[Pengukuran: Latency, Error Rate, Time-to-Scale, Cost]
         ↓
[Analisis: Statistical tests + Pareto + Decomposition]
         ↓
[Hasil: Metric effect vs Engine effect quantified per workload type]
```

Include 1-2 paragraphs explaining the logical flow. **Length:** 1 page.

#### 3.2 Analisis Masalah

##### 3.2.1 Deskripsi Singkat Mengenai Tempat Penelitian → **Lingkungan Azure Kubernetes Service**

**What to write:**
- Azure Student Subscription: $150/month credit, limitations
- AKS Free Tier: what's included, what limitations exist
- Region: Southeast Asia (closest to Indonesia, lowest latency)
- Cluster specification: 3× Standard_D4as_v5, Ephemeral OS disk, Azure CNI networking
- Why AKS over local (KIND): consistent non-burstable CPU, eliminates laptop variance, realistic multi-node topology
- **Length:** 1 page

##### 3.2.2 Analisis Kebutuhan → **Analisis Kebutuhan Autoscaling pada Aplikasi E-Commerce**

**What to write:**
- The e-commerce application description: the original 5 microservices (auth, product, cart, order, payment), 3 PostgreSQL databases, API gateway, frontend, plus a thesis-specific `shipping-rate-service` for the final controlled non-CPU comparison
- Workload characteristics: variable traffic (browsing peaks, flash sales, idle periods)
- Why autoscaling is needed: fixed replicas either waste resources (over-provisioned) or degrade performance (under-provisioned)
- Specific needs: fast scale-up during traffic spikes, cost-efficient scale-down during idle, different scaling requirements per service type
- **Length:** 1-2 pages

##### 3.2.3 Topologi Saat Ini → **Arsitektur Aplikasi dan Deployment Saat Ini**

**What to write:**
- Current architecture diagram: all 5 services, databases, gateway, monitoring stack (Prometheus, Grafana, Loki)
- Current deployment configuration: `replicas: 1` for all services, no autoscaling
- Current resource requests/limits from your actual deployment YAML files
- Current monitoring setup: Prometheus scrape config, FastAPI instrumentator, existing metrics
- **Include:** architecture diagram showing service communication flow
- **Length:** 2-3 pages with diagrams

##### 3.2.4 Observasi yang Dilakukan Termasuk Pengukuran → **Pengukuran Baseline Tanpa Autoscaling**

**What to write:**
- Pilot test results: what happens to auth-service under load without autoscaling, and why product-service was rejected as the final non-CPU comparison service
- Baseline metrics: p95 latency at 50 RPS, 100 RPS, 200 RPS with fixed 1 replica
- CPU utilization observations: auth-service CPU rises strongly (CPU-dominant evidence), while product-service showed why a DB-sensitive workload can confound app-tier autoscaling analysis and motivated the pivot to a cleaner wait-dominant service
- Resource utilization of infrastructure pods (Prometheus, Grafana, KEDA, prometheus-adapter)
- **Include:** baseline measurement tables and CPU utilization graphs from pilot runs
- **Length:** 2-3 pages with data tables

##### 3.2.5 Identifikasi Masalah

**What to write:**
From observation data (3.2.4), identify:
1. **Masalah 1:** CPU-based HPA cannot be assumed suitable for every service, but the non-CPU comparison service must also be clean enough that the dominant bottleneck remains in the app tier rather than in a downstream dependency.
2. **Masalah 2:** Fixed replicas lead to either wasted resources (over-provisioning) or degraded performance (under-provisioning) — no optimal static configuration exists
3. **Masalah 3:** It is unclear whether the solution is changing the scaling metric (to request rate) or changing the scaling engine (to KEDA) — this needs controlled experimentation
- **Length:** 1 page

##### 3.2.6 Usulan Pemecahan Masalah → **Desain Eksperimen Faktorial Terkontrol**

**What to write:**
- The controlled factorial design: 2×2 matrix (engine × metric) + 2 baselines
- The 6 configurations: B1, B2, H1, H2, H3, K1 — describe each with rationale
- The 3 load patterns: gradual ramp, sudden spike, oscillating — describe each with rationale
- The 2 core services: shipping-rate-service (wait-dominant), auth-service (CPU-dominant) — why these two
- The exploratory appendix case: product-service — why it was excluded from the final core matrix
- Repetitions: 5 per configuration — why 5 (statistical minimum)
- Total: 6 × 3 × 5 × 2 = 180 experiment runs
- **Include:** the factorial matrix diagram from blueprint Section 6
- **Include:** flowchart of the experimental protocol (reset → apply → warm-up → test → cooldown → export)
- **Length:** 3-4 pages

#### 3.3 Perancangan

##### 3.3.1 Rancangan Topologi Jaringan → **Rancangan Arsitektur Kubernetes Cluster**

**What to write:**
- AKS cluster topology diagram: 3 nodes, pod placement strategy
- Node specification: D4as_v5 with resource calculations (total allocatable: 11580m CPU, overhead breakdown)
- Pod placement: where each component runs (monitoring on which node, app pods distributed, k6 Job)
- Resource budget table: total CPU requests vs allocatable per node (from blueprint Section 4)
- **Include:** cluster architecture diagram showing all 3 nodes with pod distribution
- **Length:** 2-3 pages with diagrams and resource tables

##### 3.3.2 Rancangan Distribusi IP → **Rancangan Kubernetes Networking**

**What to write:**
- AKS networking: Azure CNI plugin, VNet configuration
- Pod CIDR and Service CIDR allocation
- How services discover each other: ClusterIP + DNS (e.g., `product-service.ecommerce.svc.cluster.local`, `shipping-rate-service.ecommerce.svc.cluster.local`)
- Internal communication paths: k6 → service (in-cluster, no LoadBalancer needed), service → PostgreSQL or mock carrier endpoint (internal DNS), KEDA → Prometheus (cross-namespace)
- Port mappings for each service
- **Length:** 1-2 pages with network diagram

##### 3.3.3 Rancangan yang Berkaitan dengan Topik Skripsi → **Rancangan Konfigurasi Autoscaling**

**What to write (this is the longest and most important section of BAB 3):**

**A. Rancangan Konfigurasi HPA Default (H1):**
- Full YAML manifest with explanation of each field
- `targetCPU: 70%`, default behavior policy, why these values

**B. Rancangan Konfigurasi HPA Tuned (H2):**
- Full YAML manifest with explanation
- `targetCPU: 50%`, aggressive scaling behavior — explain `stabilizationWindowSeconds: 0`, why aggressive

**C. Rancangan Konfigurasi HPA Custom Metric (H3):**
- prometheus-adapter rules ConfigMap — full YAML with explanation
- HPA manifest using `type: Pods` with `http_requests_per_second`
- Explain the adapter pipeline: Prometheus → prometheus-adapter → Custom Metrics API → HPA

**D. Rancangan Konfigurasi KEDA (K1):**
- ScaledObject manifest — full YAML with explanation
- Explain: `pollingInterval: 15` to match HPA, `cooldownPeriod: 30`, the PromQL query

**E. Rancangan Baseline (B1 dan B2):**
- B1: Fixed `replicas: 1` — explain as lower bound
- B2: Fixed `replicas: 5` — explain as upper bound

**F. Rancangan Load Test (k6):**
- k6 Job YAML manifest with resource requests
- k6 test script structure: `setup()` for token pooling, weighted scenario distribution
- 3 load pattern configurations: ramping-arrival-rate (gradual), constant-arrival-rate (spike), multi-stage (oscillating)

**G. Rancangan Threshold Calibration:**
- Calibration procedure: how H3 and K1 thresholds are set to the same value
- Why calibration is critical for the H3 vs K1 comparison fairness

**Length:** 6-8 pages with all YAML manifests and explanations. All YAML is already in blueprint Section 6 — copy and add Indonesian explanations.

---

### BAB 4 HASIL DAN PEMBAHASAN

#### 4.1 Spesifikasi Devais yang Digunakan → **Spesifikasi Sistem**

**What to write:**

| Komponen | Spesifikasi |
|----------|------------|
| Cloud Platform | Azure Kubernetes Service (AKS), Free Tier |
| Region | Southeast Asia |
| Node VM | Standard_D4as_v5 (4 vCPU AMD EPYC, 16GB RAM, Ephemeral OS Disk) |
| Node Count | 3 |
| Kubernetes Version | (version used) |
| Container Runtime | containerd |
| Network Plugin | Azure CNI |
| KEDA Version | (version used, AKS add-on) |
| prometheus-adapter Version | (Helm chart version) |
| Prometheus Version | (version used) |
| k6 Version | (version used) |
| Application Framework | Python FastAPI |
| Database / downstream dependencies | PostgreSQL (in-cluster) + mock carrier/downstream endpoints for shipping-rate-service |

**Length:** 1-2 pages

#### 4.2 Konfigurasi Devais → **Implementasi Konfigurasi Autoscaling**

**What to write:**
- AKS cluster creation command (`az aks create ...`) and verification
- KEDA installation (`az aks update --enable-keda`) and verification
- prometheus-adapter installation (Helm) and verification (`kubectl get --raw ...`)
- All deployed YAML configurations with narration for each section:
  - H1 HPA manifest → show `kubectl apply` → show `kubectl get hpa` output
  - H2 HPA manifest → show the behavior policy differences
  - H3 HPA manifest → show custom metric working (`TARGETS` column shows values)
  - K1 ScaledObject → show `kubectl get scaledobject` → show `READY: True`
  - prometheus-adapter config → show registered custom metrics
  - k6 Job configuration → show resource requests
  - Monitoring pods resource requests → show the fix applied
- **Approach:** For each configuration, show the YAML, then show the `kubectl` verification output proving it works. This follows the template's instruction: "Pendekatan dengan menggunakan script konfigurasi lebih direkomendasikan."
- **Length:** 5-8 pages (heavy on configuration scripts and verification output)

#### 4.3 Simulasi → **Eksekusi Load Test**

**What to write:**
- Simulation environment description: how k6 runs inside the cluster, how load patterns map to k6 stages
- Execution protocol: the 8-step procedure (reset → apply → stabilize → warm-up → test → cooldown → export → next)
- Execution log: summary of 180 runs — how many sessions, hours per session, dates, any anomalies encountered
- Example raw output: show a sample k6 summary output for one run (what the terminal looks like after a test completes)
- Data collection: how Prometheus data is exported (PromQL queries used, JSON/CSV format), how k6 results are stored
- **Use real data from your actual experiments** — this cannot be written before experiments
- **Length:** 3-4 pages

#### 4.4 Hasil Implementasi dan Pengukuran → **Hasil Eksperimen 180 Run**

**What to write:** This is the RAW RESULTS section — present data before analysis.

**For each core service (shipping-rate-service, then auth-service):**

**Table format for each configuration × load pattern combination:**

| Konfigurasi | Load Pattern | p95 Latency (ms) | Error Rate (%) | Time-to-Scale (s) | Resource Cost Index ($) | Scaling Events |
|-------------|-------------|-------------------|----------------|-------------------|------------------------|----------------|
| B1 (Fixed 1) | Gradual | mean ± SD | mean ± SD | N/A | mean ± SD | 0 |
| B1 (Fixed 1) | Spike | mean ± SD | mean ± SD | N/A | mean ± SD | 0 |
| ... | ... | ... | ... | ... | ... | ... |
| K1 (KEDA) | Oscillating | mean ± SD | mean ± SD | mean ± SD | mean ± SD | mean ± SD |

- Include 95% confidence intervals
- Include the annotated scaling timeline visualizations (Strategy 3) for 3-5 most interesting runs
- Show the synchronized multi-panel charts: RPS, Pod Count, p95 Latency, CPU — with H1/H2/H3/K1 overlaid
- **Length:** 8-12 pages (tables + figures — this is the heaviest section)

#### 4.5 Analisis Perbandingan → **Analisis Komparatif HPA vs KEDA**

**What to write:** This is the ANALYSIS section — interpret the data.

**A. Perbandingan Langsung (H1/H2 vs K1):**
- For each load pattern × service combination: which method performed better on each KPI?
- Statistical significance: Wilcoxon signed-rank test results (p-values, reject/accept H0)
- Effect sizes: how large is the difference?

**B. Isolasi Faktor — Dekomposisi (the unique deliverable):**

| Service Type | Metric Effect (H3 vs H1) | Engine Effect (K1 vs H3) | Combined Effect (K1 vs H1) |
|-------------|------------------------|-------------------------|---------------------------|
| shipping-rate-service | measured improvement | measured improvement | measured improvement |
| auth-service | measured improvement | measured improvement | measured improvement |

- Interpret: "X% of the improvement comes from the metric type, Y% from the engine"
- Discuss what this means practically

**C. Perbandingan per Load Pattern:**
- Which autoscaling method handles gradual ramp best? Spike? Oscillating?
- Does one method show more stability (fewer scaling events) during oscillating loads?

**D. Perbandingan per Service Type:**
- Confirm or refute the hypothesis: request-rate scaling is strongest when CPU weakly correlates with load, while HPA-CPU remains strongest for clearly CPU-bound services
- What does the crossover look like? Is there a service type where HPA-CPU is actually *better* than KEDA?

**Length:** 5-7 pages with comparison tables and statistical test results

#### 4.6 Analisis Evaluasi → **Evaluasi Cost-Performance dan Rekomendasi**

**What to write:**

**A. Pareto Frontier Analysis:**
- The Pareto plot (Strategy 2): Cost vs Latency scatterplot with Pareto frontier drawn
- Identify which configurations are Pareto-optimal for each service type
- Interpret: "For shipping-rate-service, K1 and H3 dominate. For auth-service, H2 and K1 are comparable."

**B. Recommendation Matrix:**

| Workload Type | Recommended Autoscaling | Recommended Metric | Why |
|--------------|------------------------|--------------------|----|
| Downstream dependency-limited (DB or external dependency is the dominant bottleneck) | Scale the dependency first; app-tier HPA/KEDA choice becomes secondary | Dependency-specific metrics, queue depth, DB saturation | Scaling the wrong tier can worsen outcomes even if the autoscaler reacts correctly |
| Wait-dominant external dependency | KEDA or HPA + custom metric | Request rate | CPU no longer reflects overload well, while request arrival still tracks concurrent waiting work |
| CPU-bound (crypto, compression) | HPA (default) | CPU | CPU correlates with load, simpler setup |
| Mixed read-heavy / DB-backed | KEDA or HPA + custom metric preferred, but validate HPA empirically | Usually request rate | CPU may still retain signal, so the correct choice depends on measured workload regime |

**C. Evaluation Against User Needs (from 3.2.2):**
- Does autoscaling meet the fast scale-up requirement? → Compare time-to-scale across methods
- Does autoscaling meet cost efficiency? → Compare Resource Cost Index vs baseline
- Which configuration best balances both? → Point to Pareto frontier

**Length:** 4-5 pages with Pareto plots and recommendation table

---

### BAB 5 SIMPULAN DAN SARAN

#### 5.1 Simpulan

**What to write:**
- Answer each research question from 1.2 with data:
  1. "Perbandingan menunjukkan bahwa K1 (KEDA) memiliki p95 latency X% lebih rendah dari H1 (HPA-CPU) pada shipping-rate-service (p < 0.05), sementara pada auth-service perbedaan tidak signifikan (p = Y)."
  2. "Dekomposisi menunjukkan bahwa Z% peningkatan berasal dari jenis metrik dan W% dari arsitektur engine."
  3. "Konfigurasi Pareto-optimal untuk layanan wait-dominant external dependency adalah [hasil aktual: kemungkinan H3/K1], sedangkan untuk CPU-bound adalah [H2 atau hasil aktual], berdasarkan analisis trade-off biaya-performa. Temuan product-service dilaporkan terpisah sebagai kasus dependency-limited."
- Confirm or refute each hypothesis from 1.3
- **Critical rule from template:** "Tidak boleh membuat kesimpulan hanya berisi sistem yang telah berjalan tanpa memberikan bukti data yang kuat." → Every conclusion must reference specific measured values and statistical test results.
- **Length:** 1-2 pages

#### 5.2 Saran

**What to write:**

**Saran untuk Praktisi:**
- Use request-rate-based scaling (KEDA or HPA + custom metric) when CPU is shown empirically to be a weak proxy for load
- CPU-based HPA is sufficient for CPU-bound services and may still be acceptable for some mixed workloads
- Consider operational complexity: KEDA requires less configuration for request-rate scaling than HPA + prometheus-adapter

**Saran untuk Penelitian Selanjutnya:**
1. Penambahan Vertical Pod Autoscaler (VPA) sebagai variabel perbandingan
2. Pengujian fitur scale-to-zero pada KEDA dan dampaknya terhadap cold-start latency
3. Perbandingan pada platform cloud lain (GKE, EKS) untuk validasi generalizability
4. Penggunaan predictive/ML-based autoscaling sebagai alternatif reactive scaling
5. Pengujian pada domain aplikasi lain (streaming, batch processing, ML inference)

**Length:** 1 page
