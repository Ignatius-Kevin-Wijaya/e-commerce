# Thesis Blueprint — Part 04: Title and Scope (§2–§3)

> Part of the thesis blueprint — index and executive summary: [thesis_blueprint.md](../thesis_blueprint.md).
> Sections moved verbatim from the single-file blueprint on 2026-10-06; original section numbers (§N) and finding numbers (#N) are kept so every cross-reference still resolves. Later additions are marked with their date.

---

## 2. Final Thesis Theme and Title Recommendation

### Final Title (approved by Pak Cahya)

> **"Analisis Pengaruh Jenis Metrik Penskalaan dan Mekanisme Autoscaler (HPA vs KEDA) terhadap Responsivitas dan Efisiensi Resource Aplikasi Microservices pada Kubernetes"**

### Title Evolution

This title has been refined through 5 iterations:

| Iteration | Title Approach | Issue |
|-----------|---------------|-------|
| v1 | "...HPA-on vs HPA-off..." | Binary, no novelty |
| v2 | "...Konfigurasi Threshold dan Scaling Policy pada HPA..." | HPA-only, narrow scope |
| v3 | "...Penskalaan Reaktif Berbasis CPU (HPA) dan Event-Driven Berbasis Request Rate (KEDA)...pada Azure Kubernetes Service" | Framed as 2-way HPA vs KEDA comparison — doesn't reflect H3 (HPA + request-rate), 27 words, double parenthetical, over-specifies platform |
| v4 | "...Jenis Metrik Penskalaan dan Mekanisme Autoscaler (HPA vs KEDA)...Efisiensi Biaya...pada Kubernetes" | ✅ Reflects factorial design (two independent variables), 18 words, clean, generalizable |
| **v5 (approved)** | v4 with "Efisiensi Resource" in place of "Efisiensi Biaya" | ✅ Approved by Pak Cahya |

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

The previous title had "Responsivitas, Efisiensi Resource, dan Biaya Operasional" — three outputs. But "Efisiensi Resource" (are pods wasting CPU?) and "Biaya Operasional" (how much does it cost in dollars?) are closely related: wasting resources IS the cause of high cost. They are merged into one output dimension. The approved wording is **"Efisiensi Resource"** (Pak Cahya's choice over "Efisiensi Biaya" and "Sumber Daya"). The thesis still MEASURES all three things (latency, utilization, dollar cost) — the title just groups them into two clean categories:
- **Responsivitas** = p95 latency, error rate, time-to-scale (performance)
- **Efisiensi Resource** = Resource Cost Index, pod utilization ratio (resource/cost efficiency)

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
| Mentions what's measured? | ✅ "Responsivitas dan Efisiensi Resource" |
| Mentions the domain? | ✅ "Aplikasi Microservices" |
| Mentions the platform? | ✅ "Kubernetes" |
| Not too long? | ✅ 18 words (ideal: 15-22) |
| Not too vague? | ✅ HPA/KEDA named, scaling metrics referenced |
| Generalizable? | ✅ All Kubernetes, not vendor-locked |
| Searchable keywords? | ✅ HPA, KEDA, Microservices, Kubernetes, Autoscaler |

**Overall: 9.5/10.** The 0.5 it loses: doesn't explicitly mention workload-type contrast (I/O-bound vs CPU-bound). Adding "dengan Karakteristik Beban Berbeda" would push to 22 words — acceptable but less punchy. This contrast is better introduced in BAB 1.

### Alternative Titles

*Historical — the title above is approved; these are kept for reference only.*

**Alt 1 (Adding workload-type contrast — 22 words):**
> "Analisis Pengaruh Jenis Metrik Penskalaan dan Mekanisme Autoscaler (HPA vs KEDA) terhadap Responsivitas dan Efisiensi Resource Aplikasi Microservices dengan Karakteristik Beban Berbeda pada Kubernetes"

*Adds "dengan Karakteristik Beban Berbeda" to signal the I/O-bound vs CPU-bound contrast. Longer but more complete. Use this if your advisor values completeness over conciseness.*

**Alt 2 (Emphasizing the experimental methodology — 20 words):**
> "Studi Eksperimental Pengaruh Jenis Metrik dan Mekanisme Autoscaling terhadap Performa Penskalaan Horizontal Aplikasi Microservices CPU-Bound dan I/O-Bound pada Kubernetes"

*Starts with "Studi Eksperimental" to immediately signal quantitative research. Mentions both workload types. Doesn't name HPA/KEDA in the title (they'd be in BAB 1). Use this if your department values methodology framing over tool specificity.*

**Alt 3 (Shorter, punchier — 16 words):**
> "Analisis Pengaruh Jenis Metrik Autoscaling pada HPA dan KEDA terhadap Performa Penskalaan Microservices pada Kubernetes"

*Shortest option at 16 words. Sacrifices the efficiency dimension ("Efisiensi Resource") and focuses solely on performance. Use this if your advisor prefers concise titles, with the cost analysis positioned as a secondary contribution in BAB 1.*

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
- **Each experiment run: 12 minutes of k6 load** (2 min warm-up, 7 min test, 3 min ramp-down), plus ~8 min of reset, stabilization and export (≈20 min wall-clock per run). Consistent across all configurations.
- **Core statistical analysis covers auth-service and shipping-rate-service only.** Product-service results are retained separately as an exploratory dependency-limited case-study and should not be pooled into the main 180-run matrix.

---
