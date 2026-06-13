# OTel Observability Lab

> **App observability tells you something is broken. Network observability tells you why.**

A fully public, production-grade lab demonstrating **Network (eBPF) + APM (OpenTelemetry SDK) + LLM (OpenLLMetry)** observability married into one vendor-agnostic OTel pipeline — across AWS EKS, on-prem k3s, GCP GKE, and Azure AKS.

Built by [Surit Maharana](https://linkedin.com/in/surit-maharana) — Principal Network Observability Engineer with 20+ years at JPMorgan Chase, applying enterprise-grade telemetry patterns to cloud-native infrastructure.

---

## What this demonstrates

| Layer | Tool | Signal |
|---|---|---|
| Network (L3/L4) | Cilium + Hubble | Flow metrics, drops, DNS failures, TCP retransmits |
| Network (L7) | Grafana Beyla (eBPF) | HTTP spans with W3C traceparent — zero code changes |
| APM | OpenTelemetry SDK | Distributed traces, metrics, logs |
| LLM | OpenLLMetry (traceloop-sdk) | Token count, cost, latency — in the same trace as HTTP |
| Backends | Dash0 → Dynatrace → Datadog | Same OTel signal, three lenses |

---

## The money shot (Phase 3)

TCP retransmits are injected between services. The app SDK shows elevated latency but **no error**. Hubble shows packet drops. Beyla shows span duration increase. **Root cause visible only at the network layer** — not in app traces alone.

This is the failure mode your APM will never catch.

---

## 8-Phase Build Series

| Phase | Title | Status |
|---|---|---|
| 1 | Foundation — vanilla app on AWS EKS | 🔄 In progress |
| 2 | Full MELT + Network observability | ⬜ Planned |
| 3 | The Network Blindspot Demo | ⬜ Planned |
| 4 | GenAI Observability (OpenLLMetry) | ⬜ Planned |
| 5 | AIOps Layer | ⬜ Planned |
| 6 | Multi-Cloud (on-prem + GCP + Azure) | ⬜ Planned |
| 7 | Multi-Backend (Dash0 + Dynatrace + Datadog) | ⬜ Planned |
| 8 | Public Packaging | ⬜ Planned |

Follow along on [LinkedIn](https://linkedin.com/in/surit-maharana) and [Substack](#).

---

## Stack

| Component | Version |
|---|---|
| Python | 3.13.14 |
| OpenTelemetry SDK | 1.42.1 |
| OpenLLMetry (traceloop-sdk) | 0.61.0 |
| Cilium CNI | 1.19.4 |
| Grafana Beyla | 3.12.x |
| OTel Collector Contrib | v0.154.0 |
| Terraform | 1.15.2 |
| Helm | 4.2.1 |
| EKS | Kubernetes 1.35 |

See [VERSIONS.md](VERSIONS.md) for the full pinned version reference and compatibility chain.

---

## Prerequisites

- AWS CLI configured (`aws configure`)
- Terraform 1.15.2
- Helm 4.2.1
- kubectl
- Docker

---

## Quick start (Phase 1)

```bash
git clone https://github.com/suritm7543/otel-observability-lab
cd otel-observability-lab

# Deploy EKS cluster (takes ~15 minutes)
terraform -chdir=terraform/eks init
terraform -chdir=terraform/eks apply

# Configure kubectl
aws eks update-kubeconfig --region us-east-2 --name otel-lab

# Verify nodes are ready
kubectl get nodes
```

---

## Licence

MIT
