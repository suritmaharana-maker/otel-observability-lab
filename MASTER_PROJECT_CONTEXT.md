# Observability Lab — Master Project Context

> **Purpose:** Single document to paste at the start of any new Claude conversation to restore full project context.
> **Last updated:** June 16, 2026

---

## Who I Am

**Name:** Surit Maharana
**Location:** Columbus, OH
**Contact:** suritmaharana@gmail.com | 614.638.9751 | linkedin.com/in/surit-maharana
**GitHub:** suritmaharana-maker
**Repo:** https://github.com/suritmaharana-maker/otel-observability-lab
**Current role:** Lead Infrastructure Engineer, Network Services — JPMorgan Chase (8/2010–5/2026, ending)
**Education:** B.E. Computer Science, Bangalore University

**In progress:**
- MIT xPRO: Designing and Building AI Products and Services (expected Aug 2026)
- OpenTelemetry Certified Associate (OTCA)
- Dynatrace Associate Certification

**Career summary:** 20+ years driving availability, resiliency, and performance strategies in high-volume merchant services and financial technology — specialising in enterprise-wide telemetry, observability, NPMD, and AIOps.

**Key JPMorgan achievements relevant to this project:**
- Architected Riverbed AppResponse packet capture + Arista DMF visibility fabrics across 35+ global datacenters
- Deployed enterprise NetFlow handling 120M+ FPM into central AIOps
- First-in-firm CA APM (Wily Introscope) deployment — ~40% MTTR reduction
- Cisco Nexus Dashboard POC across 75 fabrics / 7,000+ switches
- Led OTel + AWS CloudWatch hybrid pilot
- Currently architecting AI-driven observability lab with OpenTelemetry and OpenLLMetry

---

## Core Thesis

**"App observability tells you something is broken. Network observability tells you why. The OTel pipeline is the missing bridge between them at enterprise scale."**

---

## The 8-Phase Roadmap

| Phase | Title | Status |
|---|---|---|
| 1 | Foundation — Vanilla 3-service app on AWS EKS, Helm + Terraform IaC | ✅ COMPLETE |
| 2 | Full MELT + Network — OTel SDK, Beyla eBPF, Hubble flow metrics, Dash0 | ✅ COMPLETE |
| 3 | The Network Blindspot Demo — CiliumNetworkPolicy fault, POLICY_DENY in Dash0 | ✅ COMPLETE |
| 4 | GenAI Observability — OpenLLMetry SDK, token/cost/latency in same trace | ⏳ NEXT |
| 5 | AIOps Layer — Adaptive baselines, anomaly detection, predictive alerting | 🔲 PENDING |
| 6 | Hybrid & Multi-Cloud — on-prem k3s, GKE, AKS, OTel Collector federation | 🔲 PENDING |
| 7 | Multi-Backend Comparison — Dynatrace + Datadog alongside Dash0 | 🔲 PENDING |
| 8 | Public Packaging — README, runbooks, architecture diagrams, one-click deploy | 🔲 PENDING |

---

## Application Architecture

```
Internet
    │
    ▼
Classic ELB (port 80)
a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  gateway (Python FastAPI)                           │
│  Port 8000 → 8001 internal                         │
│  Node: ip-10-0-3-223 (us-east-2c)                  │
│  IP: 10.0.3.132                                     │
│  OTel SDK + structlog                               │
└────────────────────┬────────────────────────────────┘
                     │ HTTP → product-svc:8001
                     │ (cross-node: us-east-2c → us-east-2b)
                     ▼
┌─────────────────────────────────────────────────────┐
│  product-svc (Python FastAPI)                       │
│  Port 8001                                          │
│  Node: ip-10-0-2-140 (us-east-2b)                  │
│  IP: 10.0.2.39                                      │
│  OTel SDK + psycopg2 instrumentation                │
└────────────────────┬────────────────────────────────┘
                     │ TCP → postgres:5432
                     ▼
┌─────────────────────────────────────────────────────┐
│  postgres-0 (PostgreSQL StatefulSet)                │
│  Port 5432                                          │
│  Node: ip-10-0-3-223 (us-east-2c)                  │
│  IP: 10.0.3.162                                     │
└─────────────────────────────────────────────────────┘

llm-svc (Phase 4 — not yet deployed)
```

---

## OTel Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Signal Sources                          │
│                                                             │
│  gateway (SDK)    product-svc (SDK)    Beyla DaemonSet      │
│  OTLP/gRPC →      OTLP/gRPC →         OTLP/gRPC →         │
│                                                             │
│  Hubble metrics ─────────── Prometheus scrape ──────────── │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│           OTel Collector DaemonSet (v0.154.0)               │
│                                                             │
│  Receivers:                                                 │
│    otlp (4317 gRPC / 4318 HTTP)                             │
│    hostmetrics (CPU, disk, network, memory)                 │
│    prometheus (Hubble /metrics endpoint)                    │
│                                                             │
│  Processors:                                                │
│    memory_limiter → k8sattributes → resource → batch        │
│                                                             │
│  Exporters:                                                 │
│    otlp/dash0 → ingress.us-west-2.aws.dash0.com:4317        │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                        Dash0                                │
│                   org: Surit_org_1                          │
│                                                             │
│  Signals visible:                                           │
│  ✅ Traces (OTel SDK + Beyla L7 eBPF)                       │
│  ✅ Metrics (host + Hubble + beyla.network.flow.bytes)       │
│  ✅ Logs (structlog + OTelJSONFormatter)                     │
│  ✅ hubble_drop_total (POLICY_DENY spike on fault)           │
└─────────────────────────────────────────────────────────────┘
```

---

## Live Cluster State

**AWS Region:** us-east-2
**VPC:** vpc-00a1138c8d1c4d109 — 10.0.0.0/16
**EKS Cluster:** otel-lab — k8s v1.35.5-eks-0de9cde
**EKS Endpoint:** 99B389CBB5B02A44A96D570AA7358F4E.gr7.us-east-2.eks.amazonaws.com
**Kernel:** 6.12.90-120.164.amzn2023.x86_64 (Amazon Linux 2023)

### EC2 Instances (fixed — do not change between restarts)
| Instance | AZ | Node name changes on restart |
|---|---|---|
| i-0e94796ce751202a9 | us-east-2a | ip-10-0-1-XXX |
| i-09d84dc38796ba523 | us-east-2b | ip-10-0-2-XXX |
| i-0d66e999774a4e2b6 | us-east-2c | ip-10-0-3-XXX |

### Current Pod Placement (updates on every restart)
| Pod | IP | Node | AZ |
|---|---|---|---|
| gateway | 10.0.3.132 | ip-10-0-3-223 (node C) | us-east-2c |
| product-svc | 10.0.2.39 | ip-10-0-2-140 (node B) | us-east-2b |
| postgres-0 | 10.0.3.162 | ip-10-0-3-223 (node C) | us-east-2c |
| netshoot | 10.0.3.223 | ip-10-0-3-223 (node C) | us-east-2c |
| cilium on node C | — | cilium-vdzdt | us-east-2c |

**⚠️ Node hostnames and pod IPs change on every EC2 restart. Gateway PID changes too.**

---

## Phase 3 — Network Blindspot Demo (COMPLETE)

### What was demonstrated

Two fault injection methods were proven:

**Method 1 — tc netem (packet-level fault):**
- Injected via netshoot hostPID pod → nsenter into gateway PID → `tc qdisc add dev eth0 root netem delay 200ms loss 10%`
- Produced: 870ms–5257ms latency, timeout ERRORs
- Hubble CLI showed: exact tuples, 200ms ACK delays, 20-second connection silence
- Limitation: netem drops NOT visible in Dash0 hubble_drop_total (netem operates below Cilium's TCX observation point)

**Method 2 — CiliumNetworkPolicy ingressDeny (THE SMOKING GUN):**
- File: `cnp-fault.yaml` — denies TCP:8001 from gateway to product-svc
- Produced: 30/30 ERRORs at 5,000ms timeout (100% failure rate)
- **Dash0 hubble_drop_total showed TCP POLICY_DENY spike** ✅
- 90 errors (38.3%) visible in Dash0 tracing
- 60 error & fatal log records during fault window

### Key architectural finding
Netem operates below Cilium's TCX eBPF hook — not visible in Hubble/Dash0.
CiliumNetworkPolicy is enforced BY Cilium — fully visible in Hubble/Dash0.
For Dash0 chart visibility: always use CiliumNetworkPolicy for fault injection.

### Smoking gun evidence collected
1. ✅ hubble_drop_total — TCP POLICY_DENY hump during fault window
2. ✅ Tracing — 90 errors (38.3%) at 5,016ms p99
3. ✅ Logging — 60 error/fatal in fault window
4. ✅ Hubble CLI — exact tuple: gateway-55786f9ff5-szcfz:PORT → product-svc-8496f98d67-bnj49:8001 POLICY_DENY
5. ✅ Traffic output — clean baseline → 100% errors → clean recovery

### The LinkedIn story
**Left panel (APM):** 5,016ms timeout, 502 error, no product-svc span, no SQL span — "Something is broken. I don't know why."
**Right panel (eBPF/Hubble):** TCP POLICY_DENY spike on port 8001 — "A network policy is blocking gateway→product-svc. Root cause in seconds."

---

## Fault Injection Commands (Phase 3)

### CiliumNetworkPolicy fault (Dash0 visible — preferred)
```powershell
# Inject
kubectl apply -f cnp-fault.yaml
# Remove
kubectl delete -f cnp-fault.yaml --ignore-not-found
```

### netem fault (Hubble CLI visible only)
```powershell
# Find gateway PID first via findgw.sh
# Inject
kubectl exec -n otel-lab netshoot -- bash -c "nsenter --net=/proc/GATEWAY_PID/ns/net -- tc qdisc add dev eth0 root netem delay 200ms loss 10%"
# Remove
kubectl exec -n otel-lab netshoot -- bash -c "nsenter --net=/proc/GATEWAY_PID/ns/net -- tc qdisc del dev eth0 root"
```

### Hubble live observer (during fault)
```powershell
kubectl exec -n kube-system cilium-vdzdt -c cilium-agent -- hubble observe --from-namespace otel-lab --to-namespace otel-lab --verdict DROPPED -f
```

---

## Startup Sequence (CRITICAL — every restart)

```powershell
# 1. Start EC2 instances
aws ec2 start-instances --region us-east-2 --instance-ids i-0e94796ce751202a9 i-09d84dc38796ba523 i-0d66e999774a4e2b6

# 2. Run startup script (handles everything)
.\startup.ps1

# 3. Deploy netshoot on gateway's node
$gwNode = kubectl get pod -n otel-lab -l app=gateway -o jsonpath='{.items[0].spec.nodeName}'
# Update netshoot-pod.yaml nodeName and apply
kubectl apply -f netshoot-pod.yaml
kubectl wait --for=condition=Ready pod/netshoot -n otel-lab --timeout=60s

# 4. Find gateway PID
kubectl cp findgw.sh otel-lab/netshoot:/tmp/findgw.sh
kubectl exec -n otel-lab netshoot -- bash /tmp/findgw.sh

# 5. Sanity check
$elb = "a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com"
Invoke-WebRequest -Uri "http://$elb/products" -UseBasicParsing
```

### Shutdown sequence (before stopping instances)
```powershell
kubectl delete -f cnp-fault.yaml --ignore-not-found
kubectl exec -n otel-lab netshoot -- bash -c "nsenter --net=/proc/GATEWAY_PID/ns/net -- tc qdisc del dev eth0 root" 2>$null
kubectl scale deployment gateway -n otel-lab --replicas=0
kubectl scale deployment product-svc -n otel-lab --replicas=0
kubectl delete pod netshoot -n otel-lab --ignore-not-found
aws ec2 stop-instances --region us-east-2 --instance-ids i-0e94796ce751202a9 i-09d84dc38796ba523 i-0d66e999774a4e2b6
```

---

## Verified Versions (as of June 16, 2026)

### Infrastructure
| Component | Version |
|---|---|
| AWS EKS | k8s v1.35.5-eks-0de9cde |
| Amazon Linux | 2023.12.20260608 |
| Kernel | 6.12.90-120.164.amzn2023.x86_64 |
| containerd | 2.2.4+unknown |

### CNI / eBPF
| Component | Version |
|---|---|
| Cilium | 1.19.4 |
| Hubble (bundled) | with Cilium 1.19.4 |
| Beyla | 3.20.0 (Helm chart 1.16.8) |

### OTel
| Component | Version |
|---|---|
| OTel Collector Contrib | v0.154.0 |
| opentelemetry-api | 1.42.1 |
| opentelemetry-sdk | 1.42.1 |
| opentelemetry-instrumentation-fastapi | 0.63b1 |
| opentelemetry-instrumentation-psycopg2 | 0.63b1 |
| opentelemetry-exporter-otlp-proto-grpc | 1.42.1 |

### IaC
| Component | Version |
|---|---|
| Terraform | 1.15.6 |
| Helm | 4.2.1 |
| kubectl | 1.34.1 |

### Runtimes
| Component | Version |
|---|---|
| Python | 3.13.14 |
| Node.js | 24.16.0 LTS |

---

## Repo Files Reference

| File | Purpose |
|---|---|
| `startup.ps1` | One-command startup after EC2 restart |
| `findgw.sh` | Find gateway PID inside netshoot |
| `cnp-fault.yaml` | CiliumNetworkPolicy fault injection (Dash0 visible) |
| `netshoot-pod.yaml` | Privileged debug pod for netem injection |
| `inject.sh` / `inject_netshoot.sh` | netem fault injection scripts |
| `RUNBOOK_shutdown_startup.md` | Full shutdown/startup runbook |
| `PHASE3_NEXT_SESSION_PLAN.md` | Phase 3 demo plan and LinkedIn draft |
| `helm/beyla-values.yaml` | Beyla 3.20.0, 5s reporting_period |
| `MASTER_PROJECT_CONTEXT.md` | This file |
| `VERSIONS.md` | Verified versions |

---

## Known Issues / Tech Debt

| Issue | Impact | Fix |
|---|---|---|
| product-svc OTel export broken after restart | No DB query spans in Dash0 | kubectl rollout restart + DNS stabilization |
| startup.ps1 nodeSelector patch backtick escaping | Patch fails silently | Fix PowerShell JSON escaping |
| Dash0 auth token exposed in earlier session | Security | Rotate token |
| netshoot nodeName must be updated manually after restart | Ops burden | Automate in startup.ps1 |

---

## Next Steps

### Immediate (before Phase 4)
1. Commit cnp-fault.yaml + Phase 3 completion to GitHub
2. Fix product-svc OTel export (DB query spans)
3. Write LinkedIn post for Phase 3
4. Fix startup.ps1 nodeSelector patch

### Phase 4 — GenAI Observability
- Add llm-svc (Python FastAPI + AWS Bedrock)
- OpenLLMetry traceloop-sdk==0.61.0
- Token/cost/latency in same trace as HTTP span
- Pin: `Traceloop.init()` AFTER `trace.set_tracer_provider()`

### Phase 6 — On-prem bridge (unique Surit expertise)
- k3s + NetFlow/sFlow via OTel
- Bridges Riverbed/Arista on-prem expertise to cloud-native eBPF
- The connector that no enterprise has built yet

---

## Session History

| Session | Date | What was produced |
|---|---|---|
| 1 | Jun 13 | Project scoped, 8-phase roadmap, version verification, risk analysis |
| 2 | Jun 13 | GitHub repo, Claude Code, CI pipeline, 21 files committed |
| 3 | Jun 14 | EKS + Cilium deployed, all MELT signals in Dash0 |
| 4 | Jun 14 | Beyla 3.20.0 deployed, eBPF L7 spans + Hubble flow metrics in Dash0 |
| 5 | Jun 15 | Phase 3 planning, netem injection research, Hubble observer setup |
| 6 | Jun 16 | Phase 3 COMPLETE — CiliumNetworkPolicy fault, TCP POLICY_DENY spike in Dash0, 3-signal smoking gun |

---

*This document is the memory of the project. Keep it updated. Commit to repo root.*
