# Observability Lab — Master Project Context

> **Purpose:** This is the single document to paste at the start of any new Claude conversation
> to restore full project context without repeating any instructions.
> **Last updated:** June 13, 2026

---

## Who I Am

**Name:** Surit Maharana  
**Location:** Columbus, OH  
**Contact:** suritmaharana@gmail.com | 614.638.9751 | linkedin.com/in/surit-maharana  
**Current role:** Lead Infrastructure Engineer, Network Services — JPMorgan Chase (8/2010–5/2026, ending)  
**Education:** B.E. Computer Science, Bangalore University  
**In progress:**
- MIT xPRO: Designing and Building AI Products and Services (expected Aug 2026)
- OpenTelemetry Certified Associate (OTCA)
- Dynatrace Associate Certification

**Career summary in one sentence:** 20+ years driving availability, resiliency, and performance strategies in high-volume merchant services and financial technology — specialising in enterprise-wide telemetry, observability, NPMD, and AIOps.

**Key JPMorgan achievements relevant to this project:**
- Architected Riverbed AppResponse packet capture + Arista DMF visibility fabrics across 35+ global datacenters
- Deployed enterprise NetFlow handling 120M+ FPM into central AIOps
- First-in-firm CA APM (Wily Introscope) deployment; ~40% MTTR reduction
- Cisco Nexus Dashboard POC across 75 fabrics / 7,000+ switches
- Led OTel + AWS CloudWatch hybrid pilot
- Currently architecting AI-driven observability lab with OpenTelemetry and OpenLLMetry

---

## Project Goal

Build a **public lab** that demonstrates mastery over:
1. **Network observability** (eBPF — Beyla + Cilium/Hubble)
2. **APM / distributed tracing** (OpenTelemetry SDK)
3. **LLM / GenAI observability** (OpenLLMetry / traceloop-sdk)

...all married into **one unified OTel pipeline**, published on:
- **GitHub** (public repo, all code)
- **LinkedIn** (post per phase)
- **Substack** (deep-dive blog per phase)

**Core thesis / narrative:** *"App observability tells you something is broken. Network observability tells you why."*

---

## The 8-Phase Roadmap

| Phase | Title | Content hook |
|---|---|---|
| 1 | Foundation | Vanilla 3-service app on AWS EKS. Public GitHub repo. Helm + Terraform IaC. |
| 2 | Full MELT + Network | OTel SDK on app. Beyla eBPF for L7 spans. Hubble for flow metrics. Dash0 backend. |
| 3 | The Network Blindspot Demo | Inject TCP retransmits / DNS failures. App sees latency. Only eBPF shows why. |
| 4 | GenAI Observability | Add LLM feature to app. OpenLLMetry SDK. Token/cost/latency in same trace as HTTP span. |
| 5 | AIOps Layer | Adaptive baselines, anomaly detection, predictive alerting, MTTR reduction story. |
| 6 | Hybrid & Multi-Cloud | Extend to on-prem k3s, GCP GKE, Azure AKS. OTel Collector federation. |
| 7 | Multi-Backend Comparison | Add Dynatrace and Datadog alongside Dash0. Same OTel signal, three lenses. |
| 8 | Public Packaging | README, runbooks, architecture diagrams, one-click deploy, Substack series wrap-up. |

**Current status:** Pre-coding. All risk analysis and version verification complete. Ready to begin Phase 1 implementation.

---

## Application Architecture (Phase 1)

Three services, all Python/FastAPI + one Node.js service:

```
┌─────────────────────────────────────────────┐
│  API Gateway (Python FastAPI)               │
│  Port 8000 — routes to backend services     │
└────────────────┬────────────────────────────┘
                 │ HTTP
        ┌────────┴────────┐
        ▼                 ▼
┌──────────────┐  ┌──────────────────┐
│ Product Svc  │  │  LLM Svc         │
│ (Python)     │  │  (Python)        │
│ + PostgreSQL │  │  calls OpenAI /  │
│              │  │  AWS Bedrock     │
└──────────────┘  └──────────────────┘
```

Simple enough to instrument completely. Complex enough for realistic distributed traces, network flows, and LLM spans.

---

## Verified Version Table (sourced from authoritative registries, June 13, 2026)

### Runtimes
| Component | Version | Source |
|---|---|---|
| Python | 3.13.14 | python.org (Jun 10 2026) |
| Node.js | 24.16.0 LTS ("Krypton") | nodejs.org |

### OTel SDK — Python
| Package | Version |
|---|---|
| `opentelemetry-api` | 1.42.1 |
| `opentelemetry-sdk` | 1.42.1 |
| `opentelemetry-instrumentation-fastapi` | 0.63b1 |
| `opentelemetry-instrumentation-psycopg2` | 0.63b1 |
| `opentelemetry-exporter-otlp-proto-grpc` | 1.42.1 |
| `opentelemetry-semantic-conventions` | 0.63b1 |

> Rule: 1.42.1 SDK packages and 0.63b1 contrib packages always installed together. Never mix cycles.

### OTel SDK — Node.js
| Package | Version |
|---|---|
| `@opentelemetry/sdk-node` | 0.218.0 |
| `@opentelemetry/api` | 1.9.x |
| `@opentelemetry/sdk-metrics` | 2.8.0 |
| `@opentelemetry/exporter-trace-otlp-grpc` | 0.218.0 |

### OpenLLMetry
| Package | Version |
|---|---|
| `traceloop-sdk` (Python) | 0.61.0 |
| `@traceloop/node-server-sdk` (Node) | 0.60.0 |

### eBPF / Network
| Component | Version |
|---|---|
| Cilium CNI | 1.19.4 |
| Hubble (bundled) | with Cilium 1.19.4 |
| Grafana Beyla | 3.20.0 (Helm chart 1.16.8) |

### OTel Collector
| Component | Version |
|---|---|
| OTel Collector Contrib | v0.154.0 |

### Infrastructure
| Component | Version |
|---|---|
| AWS EKS | Kubernetes 1.35 |
| k3s (on-prem, Phase 6) | v1.36.1+k3s1 |
| GKE (Phase 6) | 1.35.x Standard |
| AKS (Phase 6) | 1.35.x |

### IaC / CI/CD
| Component | Version |
|---|---|
| Terraform | 1.15.6 |
| Terraform AWS provider | 6.50.0 |
| Helm | 4.2.1 |

---

## Technology Decisions & Rationale

### Why Beyla instead of relying on hubble-otel for L7 spans
`cilium/hubble-otel` is **officially archived and unmaintained**. There is an open Cilium issue (#41259) for native Envoy-based OTel L7 tracing but it is not implemented yet. Beyla is the correct replacement: it emits OTLP-native L7 spans with W3C traceparent propagation. Hubble is kept for L3/L4 flow metrics via Prometheus scrape.

**eBPF signal split:**
- Beyla → L7 RED spans + network-level span timing → OTLP → Collector (PRIMARY)
- Hubble → L3/L4 flow metrics → Prometheus scrape → Collector (METRICS ONLY)

### Why no Dynatrace OneAgent
OneAgent conflicts with Cilium CNI at the kernel level — would cause pod scheduling failures. Use Dynatrace OTLP ingest endpoint only (`https://{env}.live.dynatrace.com/api/v2/otlp`). Confirmed supported by Dynatrace docs.

### Why Dash0 is the primary backend (Phases 1–6)
Dash0 is built from the ground up to be truly OpenTelemetry-native — not a proprietary platform with an OTLP on-ramp. It stores OTel data in OTel format without translation loss. Critical for demonstrating GenAI semconv attributes cleanly. Dynatrace and Datadog added in Phase 7 for vendor comparison content.

### Why Python 3.13 not 3.14
OTel instrumentation contrib packages (0.55b1) lag Python releases by one cycle. 3.14 dropped Oct 2025 but contrib validation is not yet complete. 3.13.14 is stable and fully supported.

### Why Node 24 LTS not Node 26
Node 26 became Current on May 5 2026 — becomes LTS in October 2026. OTel SDK 0.218.0 is tested against Node 20 and 22 LTS. Node 24 LTS is the safe choice.

### Why Helm 4 (not 3)
Helm 4.2.1 is stable and backward compatible with Helm 3 charts. No reason to stay on 3.

### Why OpenTofu is NOT used
HashiCorp Terraform 1.15.6 is used. OpenTofu (Linux Foundation fork, 1.11.6) is the MPL-licensed alternative but introduces a different provider ecosystem. Since this is a personal lab showcase, Terraform is sufficient and more universally recognisable.

### Excluded tools and why
| Tool | Reason excluded |
|---|---|
| Pixie | Own protocol, not OTLP — breaks the chain |
| Jaeger/Zipkin | Format bridges add noise; Collector → backend directly is cleaner |
| Prometheus as backbone | Scrape model conflicts with OTel push model |
| Dynatrace OneAgent | CNI conflict with Cilium |
| Datadog Agent | Use Collector `datadog` exporter instead |
| hubble-otel | Archived and unmaintained |

---

## Critical Risks Identified (Pre-Flight Analysis)

### 🔴 CRITICAL — Datadog Connector required for APM Trace Metrics
Since OTel Collector Contrib v0.95.0, the Datadog Exporter no longer computes Trace Metrics. The `datadog/connector` must be wired into the traces pipeline or the Datadog APM page shows nothing.

Required Collector pipeline pattern:
```yaml
connectors:
  datadog/connector:
exporters:
  datadog/exporter:
    api:
      key: ${env:DD_API_KEY}
service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [datadog/connector, datadog/exporter]
    metrics:
      receivers: [otlp, datadog/connector]
      processors: [batch]
      exporters: [datadog/exporter]
```

### 🔴 CRITICAL — OpenLLMetry semantic convention drift
`gen_ai.prompt` and `gen_ai.completion` are deprecated in OTel GenAI Semconv v1.38.0+. `traceloop-sdk==0.61.0` is partially migrated but not fully aligned with v1.40.0. Pin version, do not float. Use Dash0 for GenAI showcase.

### 🔴 CRITICAL — OTel TracerProvider init order with OpenLLMetry
`Traceloop.init()` must be called AFTER the OTel `TracerProvider` is configured and set as global. If called before, OpenLLMetry creates its own provider and LLM spans get disconnected trace IDs.

Correct order:
```python
# 1. Configure and set global TracerProvider
trace.set_tracer_provider(provider)

# 2. Then init Traceloop
Traceloop.init(app_name="otel-lab", disable_batch=False)
```

### 🟡 WARNING — Beyla requires /sys/fs/cgroup volume mount
Without this mount, Beyla cannot track socket creation and some requests will not have context propagated. DaemonSet must include:
```yaml
volumeMounts:
  - name: cgroup
    mountPath: /sys/fs/cgroup
volumes:
  - name: cgroup
    hostPath:
      path: /sys/fs/cgroup
```

### 🟡 WARNING — EKS + Cilium requires specific Terraform sequencing
Cilium must be installed BEFORE worker node groups join the cluster. Node groups depend on Cilium Helm release. VPC CNI addon must be disabled at cluster creation. This is the #1 EKS+Cilium failure mode.

### 🟡 WARNING — k8sattributes processor requires ClusterRole
Without RBAC, every span arrives in backends with no Kubernetes metadata. ClusterRole must cover `pods`, `namespaces`, `nodes`, and `replicasets` with `get`, `watch`, `list` verbs.

### 🟡 WARNING — Dynatrace OTLP token requires 3 scopes
Token must have: `openTelemetryTrace.ingest`, `metrics.ingest`, `logs.ingest`

### 🟡 WARNING — Helm 4 schema validation may reject older Cilium chart values
Always specify chart version explicitly. Run `helm template --dry-run` before installing.

---

## Signal Coverage Map

| Signal | Beyla | Hubble | OTel SDK | OpenLLMetry |
|---|---|---|---|---|
| HTTP request duration | ✅ L7 RED | ✅ L3/L4 bytes | ✅ spans | — |
| DB query latency | ✅ TCP timing | ✅ bytes | ✅ spans | — |
| LLM token count | ❌ | ❌ | ❌ | ✅ gen_ai.usage.* |
| LLM latency | ✅ TCP | ✅ bytes | ❌ | ✅ span duration |
| TCP retransmits | ❌ | ✅ drop reason | ❌ | ❌ |
| DNS failures | ❌ | ✅ L7 DNS | ❌ | ❌ |
| mTLS errors | ✅ TLS handshake | ✅ policy deny | ❌ | ❌ |
| K8s pod metadata | ✅ k8sattrs | ✅ k8sattrs | ✅ k8sattrs | ✅ k8sattrs |

**Phase 3 demo scenario:** Inject TCP retransmits between services. App SDK shows latency but no error. Hubble metrics show drop counts. Beyla shows elevated span duration. Root cause visible ONLY via network layer — not in app traces alone. This is the money shot.

---

## Repository Structure (to be created in Phase 1)

```
otel-observability-lab/
├── VERSIONS.md                    # Pinned versions (separate artifact)
├── PREFLIGHT_RISKS.md             # Risk analysis (separate artifact)
├── MASTER_PROJECT_CONTEXT.md      # This file
├── terraform/
│   ├── eks/                       # AWS EKS cluster
│   ├── gke/                       # Phase 6
│   ├── aks/                       # Phase 6
│   └── k3s-onprem/                # Phase 6
├── helm/
│   ├── cilium-values.yaml
│   ├── beyla-values.yaml
│   └── otelcol-values.yaml
├── apps/
│   ├── gateway/                   # Python FastAPI
│   ├── product-svc/               # Python FastAPI + PostgreSQL
│   └── llm-svc/                   # Python FastAPI + OpenAI/Bedrock
├── collector/
│   ├── config-agent.yaml          # Per-environment local collector
│   └── config-gateway.yaml        # Central aggregation + fanout
├── rbac/
│   └── otelcol-clusterrole.yaml   # k8sattributes RBAC
├── scripts/
│   ├── install.sh                 # One-command bootstrap
│   └── fault-injection/           # Phase 3 chaos scripts
└── docs/
    ├── architecture/
    └── runbooks/
```

---

## OTel Collector Architecture

```
Per-environment (agent mode DaemonSet):
  Receivers:  otlp (4317/4318), hostmetrics, filelog
  Processors: memory_limiter → k8sattributes → resource → batch
  Exporters:  otlp → gateway collector

Central gateway (Deployment):
  Receivers:  otlp (from all environments), prometheus (Hubble metrics)
  Processors: memory_limiter → k8sattributes → resource → batch
  Exporters:
    otlp/dash0      → Dash0 OTLP/gRPC endpoint
    otlp/dynatrace  → https://{env}.live.dynatrace.com/api/v2/otlp (Phase 7)
    datadog         → datadog/connector + datadog/exporter (Phase 7)
```

---

## Multi-Cloud Infrastructure (Phase 6)

| Environment | K8s | CNI approach |
|---|---|---|
| AWS EKS | 1.35 | Replace VPC CNI with Cilium 1.19.4 (VPC addon disabled) |
| On-prem k3s | 1.36.1 | Install with `--flannel-backend=none`, then Cilium |
| GCP GKE | 1.35 | Disable default dataplane V2, install Cilium |
| Azure AKS | 1.35 | Native Cilium support (`--network-policy cilium`) since AKS 1.28 |

All four environments run a local OTel Collector in agent mode. All four forward to the central gateway Collector on EKS.

---

## Certifications Being Reinforced

| Certification | How this project supports it |
|---|---|
| OTCA (OpenTelemetry Certified Associate) | Every phase uses OTel SDK, Collector, and semantic conventions |
| Dynatrace Associate | Phase 7 Dynatrace OTLP integration, Davis AI correlation |
| MIT xPRO AI Products | Phase 4 OpenLLMetry, token/cost attribution, LLM observability |

---

## How to Resume This Project in a New Claude Conversation

1. Paste the contents of this file at the start of the conversation
2. State which phase you are working on
3. Reference `VERSIONS.md` and `PREFLIGHT_RISKS.md` as companion documents
4. Claude will have full context to continue without re-explanation

---

## Conversation History Summary

| Session | Date | What was decided/produced |
|---|---|---|
| Session 1 | Jun 13, 2026 | Full project scoped. 8-phase roadmap created. Initial stack proposed. |
| Session 1 | Jun 13, 2026 | Stack revised: hubble-otel → Beyla for L7. Azure AKS confirmed in Phase 6. |
| Session 1 | Jun 13, 2026 | All versions verified from authoritative sources (PyPI, npm, GitHub, python.org, etc.) |
| Session 1 | Jun 13, 2026 | Pre-flight risk analysis completed. 3 critical risks + 5 warnings documented. |
| Session 1 | Jun 13, 2026 | Three artifacts produced: VERSIONS.md, PREFLIGHT_RISKS.md, this file. |
| Next session | TBD | Begin Phase 1: Terraform EKS, Helm scaffolding, app skeletons, GitHub repo. |

---

*This document is the memory of the project. Keep it updated. Commit it to the root of the GitHub repo.*

---

## Session 2 — June 13, 2026

### What was built
- GitHub repo created: https://github.com/suritmaharana-maker/otel-observability-lab
- Claude Code installed on Windows (v2.1.177), authenticated
- All tools verified: Terraform 1.15.6, Helm 4.2.1, kubectl 1.34.1, git 2.51.0
- 21 files committed to main branch
- CI pipeline green — all 4 jobs passing

### Version corrections made during this session
| Component | Was | Now |
|---|---|---|
| Node.js | 24.15.0 | 24.16.0 |
| Terraform | 1.15.6 | 1.15.6 |
| OTel instrumentation-fastapi | 0.55b1 | 0.63b1 |
| OTel instrumentation-psycopg2 | 0.55b1 | 0.63b0 |

### EKS module v21 argument renames (VERIFIED — must never be forgotten)
| v20 | v21 |
|---|---|
| cluster_name | name |
| cluster_version | kubernetes_version |
| cluster_endpoint_public_access | endpoint_public_access |
| cluster_addons | addons |

### CI fixes required during this session
- `helm lint` does not accept `--version` flag — must `helm pull` chart first then lint
- Terraform version must be pinned in CI workflow, not assumed
- `terraform fmt` must pass before `terraform validate`
- File replacements must be verified with grep before committing

### Next session
Start with: terraform -chdir=terraform/eks init
Then: terraform -chdir=terraform/eks plan
Review plan together before any apply.

---

## Session 3 — June 14, 2026

### What was built
- EKS cluster fully operational with Cilium CNI, Hubble, CoreDNS, kube-proxy
- All infrastructure deployed via staged terraform apply with -target
- Phase 1 infrastructure proven end-to-end

### Critical lessons learned this session

#### Lesson 1: CoreDNS addon timeout
The EKS module v21 waits for addons to reach ACTIVE state immediately after cluster creation.
CoreDNS requires nodes to schedule on. With Cilium replacing the CNI there is no Fargate fallback.
FIX: Remove addons from EKS module entirely. Use standalone aws_eks_addon resources with
depends_on = [aws_eks_node_group.main].

#### Lesson 2: k8sServiceHost REQUIRED for Cilium ENI mode
Without k8sServiceHost set to the EKS API endpoint, Cilium init container cannot reach
the Kubernetes API before networking is initialised.
ERROR: "Unable to contact k8s api-server: dial tcp 172.20.0.1:443: i/o timeout"
FIX: k8sServiceHost: <endpoint without https://>  k8sServicePort: 443

#### Lesson 3: enableIPv4Masquerade REQUIRED alongside bpf.masquerade
bpf.masquerade: true alone is not sufficient in Cilium 1.19.
ERROR: "BPF masquerade requires --enable-ipv4-masquerade=true"
FIX: enableIPv4Masquerade: true must be set explicitly.

#### Lesson 4: Staged terraform apply is mandatory for Cilium on EKS
Never apply the entire plan at once. Required sequence:
  Step 1: terraform apply -target="module.vpc"
  Step 2: terraform apply -target="module.eks"
  Step 3: terraform apply -target="null_resource.patch_aws_node" -target="helm_release.cilium"
  Step 4: terraform apply -target="aws_eks_node_group.main"
  Step 5: terraform apply -target="aws_eks_addon.coredns" -target="aws_eks_addon.kube_proxy"
  Step 6: terraform apply -target="kubernetes_namespace.observability" -target="kubernetes_namespace.otel_lab"
Verify each step before proceeding to the next.

#### Lesson 5: Helm repo must be added before helm upgrade on Windows
helm repo add cilium https://helm.cilium.io && helm repo update
before any helm upgrade command.

#### Lesson 6: node group CREATE_FAILED recovers by delete + reimport
If node group fails in Terraform but nodes exist in AWS:
  terraform state rm aws_eks_node_group.main
  aws eks delete-nodegroup --cluster-name otel-lab --nodegroup-name otel-lab-main --region us-east-2
  Wait for deletion, then terraform apply -target="aws_eks_node_group.main"

### Verified working Cilium values (all required fields)
k8sServiceHost: 99B389CBB5B02A44A96D570AA7358F4E.gr7.us-east-2.eks.amazonaws.com
k8sServicePort: 443
enableIPv4Masquerade: true
bpf.masquerade: true
eni.enabled: true
ipam.mode: eni
routingMode: native
operator.unmanagedPodWatcher.restart: false

### Final cluster state when destroyed
- VPC: vpc-00a1138c8d1c4d109 (10.0.0.0/16)
- EKS endpoint: 99B389CBB5B02A44A96D570AA7358F4E.gr7.us-east-2.eks.amazonaws.com
- All pods healthy, all nodes Ready before destroy

### Next session
Run terraform apply in the correct staged sequence above.
The complete corrected codebase is in GitHub.
No code changes needed — just execute the 6-step apply sequence.

---

## Session 3 continued — June 14, 2026 (afternoon)

### MELT completed — all four signals in Dash0

| Signal | Status | Detail |
|---|---|---|
| M — Metrics | ✅ | host metrics: system.cpu.time, disk, network — 39 metrics from 3 nodes |
| E — Events | ✅ | span events flowing with traces |
| L — Logs | ✅ | 60 structured JSON logs, gateway service, trace_id + span_id in every record |
| T — Traces | ✅ | 212 spans, gateway → product-svc waterfall, p99 66.4ms |

### Key lessons from MELT instrumentation

#### structlog must bridge to stdlib logging for OTel to capture logs
- structlog with PrintLoggerFactory writes to stdout directly — OTel LoggingHandler never sees it
- Fix: use structlog.stdlib.LoggerFactory() + structlog.stdlib.BoundLogger
- Then attach OTelJSONFormatter to stdlib logging StreamHandler
- OTelLogExporter sends logs directly to Dash0 via OTLP — bypasses Collector

#### OTel package versions — all must be 0.63b1 (not mixing b0 and b1)
- opentelemetry-instrumentation-psycopg2==0.63b0 conflicts with fastapi==0.63b1
- Fix: use 0.63b1 for ALL contrib packages including psycopg2

#### OTel Collector Helm chart mode=daemonset had silent pipeline
- Helm chart with presets overrides config silently — no data flows
- Fix: deploy Collector as direct DaemonSet with explicit config (k8s/otelcol-direct.yaml)

#### Dash0 endpoint
- vpce endpoint: ingress.us-west-2.vpce.aws.dash0.com:4317 — VPC private only, does not work
- Public endpoint: ingress.us-west-2.aws.dash0.com:4317 — correct
- Auth: bearertokenauth/dash0 extension in Collector config

### Current cluster state
- Gateway: Python 3.13.14, FastAPI, OTel SDK 1.42.1, structlog, traces + logs
- Product-svc: Python 3.13.14, FastAPI, OTel SDK 1.42.1, psycopg2 instrumented
- OTel Collector: direct DaemonSet v0.154.0, hostmetrics + OTLP receiver, Dash0 exporter
- LoadBalancer: a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com

### Next: Phase 3 — eBPF
1. Deploy Beyla 3.20.0 DaemonSet — L7 eBPF spans alongside app spans
2. Add Hubble Prometheus scrape to Collector — L3/L4 flow metrics
3. Phase 3: network blindspot demo — inject TCP retransmits, show eBPF catches what APM misses

---

## Session 3 continued — eBPF layer complete

### Beyla deployed and working
- Beyla 3.20.0 (Helm chart 1.16.8) deployed as DaemonSet in otel-lab namespace
- 3 pods running — one per node — no restarts
- 177 new eBPF spans added alongside 212 OTel SDK spans = 389 total in Dash0
- Both SDK spans AND Beyla eBPF spans visible for same requests
- TCX mode — no Cilium conflict (kernel 6.12.90 supports TCX)

### Key discoveries
- AL2023 kernel is actually 6.12.90 — NOT 6.1 as originally documented
- TCX supported — Beyla and Cilium coexist perfectly, no bpf-filter-priority needed
- Beyla 3.20.0 is current stable (not 3.12.x as originally pinned)
- Beyla logs are silent by default — check Dash0 for span count increase

### Current signal status
| Signal | Source | Status |
|---|---|---|
| Host metrics | OTel Collector hostmetrics | ✅ Dash0 |
| App traces | OTel SDK gateway + product-svc | ✅ Dash0 — 212+ spans |
| eBPF L7 spans | Beyla 3.20.0 | ✅ Dash0 — 177+ new spans |
| App logs | OTel LogExporter + structlog | ✅ Dash0 — 60+ records |
| Hubble L3/L4 flows | OTel Collector prometheus/hubble receiver | ✅ Dash0 — hubble_flows_processed_total, beyla.network.flow.bytes |

### Phase 2 complete — all signals in Dash0

| Signal | Status | Detail |
|---|---|---|
| M — Host metrics | ✅ | system.cpu.time, disk, network — 39 metrics, 3 nodes |
| M — Hubble L3/L4 | ✅ | hubble_flows_processed_total, port_distribution, drop_total |
| M — Beyla network | ✅ | beyla.network.flow.bytes — 204 flow tuples, 25 attributes |
| E — Span events | ✅ | correlated with all traces |
| L — Logs | ✅ | structlog + OTelJSONFormatter, trace_id in every record, direct OTLP to Dash0 |
| T — App traces | ✅ | 503 spans, gateway → product-svc → SQL waterfall, p99 66ms |
| T — Beyla L7 eBPF | ✅ | SELECT products DATABASE span, processing, in queue, GET /products/* |

### Next: Phase 3 — Network Blindspot Demo
- Inject TCP fault between gateway and product-svc
- OTel SDK shows latency — no root cause visible
- Beyla + Hubble show packet drops / retransmits — root cause exposed
- The money shot: what APM alone can never tell you
