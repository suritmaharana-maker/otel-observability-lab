# OTel Observability Lab — Claude Context Document
# Generated: 2026-06-22 | Use this as the first message in a new conversation

---

## FIRST MESSAGE FOR NEW CONVERSATION

Paste this entire document as your first message. Claude will have full context.

---

## 1. PROJECT IDENTITY & GOAL

**Owner:** Surit Maharana | Columbus OH (Powell) | suritmaharana@gmail.com | 614.638.9751
**GitHub:** suritmaharana-maker | Repo: https://github.com/suritmaharana-maker/otel-observability-lab
**Background:** 20yr JPMorgan Chase (ending 5/2026) — Riverbed AppResponse, Arista DMF, NetFlow 120M FPM, CA APM Wily Introscope, Dynatrace

**Ultimate Goal:** Build the definitive open-source AppResponse + NetProfiler equivalent in Kubernetes.
Prove: "App observability tells you something is broken. Network observability tells you why.
The OTel pipeline is the missing bridge. No vendor lock-in required."

**Optum Interview:** June 26, 2026 (Senior SRE) — prep material exists from Phases 1-6.

---

## 2. 8-PHASE ROADMAP STATUS

| Phase | Title | Status |
|-------|-------|--------|
| 1 | Foundation — EKS, Cilium, Terraform, GitHub CI | ✅ COMPLETE |
| 2 | Full MELT — OTel SDK, Beyla, Hubble, Dash0 | ✅ COMPLETE |
| 3 | Network blindspot — CiliumNetworkPolicy fault | ✅ COMPLETE |
| 4 | GenAI observability — Bedrock, gen_ai.* spans | ✅ COMPLETE |
| 5 | AIOps RCA — LLM + Dash0 Prometheus API | ✅ COMPLETE |
| 6 | Multi-backend — Dynatrace + OneAgent + Davis AI | ✅ COMPLETE |
| 7 | OBI — NetO11y + StatsO11y + AppO11y | ✅ COMPLETE |
| 8 | On-prem bridge — k3s + NetFlow/sFlow via OTel | 🔲 PENDING |

---

## 3. CLUSTER STATE

**EKS Cluster:** otel-lab | us-east-2 | k8s v1.35.5-eks-0de9cde
**AMI:** AL2023 kernel 6.12 (ami-0358c5baa09a78b37)
**ELB:** a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com
**ECR:** 982920153340.dkr.ecr.us-east-2.amazonaws.com
**AWS Account:** 982920153340
**Dynatrace:** yta61562.live.dynatrace.com (trial — PaaS token expired, OneAgent broken)
**Dash0:** console.dash0.com | org: Surit_org_1

**CURRENT STATE: STOPPED** (instances stopped 2026-06-22 ~14:11 local EDT)

**Last known node IPs (ASG replaces on restart — always re-check):**
- ip-10-0-1-253, ip-10-0-2-253, ip-10-0-3-16 (last session)

---

## 4. STARTUP SEQUENCE (EVERY RESTART)

```powershell
# 1. Get current running instances (ASG may have replaced them)
$ids = (aws ec2 describe-instances --region us-east-2 `
  --filters "Name=tag:eks:cluster-name,Values=otel-lab" "Name=instance-state-name,Values=running" `
  --query "Reservations[].Instances[].InstanceId" --output text) -split "\s+"

# If stopped, start them first:
# $ids = ... state=stopped ... then aws ec2 start-instances

# 2. Fix IMDSv2 (ALWAYS required)
foreach ($id in $ids) {
    aws ec2 modify-instance-metadata-options --region us-east-2 --instance-id $id `
      --http-put-response-hop-limit 2 --http-endpoint enabled | Out-Null
    Write-Host "Fixed: $id"
}

# 3. Get current node names
kubectl get nodes

# 4. Fix node selectors (use actual node names from above)
$nodeB = "ip-10-0-2-XXX.us-east-2.compute.internal"
$nodeC = "ip-10-0-3-XXX.us-east-2.compute.internal"
kubectl patch deployment gateway -n otel-lab --type=json `
  -p="[{'op':'replace','path':'/spec/template/spec/nodeSelector','value':{'kubernetes.io/hostname':'$nodeC'}}]"
kubectl patch deployment product-svc -n otel-lab --type=json `
  -p="[{'op':'replace','path':'/spec/template/spec/nodeSelector','value':{'kubernetes.io/hostname':'$nodeB'}}]"
kubectl patch deployment llm-svc -n otel-lab --type=json `
  -p="[{'op':'replace','path':'/spec/template/spec/nodeSelector','value':{'kubernetes.io/hostname':'$nodeB'}}]"
kubectl scale deployment gateway product-svc llm-svc -n otel-lab --replicas=1

# 5. Fix DT token
$encoded = kubectl get secret dynatrace-secret -n observability -o jsonpath='{.data.api-token}'
$DT_TOKEN = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($encoded))
kubectl set env daemonset/otelcol -n observability "DT_API_TOKEN=$DT_TOKEN" "DT_ENVIRONMENT_ID=yta61562"
kubectl set env deployment/llm-svc -n otel-lab "DT_API_TOKEN=$DT_TOKEN" "DT_ENVIRONMENT_ID=yta61562"
kubectl rollout restart daemonset/otelcol -n observability
kubectl rollout status daemonset/otelcol -n observability --timeout=120s

# 6. Fix OneAgent ImagePullBackOff (trial token expired)
kubectl label namespace otel-lab dynatrace-monitor-
kubectl scale deployment gateway product-svc llm-svc -n otel-lab --replicas=0
Start-Sleep -Seconds 5
kubectl scale deployment gateway product-svc llm-svc -n otel-lab --replicas=1

# 7. Smoke test
$elb = "a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com"
Invoke-WebRequest -Uri "http://$elb/products" -UseBasicParsing -TimeoutSec 10 | Select-Object StatusCode
```

---

## 5. PROVEN RESULTS — PHASE 7 (2026-06-22)

### Test Design
20-minute structured fault injection test with two fault windows:
- P1 Normal:  13:45:20 - 13:48:20 (3 min) — OK:58 ERR:0
- P2 Fault1:  13:48:20 - 13:53:30 (5 min) — OK:1  ERR:38
- P3 Normal:  13:53:30 - 13:58:33 (5 min) — OK:96 ERR:0
- P4 Fault2:  13:58:33 - 14:04:38 (6 min) — OK:1  ERR:45
- P5 Normal:  14:04:38 - 14:10:42 (6 min) — OK:115 ERR:0

Fault mechanism: `kubectl apply -f cnp-fault.yaml` (CiliumNetworkPolicy blocking gateway)

### Proven Signal Matrix (all confirmed in Dash0, window 13:55-14:10)

| Signal | Metric | Fault Behavior | Proven |
|--------|--------|----------------|--------|
| Hubble policy drops | `hubble_drop_total{protocol=TCP}` | SPIKED during both faults | ✅ |
| Beyla network flows | `beyla.network.flow.bytes` (gateway→product-svc) | DROPPED during both faults | ✅ |
| OBI network flows | `obi.network.flow.bytes` (gateway→product-svc) | DROPPED during both faults | ✅ |
| OBI TCP failed | `obi.stat.tcp.failed.connections` (k8s_src=gateway) | SPIKED during both faults | ✅ |
| App spans | `dash0.spans` (product-svc) | DROPPED TO ZERO during both faults | ✅ |
| OBI TCP RTT | `obi.stat.tcp.rtt` | No clear correlation — sawtooth artifact | ❌ |

### Dash0 PromQL Queries (window: 13:55-14:10, calculate increase [2m])

```promql
# Hubble drops
increase({otel_metric_name = "hubble_drop_total", otel_metric_type = "sum", protocol = "TCP"}[2m])

# Beyla network flows (gateway→product-svc)
increase({otel_metric_name = "beyla.network.flow.bytes", otel_metric_type = "sum", k8s_src_owner_name = "gateway", k8s_dst_owner_name = "product-svc", k8s_dst_owner_type =~ ".*servi.*"}[1m])

# OBI network flows (gateway→product-svc)
increase({otel_metric_name = "obi.network.flow.bytes", otel_metric_type = "sum", k8s_src_owner_name = "gateway", k8s_dst_owner_name = "product-svc", k8s_dst_owner_type = "Service"}[2m])

# OBI TCP failed connections
increase({otel_metric_name = "obi.stat.tcp.failed.connections", otel_metric_type = "sum", k8s_src_owner_name = "gateway"}[2m])

# Product-svc spans (AppO11y)
increase({otel_metric_name = "dash0.spans", service_name = "product-svc", telemetry_sdk_name = "opentelemetry"}[1m])

# OBI TCP RTT (p99 — best rendering)
histogram_quantile(0.99, sum by (dash0_resource_id, dash0_resource_type, dash0_resource_name) (rate({otel_metric_name = "obi.stat.tcp.rtt", otel_metric_type = "histogram"}[2m])))
```

### Causal Chain (Interview Story)
```
CAUSE:    kubectl apply cnp-fault.yaml (CiliumNetworkPolicy)
EFFECT 1: hubble_drop_total SPIKED         — L3/L4 policy enforcement visible
EFFECT 2: obi.network.flow.bytes DROPPED   — application flow bytes stopped
EFFECT 3: obi.stat.tcp.failed SPIKED       — TCP connection failures from gateway
EFFECT 4: beyla.network.flow.bytes DROPPED — Beyla confirms same signal
EFFECT 5: dash0.spans (product-svc) = ZERO — app layer confirms no traffic reached
```

---

## 6. INFRASTRUCTURE FILES

### Key k8s files
- `k8s/obi-values.yaml` — OBI Helm values (current working version)
- `k8s/otelcol-dynatrace.yaml` — Dual Dash0+Dynatrace OTel Collector
- `k8s/dynakube.yaml` — DynaKube CR v1beta6
- `cnp-fault.yaml` — CiliumNetworkPolicy fault injection

### OBI Configuration (WORKING — committed to GitHub)
```yaml
# k8s/obi-values.yaml — key sections
preset: "application"
privileged: true
extraCapabilities: [SYS_RESOURCE]
volumes:
  - name: debugfs
    hostPath: { path: /sys/kernel/debug, type: DirectoryOrCreate }
  - name: tracefs
    hostPath: { path: /sys/kernel/tracing, type: DirectoryOrCreate }
volumeMounts:
  - { name: debugfs, mountPath: /sys/kernel/debug }
  - { name: tracefs, mountPath: /sys/kernel/tracing }
config.data:
  meter_provider:
    features: [network, stats, application]  # THIS enables StatsO11y
  network:
    enable: true
    source: socket_filter  # REQUIRED — Cilium uses TC direct action
env:
  OTEL_EBPF_METRICS_FEATURES: "network,stats,application"
  OTEL_EBPF_NETWORK_SOURCE: "socket_filter"
  OTEL_EBPF_KUBE_METADATA_ENABLE: "true"
```

### OBI Install Command
```powershell
helm install obi open-telemetry/opentelemetry-ebpf-instrumentation `
  -f k8s\obi-values.yaml --namespace observability --version 0.9.2
```

### Terraform
- `terraform/eks/main.tf` — EKS cluster (AL2023, k8s 1.35, validated)
- `terraform/observability/main.tf` — observability module

### Ansible
- `ansible/fix-imds-hop-limit.yml` + `ansible/requirements.yml`
- `AmazonSSMManagedInstanceCore` policy on node role `otel-lab-node-group-role`

---

## 7. KNOWN ISSUES & LIMITATIONS

1. **Pixie** — ABANDONED. Kernel 6.12 (AL2023) breaks BCC runtime compilation.
   All available EKS AMIs (AL2023 6.12, Ubuntu 24.04 6.17, Ubuntu 22.04 6.8) break Pixie.
   OBI with libbpf/CO-RE is the replacement — works on kernel 6.12.

2. **OBI TCP RTT** — metric exists and exports but shows sawtooth artifact in Dash0.
   Need to investigate proper rendering. Try heatmap or p50/p99 percentile queries.
   Root cause: Dash0 renders histogram with [2m] rate() creating reset artifacts.

3. **OneAgent** — ImagePullBackOff (trial PaaS token expired). Not blocking anything.
   Davis AI problems still readable via API directly.

4. **Dynatrace** — rejects monotonic cumulative sum and histogram metrics.
   `beyla.network.flow.bytes`, `http.server.request.duration` rejected.
   Dash0 accepts all. DT only sees what it natively supports.

5. **OBI `obi.network.flow.bytes` under Cilium** — socket_filter captures retry traffic,
   not normal successful HTTP flows. Metric shows increase during fault (retry storm),
   decrease after fault removed. Complementary to Hubble, not replacement.

6. **DT token** — dt0c01.6DSWIXSQZYH7Z... needs rotation (exposed in chat).

---

## 8. PENDING ITEMS (PRIORITIZED)

### Immediate (next session)
1. Fix OBI TCP RTT rendering in Dash0 — try heatmap visualization
2. Commit final test results to GitHub with proper commit message
3. Rotate DT token (security)

### Phase 8 — On-prem bridge (k3s + NetFlow/sFlow)
- Deploy k3s on local Ubuntu VM (kernel 5.15 — Pixie works here)
- Install NetFlow/sFlow receiver in OTel Collector
- Bridge on-prem flows to same Dash0 backend
- Prove same AppResponse vision works across cloud + on-prem

### Other deferred
- Fix /diagnose?backend=dynatrace bug (httpx vs urllib)
- Send blog posts to 4 contacts
- Substack "The Bridge" setup

---

## 9. SIGNAL COVERAGE — AppResponse Vision

| Signal | Tool | Metric | Status |
|--------|------|--------|--------|
| Policy drops | Hubble → OTel | `hubble_drop_total` | ✅ PROVEN |
| HTTP RED metrics | Beyla AppO11y | `http.server.request.duration` | ✅ PROVEN |
| Network flow bytes | Beyla NetO11y | `beyla.network.flow.bytes` | ✅ PROVEN |
| Network flow bytes | OBI NetO11y | `obi.network.flow.bytes` | ✅ PROVEN |
| TCP failed connections | OBI StatsO11y | `obi.stat.tcp.failed.connections` | ✅ PROVEN |
| TCP RTT | OBI StatsO11y | `obi.stat.tcp.rtt` | ⚠️ EXISTS, rendering TBD |
| App spans | OTel SDK | `dash0.spans` | ✅ PROVEN |
| Multi-backend export | OTel Collector | Dash0 + Dynatrace | ✅ PROVEN |
| AIOps RCA | Bedrock LLM | /diagnose endpoint | ✅ PROVEN |
| NetFlow/sFlow | Phase 8 | TBD | 🔲 PENDING |

---

## 10. NEW CONVERSATION STARTER

Paste the following as your first message in the new conversation:

---

I am continuing an OTel observability lab project. Please read this entire context document carefully before responding.

[PASTE THIS ENTIRE DOCUMENT]

We are picking up where we left off. The immediate next steps are:
1. Fix OBI TCP RTT rendering in Dash0
2. Commit Phase 7 final results to GitHub
3. Begin Phase 8 — k3s on-prem bridge

The cluster is currently STOPPED. Do not start it until we have a clear plan for what we are doing next.

---


---

## 11. AIOPS RCA — FULL IMPLEMENTATION DETAILS

### Architecture
`llm-svc` is a Python FastAPI service deployed in `otel-lab` namespace.
It exposes a `/diagnose` endpoint that:
1. Queries Prometheus metrics from the active backend (Dash0 or Dynatrace)
2. Passes signals to AWS Bedrock (Claude claude-sonnet-4-6) for root cause analysis
3. Returns structured JSON with diagnosis

### Endpoint
```
GET http://<ELB>/diagnose?window=5m&backend=dash0
GET http://<ELB>/diagnose?window=30m&backend=dynatrace
```

### OTel (Dash0) Backend — How It Works
llm-svc queries Dash0 Prometheus API with these signals:

```python
# Hubble policy drops
hubble_drop_total = query_prometheus(
    f'increase(hubble_drop_total{{reason="POLICY_DENY"}}[{window}])'
)

# HTTP error rate
http_error_rate = query_prometheus(
    f'rate(http_server_request_duration_seconds_count{{http_response_status_code=~"5.."}}[{window}])'
)

# Network flow bytes
network_flow = query_prometheus(
    f'increase(beyla_network_flow_bytes_total[{window}])'
)
```

**Proven results (Phase 5):**
```
GET /diagnose?window=5m&backend=dash0
→ ROOT CAUSE:  "Cilium network policy blocking traffic between microservices"
→ CONFIDENCE:  HIGH
→ SEVERITY:    CRITICAL
→ drops:       207.63
```

### Dynatrace Backend — How It Works
llm-svc queries Dynatrace Problems API directly via urllib:

```python
import urllib.request, json, os

token = os.environ.get('DT_API_TOKEN', '')
env = os.environ.get('DT_ENVIRONMENT_ID', 'yta61562')
url = f'https://{env}.live.dynatrace.com/api/v2/problems?from=now-{window}'
req = urllib.request.Request(url, headers={'Authorization': f'Api-Token {token}'})
r = urllib.request.urlopen(req, timeout=10)
data = json.loads(r.read().decode())
problems = data.get('problems', [])
```

**CRITICAL NOTE — httpx vs urllib bug:**
The llm-svc code has a bug where the async httpx call does NOT return Davis problems
even when the token is correct. The urllib call works perfectly.
Direct API verification always works:
```powershell
$headers = @{ Authorization = "Api-Token $DT_TOKEN" }
Invoke-WebRequest -Uri "https://yta61562.live.dynatrace.com/api/v2/problems?from=now-30m" -Headers $headers
```

### Davis AI — Proven Firing Behavior (Phase 6)
```
FAULT injected:          00:20:05 (CiliumNetworkPolicy)
Failure rate increase:   Fired 00:21:00 (55 seconds after fault)
Response time degradation: Fired 00:22:00 (115 seconds after fault)
Both problems CLOSED:    00:28:09 (when fault removed)
```

**Davis problem IDs (confirmed):** P-260611, P-260612

**Token requirements for DT backend:**
- `problems.read` — required to read Davis problems
- `metrics.ingest`, `logs.ingest`, `openTelemetryTrace.ingest` — for OTel Collector
- Token name in DT UI: `OTel_API_Token_v2`
- Token stored in: `dynatrace-secret` in `observability` namespace AND as env var in `llm-svc`

### Setting DT Token in llm-svc
```powershell
$encoded = kubectl get secret dynatrace-secret -n observability -o jsonpath='{.data.api-token}'
$DT_TOKEN = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($encoded))
kubectl set env deployment/llm-svc -n otel-lab "DT_API_TOKEN=$DT_TOKEN" "DT_ENVIRONMENT_ID=yta61562"
kubectl rollout restart deployment/llm-svc -n otel-lab
```

### Verified End-to-End Test Results (Phase 6, June 21 2026)
```
=== DASH0 ===
ROOT CAUSE:  "Cilium network policy blocking traffic between microservices"
CONFIDENCE:  HIGH
SEVERITY:    CRITICAL
drops:       207.63

=== DYNATRACE (direct API) ===
Total problems: 3
- Failure rate increase    CLOSED  (started 00:21:00)
- Response time degradation CLOSED (started 00:22:00)
- Monitoring not available  OPEN

=== DYNATRACE (/diagnose endpoint) ===
ROOT CAUSE:  "Kubernetes Cilium network policies blocking traffic between services"
CONFIDENCE:  HIGH
NOTE: Davis problems not surfaced due to httpx bug — fix pending
```

### Known Bug — /diagnose?backend=dynatrace
The llm-svc `/diagnose?backend=dynatrace` returns ROOT CAUSE correctly (Bedrock LLM inference)
but `davis_active_problems` is empty due to async httpx not returning DT API response.
Workaround: query DT Problems API directly via PowerShell (shown above).
Fix: replace httpx with urllib in llm-svc collect_dynatrace_signals function.

### llm-svc Container
```
ECR image: 982920153340.dkr.ecr.us-east-2.amazonaws.com/otel-lab/llm-svc:latest
Namespace: otel-lab
Port: 8001 (internal), accessed via gateway at /diagnose
AWS Bedrock model: us.anthropic.claude-3-5-sonnet-20241022-v2:0
Region: us-east-2
Required IAM: AmazonBedrockFullAccess (on node role otel-lab-node-group-role)
```

