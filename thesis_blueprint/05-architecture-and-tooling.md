# Thesis Blueprint — Part 05: AKS Architecture and Platform/Tooling Decisions (§4–§5)

> Part of the thesis blueprint — index and executive summary: [thesis_blueprint.md](../thesis_blueprint.md).
> Sections moved verbatim from the single-file blueprint on 2026-10-06; original section numbers (§N) and finding numbers (#N) are kept so every cross-reference still resolves. Later additions are marked with their date.

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

*Identifiers match the cluster used for the experiments (resource group `ecommerce`, cluster `ecommerce-aks`, region Indonesia Central, Azure CNI Overlay — see BAB 3.2.1, ACR `ecommerce`). The original plan used `thesis-rg` / `thesis-aks` in Southeast Asia.*

```bash
az aks create \
  --resource-group ecommerce \
  --name ecommerce-aks \
  --node-count 3 \
  --node-vm-size Standard_D4as_v5 \
  --node-osdisk-type Ephemeral \
  --tier free \
  --location indonesiacentral \
  --network-plugin azure \
  --network-plugin-mode overlay \
  --generate-ssh-keys \
  --no-wait
```

After creation, install KEDA and prometheus-adapter:
```bash
# Step 1: Install KEDA via AKS add-on (simplest, Microsoft-managed)
az aks update --resource-group ecommerce --name ecommerce-aks --enable-keda

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
az acr create --resource-group ecommerce --name ecommerce --sku Basic

# Attach ACR to AKS (allows AKS to pull images without secrets)
az aks update --resource-group ecommerce --name ecommerce-aks --attach-acr ecommerce

# Build and push images (repeat for every service image used in the experiment)
az acr login --name ecommerce
docker tag shipping-rate-service ecommerce.azurecr.io/shipping-rate-service:latest
docker push ecommerce.azurecr.io/shipping-rate-service:latest
```

> ⚠️ **Note (2026-10-06):** ACR Tasks (`az acr build`) are **not available in Indonesia Central**. Azure rejects the context upload with "No registered resource provider found for location 'indonesiacentral' … registries/listBuildSourceUploadUrl". Images must be built elsewhere: local Docker (not installed on the laptop), Docker on a VM, or a temporary ACR in a supported region followed by `az acr import`. For the open-loop v2 work the code change was instead mounted from a ConfigMap over the unchanged `:latest` images (Part 08 §8.10).

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

**Also required:** every k6 scenario sets `noConnectionReuse: true` (finding #12). With keep-alive, kube-proxy pins each VU to the pods that existed when it connected, so autoscaler-added pods receive no traffic.

> **Open-loop k6 jobs (added 2026-10-06, Part 08):** `k6-openloop-pilot.yaml` pins `grafana/k6:0.46.0` for both services; the closed-loop auth jobs use unpinned `:latest`, shipping 0.46.0. Pod resources are request 1000m CPU / 1Gi, limit 2000m / 4Gi, sized from measured use: ≈0.4 MiB per preallocated VU (204 MiB for 525 VUs, 1752 MiB for 3000) and ≤ 0.57 cores in every ladder and pilot run. A wrapper keeps the container alive after k6 exits until the runner has copied the gzipped per-request JSON and verified its md5. The closed-loop runner's `kubectl cp` ran after the pod had terminated, so it never captured `results.json`.

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
