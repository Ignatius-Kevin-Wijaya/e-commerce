# Critical Analysis: Thesis Outline on HPA Performance

**Thesis**: *Analisis Performa Horizontal Pod Autoscaler (HPA) terhadap Stabilitas dan Efisiensi Resource pada Aplikasi Cloud-Native Berbasis Kubernetes*

**Reviewer context**: I have read the full outline AND inspected your actual codebase — the 5-service e-commerce app (auth, product, cart, order, payment), KIND cluster config (1 control-plane + 2 workers), existing k6 load test script, Prometheus/Grafana monitoring stack, Loki for logging, and your HPA manifests (currently `minReplicas: 2`, `maxReplicas: 10`, `targetCPU: 70%`).

---

## 1. Overall Evaluation

**Rating: 6.5 / 10**
**Classification: "Good for an average S1 thesis, but not yet high-quality or publishable"**

### Why this score:

**Strengths:**
- The research questions are well-formulated and clearly scoped
- The KPI structure (stability / efficiency / scaling behavior) is organized and measurable
- You have a real, working application — not a toy `nginx` benchmark. This immediately puts you above many S1 theses
- Acceptable thresholds are defined upfront (p95 ≤ 400ms, error ≤ 2%, etc.), which is surprisingly mature for an S1 outline
- The bibliography includes recent, relevant papers (2020–2024)

**Why it's not higher:**
- The experiment design is essentially **"HPA on vs HPA off"** — this is a *demonstration*, not a *research contribution*
- Only one metric type (CPU) is tested. Everyone knows CPU-based HPA works. The result is predictable.
- No statistical rigor is mentioned (no repeated trials, no confidence intervals, no hypothesis testing)
- The "konfigurasi optimal" claim in the objectives is not supported by the methodology — testing 3 threshold values is parameter sweeping, not optimization
- The load test scenarios are too simplistic (ramp up → sustain → ramp down). Real-world patterns are far more complex.

---

## 2. Critical Weakness Analysis

### Weakness 1: Predictable Results (Fatal for Novelty)

**Problem**: Comparing "HPA on" vs "HPA off" (fixed replicas) under load will *obviously* show that HPA improves performance under variable load. This is a known outcome documented in Kubernetes documentation itself.

**Risk**: During defense, the examiner will ask: *"What new knowledge does this thesis produce?"* You will struggle to answer. The thesis reads like a tutorial validation, not a research contribution.

**Severity**: 🔴 **Critical** — this is the single biggest weakness.

---

### Weakness 2: No Statistical Rigor

**Problem**: The outline mentions no:
- Number of trial repetitions per scenario
- Statistical tests (t-test, Mann-Whitney U, ANOVA)
- Confidence intervals or standard deviations
- Warm-up / cool-down periods to avoid measurement artifacts

**Risk**: Any examiner with quantitative research training will immediately flag this. Running a load test once and reporting the numbers is **anecdotal evidence**, not empirical research. One run could be influenced by background processes, garbage collection, or network jitter.

**Severity**: 🔴 **Critical** — undermines the entire "eksperimen kuantitatif" claim.

---

### Weakness 3: Shallow Variable Space

**Problem**: You vary only one independent variable — CPU threshold (50%, 70%, 80%). This produces a maximum of 3 data points per scenario per metric. That is not enough to draw meaningful conclusions about "optimal configuration."

**What's missing as independent variables**:
- `minReplicas` / `maxReplicas` variations
- Scaling behavior policies (`stabilizationWindowSeconds`, `scaleDown` / `scaleUp` speed)
- Different workload patterns (not just gradual and spike, but also oscillating, diurnal, bursty)
- Different services under test (product-service vs order-service may behave very differently due to DB write patterns)

**Risk**: The "menentukan konfigurasi HPA yang optimal" objective cannot be fulfilled with 3 data points. An examiner will challenge whether 3 thresholds constitute meaningful optimization.

**Severity**: 🟡 **Major**

---

### Weakness 4: Load Test Design Is Too Simplistic

**Problem**: Your current k6 script only hits `/health` and `GET /api/v1/products`. This is:
- Read-only (no write operations)
- Stateless (no session/auth flow)
- Unrealistic (real e-commerce traffic involves browsing → cart → checkout → payment)

A CPU-heavy operation like writing orders with stock validation and payment processing would put *fundamentally different* pressure on the system than a simple GET request.

**Risk**: The thesis claims to test a "microservices e-commerce app" but actually only tests a single GET endpoint. The results won't generalize to the actual application's behavior. During defense: *"Why didn't you test the checkout flow that actually stresses the system?"*

**Severity**: 🟡 **Major**

---

### Weakness 5: The HPA Config in Your Codebase Contradicts the Outline

**Problem**: Your actual HPA manifest uses `minReplicas: 2, maxReplicas: 10, targetCPU: 70%`, but your outline says `minReplicas: 1, maxReplicas: 5, targetCPU: 50%/70%/80%`. This inconsistency suggests the experiment design hasn't been reconciled with the actual implementation.

More importantly, your outline's `maxReplicas: 5` on a 2-worker KIND cluster may hit node resource limits before reaching max pods — this introduces a confounding variable (node resource exhaustion vs. HPA behavior).

**Risk**: If HPA wants to scale to 5 pods but the nodes can't schedule them, you're measuring node capacity, not HPA effectiveness.

**Severity**: 🟡 **Major** — must be addressed in experiment design.

---

### Weakness 6: No Consideration of HPA's Internal Mechanics

**Problem**: The outline treats HPA as a black box. There's no mention of:
- The HPA control loop interval (default: 15 seconds)
- The algorithm HPA uses (desired replicas = ceil[currentReplicas × (currentMetricValue / desiredMetricValue)])
- `--horizontal-pod-autoscaler-downscale-stabilization` (default: 5 minutes)
- How metric collection lag affects scaling decisions

**Risk**: Without understanding *why* HPA makes certain decisions, your analysis will be purely descriptive ("X happened") instead of explanatory ("X happened *because* of Y mechanism"). Explanatory analysis is what separates good research from mere observation.

**Severity**: 🟡 **Moderate**

---

## 3. Scope Evaluation

### Verdict: **Narrow AND Shallow**

The scope is narrow (only HPA, only CPU, only one app) — which *could* be fine if the depth compensated. But it doesn't. Here's the distinction:

| Aspect | Current State | "Narrow but Deep" Would Be |
|--------|--------------|---------------------------|
| Metrics | CPU only | CPU + memory + custom metrics comparison |
| Thresholds | 3 values (50/70/80%) | Systematic sweep with fine granularity (40–90%, step 5%) |
| Scenarios | 2 patterns | 4–5 patterns including oscillating, diurnal, burst |
| Statistical design | Not mentioned | ≥5 trials per config, statistical tests, CI |
| Analysis type | Descriptive | Explanatory (correlate HPA algorithm behavior with observed metrics) |
| Scaling policies | Default only | Compare different `stabilizationWindow` and `scaling.behavior` configs |

### What's missing that reduces quality:

1. **No "why" analysis** — you report that scaling time was X seconds but never analyze *why* (was it the HPA loop interval? Pod startup time? Readiness probe delay?). Your deployment has `initialDelaySeconds: 5` for readiness — this directly affects scaling time but is never discussed.

2. **No service-level differentiation** — you have 5 distinct services with different resource profiles (auth is lightweight, order has DB writes + inter-service calls). Testing only one service wastes the richness of your architecture.

3. **No sensitivity analysis** — how sensitive are your results to resource requests/limits? Your deployment uses `cpu: 100m request / 500m limit`. Changing these would fundamentally alter HPA behavior, but this isn't explored.

---

## 4. Environment Design Decision: Local (KIND) vs Cloud (AKS)

### Verdict: **CONDITIONAL — Include only if you design it correctly, otherwise exclude.**

### Arguments FOR including cloud:

| Factor | Impact |
|--------|--------|
| Research validity | Significantly increases external validity. KIND runs on Docker-in-Docker with shared host resources — performance characteristics are fundamentally different from cloud VMs with dedicated compute |
| Practical relevance | HPA is primarily used in cloud. Testing only locally limits applicability |
| Thesis differentiation | Most S1 theses test only locally. Cloud testing immediately elevates quality |

### Arguments AGAINST:

| Factor | Impact |
|--------|--------|
| Fairness of comparison | KIND and AKS are *not comparable*. Different networking (KIND uses host network, AKS uses Azure CNI), different storage, different scheduler behavior. A direct comparison is scientifically invalid unless you very carefully control for these differences |
| Complexity | AKS adds cost management, Terraform provisioning, image registry setup, networking config — significant engineering overhead |
| Budget | AKS costs real money for sustained load testing |

### If you INCLUDE it — proper design:

> [!IMPORTANT]
> Do NOT frame it as "KIND vs AKS performance comparison." That comparison is meaningless because the infrastructure is fundamentally different.

Instead, frame it as:

**"Evaluating HPA effectiveness across two deployment environments"**

- The research question becomes: *Does HPA provide similar relative improvements (HPA-on vs HPA-off) regardless of the underlying infrastructure?*
- Report **relative metrics** (% improvement from baseline), not absolute numbers
- Ensure identical: HPA config, app images, load patterns, resource requests/limits
- Clearly document: node specs (CPU/memory), Kubernetes version, CNI, metrics-server version

### If you EXCLUDE it — justification:

Write something like:

> *"This research focuses on evaluating HPA's scaling behavior and effectiveness in a controlled single-cluster environment. Cloud provider-specific factors (network topology, multi-zone scheduling, cloud-native metrics services) introduce additional variables that are outside the scope of this study. The controlled local environment ensures reproducibility and isolates HPA behavior from infrastructure-level variability. Extension to managed Kubernetes environments is identified as future work."*

### My recommendation:

**Exclude cloud for the main experiment. Include it as a brief validation chapter if time permits.** Reason: the engineering overhead of properly setting up AKS with fair comparison methodology will consume weeks that are better spent improving your experiment's statistical rigor and depth.

---

## 5. Autoscaling Scope Decision: Cluster Autoscaler

### Option A: Exclude (Recommended ✅)

**Impact**:
- **Realism**: Low — in production, Cluster Autoscaler and HPA work together. Excluding it means your results don't reflect real-world conditions.
- **Experimental clarity**: High — you isolate HPA behavior completely. If pods can't be scheduled because nodes are full, that's a clear confounding variable eliminated.
- **Complexity**: Minimal addition.

**How to justify**: *"Cluster Autoscaler adds node-level provisioning latency (2-5 minutes for cloud) which introduces infrastructure-level variability unrelated to HPA's pod-level scaling decisions. To isolate HPA behavior, the cluster is pre-provisioned with sufficient node capacity to accommodate maximum replica count."*

**Critical requirement**: You MUST ensure your KIND cluster has enough resources for `maxReplicas` across all HPA-enabled services. Calculate: if you test product-service with `maxReplicas: 5` at `500m CPU limit` each, you need at least 2500m CPU available on worker nodes. Your 2-worker KIND cluster runs on your local machine — verify Docker's resource allocation.

### Option B: Controlled (Acceptable but adds complexity)

If you set up AKS, Cluster Autoscaler is nearly unavoidable. In that case:
- Fix node pool to a specific count (disable Cluster Autoscaler)
- Document the fixed node count and specs
- This effectively becomes the same as "excluded"

### Option C: Include as Variable (Not recommended for S1)

Adding Cluster Autoscaler as a variable doubles your experiment matrix. You'd need:
- HPA off + CA off (baseline)
- HPA on + CA off
- HPA off + CA on
- HPA on + CA on

This is a full factorial design that could be excellent for a Master's thesis but is likely too much for S1.

---

## 6. How to Improve (Actionable)

### ADD ✅

1. **Statistical rigor**: Run each experiment configuration **minimum 5 times**. Report mean, standard deviation, and 95% confidence intervals. Perform paired t-tests (or Wilcoxon signed-rank for non-normal distributions) to determine if differences are statistically significant.

2. **Realistic load patterns**: Rewrite your k6 script to include a **complete user journey**:
   ```
   Browse products → View product detail → Add to cart → Checkout → Payment
   ```
   Weight the scenarios: 70% browse, 20% add-to-cart, 10% checkout. This creates a realistic mixed workload where different services are stressed differently.

3. **Scaling behavior policies as a variable**: Test at least 2 HPA behavior configurations:
   - Default behavior (conservative downscale with 5-min stabilization)
   - Aggressive downscale (`stabilizationWindowSeconds: 30`, `policies: [{type: Percent, value: 100, periodSeconds: 15}]`)
   
   This instantly doubles your contribution and lets you recommend specific `behavior` configs, not just threshold values.

4. **Pod startup time decomposition**: Break down scaling time into:
   - Time from metric threshold breach → HPA decision
   - Time from HPA decision → pod scheduled
   - Time from pod scheduled → container running
   - Time from container running → readiness probe passed
   
   This transforms your analysis from "scaling took 25 seconds" to "scaling took 25 seconds because readiness probe has 5s initial delay + 10s period, and container pull took 8 seconds."

5. **A "cost model" section**: Define a simple cost function: `Cost = (total_pod_seconds × resource_request)`. Compare the "cost" of baseline (fixed high replicas) vs HPA across scenarios. This gives your thesis a practical dimension.

### REMOVE ❌

1. **Remove or rephrase the "konfigurasi optimal" claim** unless you're doing proper optimization. Replace with: *"Mengidentifikasi pengaruh variasi konfigurasi HPA terhadap keseimbangan antara stabilitas dan efisiensi resource."*

2. **Remove "throughput" from KPI list if you're controlling RPS**. If you're sending a fixed number of requests per second, throughput is your *input* (independent variable), not a KPI (dependent variable). What you actually want to measure is **successful throughput vs attempted throughput** (i.e., effective throughput ratio).

### MODIFY 🔄

1. **Modify your baseline**: Don't use `replicas: 1` as baseline. Use two baselines:
   - **Under-provisioned baseline**: `replicas: 1` (simulates a system without scaling)
   - **Over-provisioned baseline**: `replicas: maxReplicas` (simulates "just throw resources at it")
   - **HPA**: dynamic scaling

   This three-way comparison is far more informative. It shows both that HPA improves on under-provisioning AND that HPA is more efficient than over-provisioning.

2. **Modify acceptable parameter thresholds**: Your thresholds (p95 ≤ 400ms, error ≤ 2%) appear arbitrary. Either:
   - Cite industry standards (Google SRE Workbook recommends specific SLO targets)
   - Derive them from your own baseline measurements (e.g., "p95 at low load is 80ms, we define degradation as >5× baseline")

3. **Modify the research questions** to be more specific:
   - Current: *"Bagaimana pengaruh HPA terhadap latency dan throughput?"*
   - Better: *"Seberapa cepat HPA dapat memulihkan p95 latency ke level baseline setelah lonjakan beban, dan bagaimana variasi target CPU utilization (50%, 70%, 80%) memengaruhi waktu pemulihan tersebut?"*

---

## 7. "Make It Stand Out" Strategy

### Idea 1: HPA Scaling Behavior Policy Comparison (High Impact, Feasible)

Instead of only varying CPU thresholds, add **scaling behavior policies** as a second dimension:

| Config | Scale-up Policy | Scale-down Policy |
|--------|----------------|-------------------|
| Conservative | Default | `stabilizationWindowSeconds: 300` (default) |
| Balanced | `policies: [{type: Percent, value: 100, periodSeconds: 30}]` | `stabilizationWindowSeconds: 120` |
| Aggressive | `policies: [{type: Percent, value: 100, periodSeconds: 15}]` | `stabilizationWindowSeconds: 30` |

This creates a 3×3 matrix (3 thresholds × 3 behaviors = 9 configs). This is genuinely useful research because very few papers systematically test `behavior` policies, and it's the #1 thing DevOps engineers struggle to tune.

**Feasibility**: You just modify YAML files. No new infrastructure needed.

**Why it stands out**: Augustyn et al. (2024) in your bibliography focuses on tuning HPA, but their methodology is different. You would complement their work with a systematic comparison of `behavior` policies, which is an underexplored area.

---

### Idea 2: Multi-Service Differential Analysis (High Impact, Feasible)

Test HPA on **different services simultaneously** and analyze how they respond differently:

- **product-service**: Read-heavy, CPU-bound (GET requests, JSON serialization)
- **order-service**: Write-heavy, IO-bound (DB writes, inter-service calls to payment and product)
- **auth-service**: Lightweight, burst-sensitive (JWT generation/validation)

Show that the "optimal" HPA config differs per service type. This is a genuine finding that has practical value — it would recommend different `targetCPU` for read-heavy vs write-heavy services.

**Feasibility**: You already have all 5 services deployed. Just enable HPA on multiple services and observe differential behavior.

**Why it stands out**: Most HPA studies test a single synthetic service. Testing on a real multi-service architecture with differentiated workloads is significantly more valuable.

---

### Idea 3: Scaling Event Timeline Visualization (Medium Impact, Very Feasible)

Create detailed **timeline visualizations** that correlate:
- Request rate (k6 output) on one axis
- Pod count (HPA decisions) on a second axis
- p95 latency on a third axis
- CPU utilization on a fourth axis

All time-synchronized on the same X axis. You already have Prometheus + Grafana set up.

Create dashboards that tell a "story": *"At t=120s, load spiked to 200 RPS. HPA detected CPU >70% at t=135s (15s control loop). New pod was scheduled at t=138s but didn't pass readiness probe until t=148s. During this 28-second gap, p95 latency degraded from 120ms to 850ms. By t=155s, the new pod absorbed load and latency recovered to 150ms."*

This narrative approach demonstrates deep understanding of the system and makes your thesis extremely readable and memorable.

**Feasibility**: Grafana can do this with panel annotations. You just need to export and annotate the data.

---

## 8. Final Recommended Scope

> [!IMPORTANT]
> This refined scope is designed to be academically strong, realistic for an S1 timeline, and produce genuinely useful findings.

---

### Proposed Title (Refined)

**"Analisis Performa dan Perilaku Penskalaan Horizontal Pod Autoscaler (HPA) pada Aplikasi Microservices Berbasis Kubernetes: Studi Eksperimental terhadap Variasi Konfigurasi Threshold dan Scaling Policy"**

### Research Questions (Refined)

1. Bagaimana pengaruh variasi target CPU utilization (50%, 65%, 80%) pada HPA terhadap p95 latency, error rate, dan waktu pemulihan aplikasi microservices saat menghadapi beban dinamis?

2. Bagaimana perbedaan konfigurasi scaling behavior policy (conservative, balanced, aggressive) memengaruhi kecepatan penskalaan, stabilitas jumlah pod, dan efisiensi resource?

3. Apakah terdapat perbedaan respons HPA yang signifikan antara layanan dengan karakteristik beban berbeda (read-heavy vs write-heavy) pada arsitektur microservices?

4. Bagaimana trade-off antara responsivitas penskalaan dan efisiensi resource pada berbagai kombinasi konfigurasi HPA?

### Environment

- **Cluster**: KIND (1 control-plane + 3 worker nodes — *add 1 more worker than current*)
- **Application**: E-commerce microservices (5 services), focus HPA on 2-3 services with different profiles
- **Monitoring**: Prometheus + Grafana (already set up)
- **Load testing**: k6 with realistic multi-endpoint user journey scenarios
- **Cluster Autoscaler**: Excluded (controlled — pre-provision sufficient node capacity)
- **Cloud environment**: Excluded from main experiment; noted as future work

### Independent Variables

| Variable | Levels | Rationale |
|----------|--------|-----------|
| HPA State | Off (under-provisioned baseline, 1 replica), Off (over-provisioned baseline, max replicas), On | Three-way comparison |
| Target CPU Utilization | 50%, 65%, 80% | Covers low/mid/high sensitivity |
| Scaling Behavior Policy | Conservative (default), Balanced, Aggressive | Tests the underexplored `behavior` field |
| Load Pattern | Gradual ramp, Sudden spike, Oscillating | Three realistic patterns |

### Dependent Variables (KPIs)

**Stability**:
- p95 latency (ms)
- Error rate (%)
- Latency degradation ratio (peak p95 / baseline p95)

**Efficiency**:
- Average CPU utilization (%)
- Pod utilization ratio (actual CPU / requested CPU)
- Resource cost (total pod-seconds × CPU request)

**Scaling Behavior**:
- Time-to-scale (from threshold breach to new pod ready)
- Scaling event count
- Recovery time (time to return to baseline p95 after spike subsides)
- Pod stability (number of scale-up/down oscillations in 5-minute window)

### Experimental Protocol

1. Each configuration combination is run **5 times**
2. Each run has a 2-minute warm-up period (excluded from measurements)
3. Between runs: full cluster reset to baseline state (delete all HPA-created pods, wait for metrics stabilization)
4. Load test duration: 10 minutes per run (2 min ramp + 5 min sustain + 3 min cooldown/observation)
5. All metrics collected via Prometheus at 15-second scrape intervals

### Analysis Method

- Descriptive statistics (mean, SD, CI) for all KPIs
- Paired comparison tests (Wilcoxon signed-rank or paired t-test) for HPA-on vs baselines
- Two-way analysis (threshold × behavior policy) for interaction effects
- Timeline visualizations with correlated metrics for selected runs
- Trade-off analysis using scatter plots (latency vs resource cost)

### Deliverables

- Quantitative comparison tables with statistical significance indicators
- Scaling event timeline visualizations
- Recommended HPA configuration matrix (by service type and workload pattern)
- Trade-off analysis showing the Pareto-optimal configurations

---

> [!TIP]
> **Estimated total experiment runs**: 3 thresholds × 3 policies × 3 load patterns × 5 repetitions + 2 baselines × 3 patterns × 5 repetitions = 135 + 30 = **165 runs**. At ~15 minutes each (including setup/teardown), that's ~41 hours of testing. Spread over 2 weeks, this is very feasible.

---

## Summary

Your thesis outline is a solid starting point but currently reads as a **demonstration** rather than a **research contribution**. The three changes that would most dramatically improve it:

1. **Add scaling behavior policies as a variable** — this is your novelty
2. **Add statistical rigor** — 5 repetitions + significance tests transforms it from anecdotal to empirical
3. **Create realistic load scenarios** — test the actual e-commerce flow, not just GET /products

With these changes, you move from a 6.5 to a potential **8–8.5/10** — which is genuinely high quality for an S1 thesis.
