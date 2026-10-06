# Thesis Blueprint — Part 10: Thesis Chapter Outline (§12)

> Part of the thesis blueprint — index and executive summary: [thesis_blueprint.md](../thesis_blueprint.md).
> Sections moved verbatim from the single-file blueprint on 2026-10-06; original section numbers (§N) and finding numbers (#N) are kept so every cross-reference still resolves. Later additions are marked with their date.

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
- Platform: Azure Kubernetes Service (AKS), Free Tier, Indonesia Central region
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
- How it works: scenario-based testing with JavaScript; open-loop executors (ramping-arrival-rate, constant-arrival-rate) vs closed-loop executors (ramping-vus — used for both services in this thesis, because open-loop load drops iterations under saturation and delivers unequal load across configurations); the `noConnectionReuse` option and why it is enabled (finding #12)
  - ⚠️ **Rewrite this justification (2026-10-06, Part 08 §8.14):** "drops iterations" only applies to an undersized generator. A correctly sized open-loop generator dropped 0 iterations in 20 runs. Explain instead that closed loop measures scaling under self-throttled load, while open loop holds the offered load fixed, so slow scaling turns directly into failed requests. Describe whichever generator(s) the final dataset uses.
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
- Region: Indonesia Central (`indonesiacentral`)
- Cluster specification: 3× Standard_D4as_v5, Ephemeral OS disk, Azure CNI Overlay networking
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
- Baseline metrics: the fixed-replica calibration ladders (shipping VU ladder 70/80/100/120, April 2026; auth VU ladder in `calib-logs/`, 2026-08-15) and the measured B1/B2 p95 gates from the final dataset (shipping 3.51/3.62/3.57×, auth 2.98/3.14/2.72×)
- Load-generator observation: per-pod CPU showed that with k6 keep-alive, autoscaler-added pods received no traffic (finding #12) — the reason connection reuse is disabled
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

> **If the open-loop campaign is adopted (2026-10-06, Part 08):** also describe the arrival-rate stage shapes and rates (auth 2→30, shipping 10→105 req/s), the 5 s timeout, VU sizing ⌈1.5 × peak × timeout⌉, raw per-request capture, the auth token pre-authentication during the reset, and the per-pod admission control (cap 22 / 48, standard load shedding, outermost middleware, delivered via ConfigMap overlay on the unchanged images).
- k6 Job YAML manifest with resource requests
- k6 test script structure: `setup()` for token pooling (auth: log in first, register only if login fails — commit `a39b1f2`), weighted scenario distribution (auth 70% `/auth/me`, 30% `/auth/login`)
- 3 load pattern configurations, all `ramping-vus` stage shapes (gradual, spike, oscillating — see §6 Load Patterns), with `noConnectionReuse: true`

**G. Rancangan Threshold Calibration:**
- Calibration procedure: how H3 and K1 thresholds are set to the same value
- Why calibration is critical for the H3 vs K1 comparison fairness
- Final values: auth `5` req/s/pod, shipping `15` req/s/pod, shared 1 m rate window; report the measured B1/B2 gates (§1 PEAK_VUS deep-dive), not 5.56×

**Length:** 6-8 pages with all YAML manifests and explanations. All YAML is already in blueprint Section 6 — copy and add Indonesian explanations.

---

### BAB 4 HASIL DAN PEMBAHASAN

#### 4.1 Spesifikasi Devais yang Digunakan → **Spesifikasi Sistem**

**What to write:**

| Komponen | Spesifikasi |
|----------|------------|
| Cloud Platform | Azure Kubernetes Service (AKS), Free Tier |
| Region | Indonesia Central |
| Node VM | Standard_D4as_v5 (4 vCPU AMD EPYC, 16GB RAM, Ephemeral OS Disk) |
| Node Count | 3 |
| Kubernetes Version | 1.33.7 |
| Container Runtime | containerd |
| Network Plugin | Azure CNI Overlay |
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
- Execution log: summary of the final 180-run campaign — one continuous session, 2026-08-15 06:11 → 08-17 17:05 UTC (58 h 49 m runner time) — plus the superseded earlier campaign and why it was discarded (finding #12)
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

> **Open-loop material for BAB 4 (2026-10-06, Part 08):** at minimum, report the open-loop pilot as a robustness study. A correctly sized generator is stable (finding #17). The H2/H3/K1 spread grows by more than an order of magnitude (finding #18). Pod-exported request-rate metrics go blind under overload unless the service sheds load (findings #19, #22). Request rate reacts about twice as fast as CPU (finding #20). Disclose the closed-loop `setup()` warm-up burst (finding #21). If the 180-run open-loop campaign passes its gate, it becomes a second full results section with the same tables.

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

- Interpret using the final values in §9 Strategy 4: the decomposition is mostly null; metric and engine separate only on shipping spike
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
- Interpret the post-fix evidence: shipping gradual is one cluster on the B2 floor separated only by cost; shipping spike shows a genuine ranking (K1 < H3 < H2 < H1); shipping oscillating is a failure cluster; auth is a tight cluster per pattern (K1 oscillating the one outlier at +9.2% vs B2).

**B. Recommendation Matrix:**

| Workload Type | Recommended Autoscaling | Recommended Metric | Why |
|--------------|------------------------|--------------------|----|
| Downstream dependency-limited (DB or external dependency is the dominant bottleneck) | Scale the dependency first; app-tier HPA/KEDA choice becomes secondary | Dependency-specific metrics, queue depth, DB saturation | Scaling the wrong tier can worsen outcomes even if the autoscaler reacts correctly |
| Wait-dominant external dependency | Any autoscaler for gradual load; KEDA (or HPA + custom metric) for spiky load; under fast oscillation none of the tested configurations is adequate | Request rate | Post-fix shipping data: gradual ties on the B2 floor (916–920 ms); spike K1 941 ± 10 ms vs H1 1101 ± 177 ms; oscillating 2656–3096 ms against a 916 ms floor (≤26% of the gap closed) |
| CPU-bound (crypto, compression) | HPA (default) | CPU | CPU correlates with load, simpler setup; post-fix auth data shows every autoscaler within ~3% of B2 (K1 oscillating +9.2%) |
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
  1. "Pada auth-service yang CPU-bound, seluruh autoscaler menghasilkan p95 dalam kisaran ~3% dari baseline B2 pada ketiga pola beban (kecuali K1 pada pola oscillating, +9,2%), sehingga jenis metrik maupun engine tidak berpengaruh material. Pada shipping-rate-service yang wait-dominant, seluruh autoscaler setara di lantai B2 pada pola gradual (916–920 ms); keunggulan request rate hanya muncul pada pola spike (K1 941 ms vs H1 1101 ms); dan pada pola oscillating seluruh konfigurasi gagal (konfigurasi terbaik, H1, hanya menutup 26% gap B1→B2)."
  2. "Dekomposisi menunjukkan bahwa efek jenis metrik dan arsitektur engine sebagian besar mendekati nol; keduanya hanya terpisah pada shipping-rate-service pola spike (efek metrik −10,4%, efek engine −4,7%, gabungan −14,5%). Interaksi beban kerja × pola beban lebih dominan dibanding jenis metrik maupun engine."
  3. "Konfigurasi Pareto-optimal ditentukan setelah Resource Cost Index dihitung. Dari sisi latensi: pada pola gradual seluruh autoscaler setara sehingga biaya menjadi pembeda; pada pola spike K1 unggul untuk layanan wait-dominant; dan pada pola oscillating tidak ada konfigurasi yang memadai untuk layanan wait-dominant. Temuan product-service dilaporkan terpisah sebagai kasus dependency-limited."
- Confirm or refute each hypothesis from 1.3
- **Critical rule from template:** "Tidak boleh membuat kesimpulan hanya berisi sistem yang telah berjalan tanpa memberikan bukti data yang kuat." → Every conclusion must reference specific measured values and statistical test results.
- **Length:** 1-2 pages

#### 5.2 Saran

**What to write:**

**Saran untuk Praktisi:**
- Use request-rate-based scaling (KEDA or HPA + custom metric) for spiky load on wait-dominant services; for gradual load and for CPU-bound services, default CPU-based HPA was as good as any alternative tested
- CPU-based HPA is sufficient for CPU-bound services and may still be acceptable for some mixed workloads
- Treat wait-dominant services under fast oscillating load (≈90 s half-cycle) as a known limitation: none of the tested configurations handled it
- Consider operational complexity: KEDA requires less configuration for request-rate scaling than HPA + prometheus-adapter

**Saran untuk Penelitian Selanjutnya:**
1. Penambahan Vertical Pod Autoscaler (VPA) sebagai variabel perbandingan
2. Pengujian fitur scale-to-zero pada KEDA dan dampaknya terhadap cold-start latency
3. Perbandingan pada platform cloud lain (GKE, EKS) untuk validasi generalizability
4. Penggunaan predictive/ML-based autoscaling sebagai alternatif reactive scaling
5. Pengujian pada domain aplikasi lain (streaming, batch processing, ML inference)
6. Variasi periode osilasi, service time, dan baseline replica pada lebih dari satu workload wait-dominant untuk menguji mekanisme kegagalan pola oscillating (temuan #14)
7. *(added 2026-10-06)* Mengukur request rate di hulu (gateway/ingress, atau KEDA HTTP add-on) dibandingkan dengan metrik yang diekspor pod, serta pengaruh load shedding terhadap autoscaling di bawah beban open-loop (temuan #19, #22)

**Length:** 1 page
