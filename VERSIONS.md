# Observability Lab — Verified Version Reference

**Project:** Surit Maharana Observability Lab  
**Last verified:** June 22, 2026  
**Sources:** PyPI, npmjs.com, github.com releases, python.org, nodejs.org, endoflife.date, AWS docs, Helm GitHub

---

## Runtime environments

| Component | Pinned version | Source | Notes |
|---|---|---|---|
| Python | **3.13.14** | python.org (Jun 10 2026) | Active LTS; 3.14.x is newer but OTel SDK targets 3.13 |
| Node.js | **24.16.0 LTS** | nodejs.org | Active LTS "Krypton"; Node 26 is Current (not yet LTS) |

> **Why 3.13 not 3.14?** The OTel Python SDK (1.42.1) marks support for 3.13 stable. 3.14.x dropped in Oct 2025 and the instrumentation contrib packages lag by one cycle. Use 3.13.14 for production stability.

> **Why Node 24 not 26?** Node 26 entered Current on May 5 2026 and becomes LTS in October 2026. `@opentelemetry/sdk-node` 0.218.0 is tested against Node 20 and 22 LTS. Node 24 is the safe LTS choice now.

---

## App instrumentation — Python

| Package | Pinned version | Source |
|---|---|---|
| `opentelemetry-api` | **1.42.1** | PyPI (May 21 2026) |
| `opentelemetry-sdk` | **1.42.1** | PyPI (May 21 2026) |
| `opentelemetry-instrumentation-fastapi` | **0.63b1** | PyPI (Apr 24 2026) |
| `opentelemetry-instrumentation-psycopg2` | **0.63b1** | PyPI (May 21 2026) |
| `opentelemetry-exporter-otlp-proto-grpc` | **1.42.1** | PyPI (May 21 2026) |
| `opentelemetry-semantic-conventions` | **0.63b1** | PyPI (May 21 2026) |

> **Version alignment rule:** Python OTel SDK (1.x) and contrib instrumentation (0.xb1) must always be installed together from the same release cycle. The `0.63b1` contrib packages align exactly with `1.42.1` SDK. Never mix cycles.

---

## App instrumentation — Node.js

| Package | Pinned version | Source |
|---|---|---|
| `@opentelemetry/sdk-node` | **0.218.0** | npm (May 2026) |
| `@opentelemetry/api` | **1.9.x** | npm |
| `@opentelemetry/auto-instrumentations-node` | latest stable matching 0.218.0 | npm |
| `@opentelemetry/exporter-trace-otlp-grpc` | **0.218.0** | npm |
| `@opentelemetry/sdk-metrics` | **2.8.0** | npm (Apr 2026) |

> **Note:** `@opentelemetry/sdk-node` uses 0.x versioning for the experimental SDK wrapper; stable trace/metrics packages use 1.x/2.x. Both are production-ready.

---

## LLM observability — OpenLLMetry

| Package | Pinned version | Source |
|---|---|---|
| `traceloop-sdk` (Python) | **0.61.0** | PyPI (May 31 2026) |
| `@traceloop/node-server-sdk` (Node) | **0.60.0** | GitHub (Apr 19 2026) |
| **AWS Bedrock model (AIOps RCA)** | **Amazon Nova Micro** `us.amazon.nova-micro-v1:0` | AWS Bedrock, us-east-2 |

> **Compatibility joint:** OpenLLMetry wraps the OTel `TracerProvider` you configure — it does not create a second pipeline. LLM spans carry the same `trace_id` as the HTTP span that triggered them. Requires `opentelemetry-sdk >= 1.40.0`.

---

## eBPF / Network observability

| Component | Pinned version | Source | Notes |
|---|---|---|---|
| **Cilium CNI** | **1.19.4** | github.com/cilium/cilium (May 13 2026) | Active stable; 1.18.10 and 1.17.16 also maintained |
| **Hubble** | bundled with Cilium 1.19.4 | — | OTLP export native since Cilium 1.15 |
| **Grafana Beyla** | **3.20.0** | github.com/grafana/beyla (Jun 8 2026) | Helm chart 1.16.8; stable release |
| **OTel eBPF Instrumentation (OBI)** | **0.9.2** | open-telemetry/opentelemetry-ebpf-instrumentation | NetO11y + StatsO11y; installed separately from Beyla |

> **Cilium kernel requirement:** Linux kernel 5.10+ required; 5.15+ recommended for full eBPF feature set. EKS AL2023 AMIs ship kernel 6.12.90 (AL2023.12.20260608) — TCX mode fully supported. No bpf-filter-priority workaround needed.

> **Beyla note:** Grafana donated Beyla to OpenTelemetry under the name "OpenTelemetry eBPF Instrumentation (OBI)." The current stable Beyla release is 3.20.0 (Helm chart 1.16.8, Jun 8 2026). Emit is OTLP-native. Requires privileged: true + SYS_ADMIN capability on EKS.

> **OBI note:** OBI is deployed as a separate DaemonSet (Helm chart version 0.9.2) with `meter_provider.features: [network, stats, application]` and `OTEL_EBPF_NETWORK_SOURCE: socket_filter` (required — Cilium uses TC direct action). It surfaces `obi.network.flow.bytes`, `obi.stat.tcp.failed.connections`, and `obi.stat.tcp.rtt`. The RTT metric exports but renders as a sawtooth artifact in Dash0 (rate()+reset); rendering fix is backlogged.

> **TCP retransmit — verified finding:** A claim that Beyla 3.20.0 exposes TCP retransmit counts as a queryable metric did not hold up against the live endpoint. Beyla exposes only `beyla_network_flow_bytes`; the `tcp_retransmit_skb` tracepoint is internal to L7 span correlation and is not user-facing. TCP retransmit visibility requires a custom eBPF program. The proven fault demo uses POLICY_DENY drops, OBI flow bytes, and OBI TCP failed connections instead.

> **Cloud-specific eBPF:**
> - **EKS:** Replace AWS VPC CNI with Cilium (Terraform `cilium_replace_cni = true`)
> - **GKE:** Disable default dataplane V2, install Cilium as CNI
> - **AKS:** Use native Cilium network policy (`--network-plugin azure --network-plugin-mode overlay --network-policy cilium`) — no CNI replacement needed from AKS 1.28+
> - **k3s on-prem:** Install with `--flannel-backend=none --disable-network-policy`, then install Cilium

---

## OTel Collector

| Component | Pinned version | Source |
|---|---|---|
| **OTel Collector Contrib** | **v0.154.0** | github.com/open-telemetry/opentelemetry-collector-releases (Jun 9 2026) |
| **OTel Operator (K8s)** | latest matching v0.154.0 | open-telemetry/opentelemetry-helm-charts |

> **Collector Helm chart:** `open-telemetry/opentelemetry-collector` — install via `helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts`

**Receivers to enable:**
- `otlp` (gRPC 4317, HTTP 4318) — app signals
- `hubble` — Cilium/Hubble network flows
- `prometheus` — scrape existing Prometheus endpoints
- `filelog` — container logs
- `hostmetrics` — node-level CPU/mem/disk/net

**Processors (in order):**
- `memory_limiter` — first, always
- `k8sattributes` — enriches every span/metric/log with K8s metadata (requires ClusterRole)
- `resource` — add environment/cloud labels
- `batch` — last before export

**Exporters (fanout):**
- `otlp/dash0` — Dash0 OTLP/gRPC endpoint (phases 1–8)
- `otlp/dynatrace` — Dynatrace OTLP ingest endpoint (phase 7+)
- `datadog` — Datadog exporter (phase 7+, preferred over OTLP ingest for APM correlation)

---

## Infrastructure

| Component | Pinned version | Source |
|---|---|---|
| **AWS EKS** | **Kubernetes 1.35** | AWS (Jan 28 2026) |
| **k3s (on-prem)** | **v1.36.1+k3s1** | github.com/k3s-io/k3s (May 2026) |
| **GKE** | **1.35.x** (Standard mode) | GCP |
| **AKS** | **1.35.x** | Azure |

> **Why EKS 1.35 vs k3s 1.36?** EKS announced 1.35 support Jan 28 2026. k3s tracks upstream faster — 1.36.1 is current. Both are fine; the Collector and Cilium are version-agnostic above K8s 1.24.

---

## IaC and CI/CD

| Component | Pinned version | Source |
|---|---|---|
| **Terraform** | **1.15.6** | hashicorp/terraform (May 6 2026) |
| **Terraform AWS provider** | **6.50.0** | registry.terraform.io (Jun 10 2026) |
| **Helm** | **4.2.1** | github.com/helm/helm (May 2026) |
| **GitHub Actions** | ubuntu-24.04 runners | GitHub |

> **Helm 4 note:** Helm 4.x is now stable (released early 2026). It is backward compatible with Helm 3 charts. Use 4.2.1. Helm 3.21.x is still maintained for those who prefer it.

---

## Compatibility chain verification

```
Python 3.13.14
  └─ opentelemetry-sdk 1.42.1
       └─ opentelemetry-instrumentation-fastapi 0.63b1     ✓ same release cycle
       └─ traceloop-sdk 0.61.0                              ✓ requires OTel SDK ≥ 1.40
       └─ opentelemetry-exporter-otlp-proto-grpc 1.42.1    ✓ same release cycle

Node.js 24.16.0 (LTS)
  └─ @opentelemetry/sdk-node 0.218.0
       └─ @opentelemetry/sdk-metrics 2.8.0                 ✓ compatible
       └─ @traceloop/node-server-sdk 0.60.0                ✓ wraps OTel SDK

Cilium 1.19.4 + Hubble
  └─ emits OTLP natively → Collector 0.154.0              ✓ hubblereceiver in contrib
Grafana Beyla 3.20.0 (Helm chart 1.16.8)
  └─ emits OTLP natively → Collector 0.154.0              ✓ no bridge needed

OTel Collector Contrib v0.154.0
  └─ otlp exporter → Dash0 (OTLP/gRPC)                   ✓ OTel-native backend
  └─ otlp exporter → Dynatrace (OTLP ingest)              ✓ no OneAgent needed
  └─ datadog exporter → Datadog APM                       ✓ preserves trace/span IDs

K8s 1.35 (EKS) / 1.36 (k3s/GKE/AKS)
  └─ Cilium 1.19.4 supports K8s 1.25–1.36                ✓ full range covered
  └─ OTel Operator supports K8s 1.24+                     ✓ covered

Helm 4.2.1
  └─ open-telemetry/opentelemetry-collector Helm chart    ✓
  └─ cilium/cilium Helm chart                             ✓
  └─ grafana/beyla Helm chart                             ✓

Terraform 1.15.6 + AWS provider 6.50.0
  └─ EKS 1.35 cluster provisioning                       ✓
```

---

## What was deliberately excluded

| Tool | Reason |
|---|---|
| **Pixie** | Own protocol, not OTLP — breaks the chain at the eBPF layer |
| **Jaeger / Zipkin** | Format bridge adds noise; Collector → backend directly is cleaner |
| **Prometheus as backbone** | Scrape model conflicts with OTel push model; use only as supplementary receiver |
| **Dynatrace OneAgent** | Conflicts with Cilium CNI at kernel level; OTLP ingest endpoint only |
| **Datadog Agent** | Use Collector `datadog` exporter instead; avoids dual-agent complexity |
| **Node.js 26** | Current (not LTS) until October 2026; OTel SDK not yet validated |
| **Python 3.14** | OTel instrumentation contrib packages lag one cycle; use 3.13.14 |
| **Helm 3.x** | Helm 4.2.1 is stable and backward compatible; no reason to stay on 3 |

---

## Renovate bot config (recommended)

Add `renovate.json` to the repo root to auto-track version bumps:

```json
{
  "extends": ["config:base"],
  "packageRules": [
    {
      "matchPackagePatterns": ["opentelemetry"],
      "groupName": "opentelemetry",
      "automerge": false
    },
    {
      "matchPackagePatterns": ["traceloop"],
      "groupName": "openllmetry",
      "automerge": false
    }
  ],
  "terraform": { "enabled": true },
  "helm-values": { "enabled": true }
}
```

---

*This document is the single source of truth for versions across the project. Update after each phase.*

---

## Version corrections log

| Date | Component | Was | Corrected to | Reason |
|---|---|---|---|---|
| Jun 13, 2026 | Node.js | 24.15.0 | 24.16.0 | One patch behind — verified nodejs.org |
| Jun 13, 2026 | Terraform | 1.15.2 | 1.15.6 | Four patches behind — verified github.com/hashicorp/terraform |
| Jun 13, 2026 | opentelemetry-instrumentation-fastapi | 0.55b1 | 0.63b1 | Wrong release cycle — must align with SDK 1.42.1 |
| Jun 13, 2026 | opentelemetry-instrumentation-psycopg2 | 0.55b1 | 0.63b0 | Wrong release cycle — must align with SDK 1.42.1 |
| Jun 13, 2026 | EKS module argument | cluster_addons | addons | Renamed in v21 — verified UPGRADE-21.0.md |
| Jun 13, 2026 | EKS module argument | cluster_name | name | Renamed in v21 — verified UPGRADE-21.0.md |
| Jun 13, 2026 | EKS module argument | cluster_version | kubernetes_version | Renamed in v21 — verified UPGRADE-21.0.md |
| Jun 13, 2026 | EKS module argument | cluster_endpoint_public_access | endpoint_public_access | Renamed in v21 — verified UPGRADE-21.0.md |
| Jun 14, 2026 | Grafana Beyla | 3.12.x | 3.20.0 (chart 1.16.8) | Live cluster confirmed via helm list -A |
| Jun 14, 2026 | EKS AL2023 kernel | 6.1 | 6.12.90-120.164.amzn2023.x86_64 | Live cluster confirmed via kubectl get nodes |
| Jun 14, 2026 | opentelemetry-instrumentation-psycopg2 | 0.63b0 | 0.63b1 | Must match fastapi==0.63b1 — confirmed in cluster |
| Jun 22, 2026 | OBI | (not listed) | 0.9.2 | Added as distinct component — NetO11y + StatsO11y, separate from Beyla |
| Jun 22, 2026 | Beyla TCP retransmit metric | assumed exposed | not user-facing | Verified against live endpoint; `tcp_retransmit_skb` is internal only |
| Jun 22, 2026 | llm-svc | 0.6.0 | 0.7.0 | Absolute time window + 3 new signals + deterministic healthy-path gate |
| Jun 22, 2026 | AIOps model | (not recorded) | Amazon Nova Micro | Confirmed via /diagnose response model field |
