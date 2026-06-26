# OTel Observability Lab

> **App observability tells you something is broken. Network observability tells you why. The OTel pipeline is the missing bridge — no vendor lock-in required.**

A public, production-grade reference lab that unifies **network (eBPF), application (OpenTelemetry SDK), and LLM observability** into one vendor-agnostic OpenTelemetry pipeline — and then puts an LLM on top of it to do automated root-cause analysis from real, correlated signals.

The larger goal this lab is building toward: make *every* signal class — application traces, network flows, policy enforcement, audit logs, configuration changes, SNMP, and beyond — flow through one open pipeline, across every environment (AWS, GCP, Azure, on-prem) and into whichever backend an organization already owns (Dash0, Dynatrace, Datadog). Once observability can be reasoned about as a whole, infrastructure can be tied to business requirement — and environments stood up and torn down in hours, not months.

Built by [Surit Maharana](https://linkedin.com/in/surit-maharana) — 20+ years at JPMorgan Chase across network observability (Riverbed AppResponse, Arista DMF, NetFlow at 120M flows/min) and application performance monitoring (CA APM Wily Introscope), now applying enterprise telemetry patterns to cloud-native infrastructure.

---

## Proven, today

This is not a roadmap of intentions. The following is implemented, deployed, and demonstrated on a live AWS EKS cluster:

- **Unified pipeline** — application traces, L7 HTTP spans (Beyla eBPF), L3/L4 network flows + policy drops (Cilium/Hubble), and TCP connection stats (OBI) all flow through one OTel Collector to one backend.
- **The network blindspot, proven** — a CiliumNetworkPolicy fault is injected; the app layer sees only silence (a timeout, spans falling to zero), while the network layer shows exactly why (policy-deny drops spike, TCP failures spike, flow bytes collapse).
- **AIOps root-cause analysis** — a `/diagnose` endpoint queries the backend for the correlated signals, hands them to an LLM (AWS Bedrock, Amazon Nova Micro), and returns a structured root cause in ~3 seconds for ~$0.00005 per call.
- **Absolute-window querying** — `/diagnose` accepts an exact incident window (`start`/`end`), so the analysis targets the precise span of a fault rather than a relative "last N minutes."
- **A deterministic healthy-path gate** — if the two fault fingerprints (policy-deny drops and TCP failures) are both zero, the system returns "no anomaly" deterministically and never calls the LLM. The model explains problems; it does not decide whether one exists.
- **LLM observability** — every Bedrock call emits a span with `gen_ai.*` attributes (model, token counts, cost, latency) in the same trace as the HTTP request.

---

## The money shot

The gateway runs on one Kubernetes node; the product service runs on another. Cross-node traffic is where network faults live and where APM goes blind.

A `CiliumNetworkPolicy` blocks all TCP traffic from gateway → product-svc. Then each layer is observed in the same backend, in the same time window:

| Layer | Signal | During the fault |
|---|---|---|
| App spans (OTel SDK) | `dash0.spans` (product-svc) | **drop to zero** — no request arrives |
| Network policy (Hubble) | `hubble_drop_total{POLICY_DENY}` | **spike** — packets being denied |
| Network flow (OBI/Beyla) | `obi.network.flow.bytes` | **drop** — traffic stops on the wire |
| TCP stats (OBI) | `obi.stat.tcp.failed.connections` | **spike** — handshakes failing |

The application trace alone says *something is slow.* The network signals say *connections are being blocked by a policy.* Same incident, two truths, one pipeline — no bridge call required.

> Note on TCP retransmits: an earlier plan leaned on a Beyla retransmit metric. Verifying against the live Beyla endpoint showed it does **not** expose a user-queryable retransmit counter (the tracepoint is used internally for span correlation only). The proven demo uses policy-deny drops, flow bytes, and TCP failed connections instead. See VERSIONS.md for the correction.

---

## Build series status

| Phase | Title | Status |
|---|---|---|
| 1 | Foundation — EKS, Cilium, Terraform, CI | ✅ Complete |
| 2 | Full MELT — OTel SDK, Beyla, Hubble | ✅ Complete |
| 3 | Network blindspot — CiliumNetworkPolicy fault | ✅ Complete |
| 4 | GenAI observability — Bedrock, `gen_ai.*` spans | ✅ Complete |
| 5 | AIOps RCA — LLM + Dash0 Prometheus API | ✅ Complete |
| 6 | Multi-backend — Dynatrace (OTLP) alongside Dash0 | ✅ Complete |
| 7 | OBI — NetO11y + StatsO11y + AppO11y | ✅ Complete |
| 7.5 | AIOps upgrades — absolute window, richer signals, healthy-path gate | ✅ Complete |
| 8 | On-prem bridge — k3s + NetFlow/sFlow via OTel | ⬜ Planned |

Beyond Phase 8, the lab extends toward multi-cloud (GCP GKE, Azure AKS), additional signal classes (audit logs, config/change events, SNMP), and the cost-to-business-requirement layer described above.

Follow the build on [LinkedIn](https://linkedin.com/in/surit-maharana) and Substack.

---

## Architecture at a glance

```
            Node A                          Node B
        ┌───────────┐               ┌──────────────────────┐
        │  gateway  │               │ product-svc  postgres│
        └─────┬─────┘               └──────────┬───────────┘
              │   cross-node link (faults live here)
              ▼                                ▼
     OTel SDK · Beyla · Hubble        OTel SDK · Beyla · OBI
              └───────────────┬────────────────┘
                              ▼
                       OTel Collector  (one pipeline)
                              ▼
                            Dash0       (Prometheus API)
                              ▼
                          /diagnose     (LLM root cause)
```

Full interactive architecture, data-flow, and executive diagrams: [`docs/otel-lab-diagrams.html`](docs/otel-lab-diagrams.html).

---

## How the AIOps RCA works

`/diagnose` is an OTel + LLM pattern, not a backend feature. It queries any Prometheus-compatible backend (Dash0 today; the same engine works against Dynatrace, Datadog, Grafana Cloud with a one-line endpoint change), assembles the correlated signals into a prompt with SRE context and the known fault signature, and asks Bedrock for a structured root cause.

```
GET /diagnose?backend=dash0&start=2026-06-22T21:56:52Z&end=2026-06-22T22:02:57Z
```

Returns root cause, confidence, evidence (the causal chain), a remediation command, severity, model, latency, and cost. On a healthy window, the deterministic gate short-circuits to a "no anomaly" result with no LLM call.

---

## Stack

| Component | Version |
|---|---|
| Python | 3.13.14 |
| OpenTelemetry SDK | 1.42.1 |
| Cilium CNI + Hubble | 1.19.4 |
| Grafana Beyla | 3.20.0 |
| OpenTelemetry eBPF Instrumentation (OBI) | 0.9.2 |
| OTel Collector Contrib | v0.154.0 |
| AWS Bedrock model | Amazon Nova Micro (`us.amazon.nova-micro-v1:0`) |
| Terraform | 1.15.6 |
| Helm | 4.2.1 |
| EKS | Kubernetes 1.35 |

See [VERSIONS.md](VERSIONS.md) for the full pinned reference and compatibility chain.

---

## Prerequisites

- AWS CLI configured (`aws configure`)
- Terraform 1.15.6
- Helm 4.2.1
- kubectl
- Docker

---

## Quick start

```bash
git clone https://github.com/suritmaharana-maker/otel-observability-lab
cd otel-observability-lab

# Provision the EKS cluster (~15 minutes)
terraform -chdir=terraform/eks init
terraform -chdir=terraform/eks apply

# Configure kubectl
aws eks update-kubeconfig --region us-east-2 --name otel-lab

# Verify nodes
kubectl get nodes
```

A complete operational runbook — bring-up, the LLM and network observability demos, the 20-minute chaos test, the AIOps RCA, and teardown — with validation gates after every step is in [`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md).

> **Cost note:** this lab runs on EKS, which is not free-tier eligible (the control plane, NAT gateway, and load balancer bill independently of worker nodes). The runbook documents both scale-to-zero (stop worker-node cost, keep the cluster) and full `terraform destroy` (near-zero cost, ~15-minute rebuild) so environments can be stood up and torn down on demand.

---

## Repository layout

```
apps/
  gateway/        FastAPI gateway — routes /products, /recommendations, /diagnose
  llm-svc/        Bedrock-backed LLM service — recommendations + AIOps /diagnose
  product-svc/    FastAPI product service + PostgreSQL
k8s/              OBI values, OTel Collector config, DynaKube, fault injection
terraform/        eks/ (cluster + VPC + node group) · observability/ (module)
docs/             interactive architecture diagrams
DEMO_RUNBOOK.md   end-to-end demo + teardown with validation gates
VERSIONS.md       pinned version reference and compatibility chain
```

> Implementation note: the gateway runs from a Kubernetes ConfigMap (`gateway-code`), and `llm-svc` deploys by image digest to force a clean pull on `:latest`. Both are documented in the runbook.

---

## Licence

Released under the MIT Licence — see the `LICENSE` file. (If you are reusing substantial portions, attribution is appreciated.)
