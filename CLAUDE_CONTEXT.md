# OTel Observability Lab — Claude Context Document
Generated: 2026-06-22 (PM session) | Use this as the first message in a new conversation

## FIRST MESSAGE FOR NEW CONVERSATION
Paste this entire document as your first message. Claude will have full context.

---

## 1. PROJECT IDENTITY & GOAL

**Owner:** Surit Maharana | Columbus OH (Powell) | suritmaharana@gmail.com | 614.638.9751
**GitHub:** suritmaharana-maker | Repo: https://github.com/suritmaharana-maker/otel-observability-lab
**Background:** 20yr JPMorgan Chase (ending 5/2026) — Riverbed AppResponse, Arista DMF, NetFlow 120M FPM, CA APM Wily Introscope, Dynatrace

**Ultimate Goal:** Build the definitive open-source AppResponse + NetProfiler equivalent in Kubernetes. Prove: "App observability tells you something is broken. Network observability tells you why. The OTel pipeline is the missing bridge. No vendor lock-in required."

**Optum Interview:** June 26, 2026 (Senior SRE) — prep material exists from Phases 1-7.

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
| 7.5 | AIOps RCA upgrades — absolute window + richer signals + healthy gate | ✅ COMPLETE (2026-06-22 PM) |
| 8 | On-prem bridge — k3s + NetFlow/sFlow via OTel | 🔲 PENDING |

---

## 3. CLUSTER STATE

**EKS Cluster:** otel-lab | us-east-2 | k8s v1.35.5-eks-0de9cde
**AMI:** AL2023 kernel 6.12 (ami-0358c5baa09a78b37)
**ELB:** a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com
**ECR:** 982920153340.dkr.ecr.us-east-2.amazonaws.com
**AWS Account:** 982920153340
**Dynatrace:** yta61562.live.dynatrace.com (trial — OneAgent ImagePullBackOff, token OTel_API_Token_v2 ROTATED 2026-06-22)
**Dash0:** console.dash0.com | org: Surit_org_1

**CURRENT STATE: RUNNING** (as of 2026-06-22 PM session)

Last known node IPs (ASG replaces on restart — ALWAYS re-check):
ip-10-0-1-17, ip-10-0-2-45, ip-10-0-3-181 (this session)

---

## 4. STARTUP SEQUENCE (EVERY RESTART)

> ⚠️ Two failure modes bite on EVERY restart because the ASG replaces nodes:
> 1. **node selectors** point at dead node names → pods stuck Pending
> 2. **IMDSv2 hop-limit resets to 1** → pods can't reach instance metadata →
>    botocore `NoCredentialsError` → llm-svc Bedrock calls 500.
> Both MUST be fixed after every restart. Step 2 was the root cause of a long
> debugging detour on 2026-06-22 — do not skip it.

```powershell
# 1. Get current running instances (ASG may have replaced them)
$ids = (aws ec2 describe-instances --region us-east-2 `
  --filters "Name=tag:eks:cluster-name,Values=otel-lab" "Name=instance-state-name,Values=running" `
  --query "Reservations[].Instances[].InstanceId" --output text) -split "\s+"

# 2. Fix IMDSv2 hop-limit (ALWAYS required — fixes Bedrock NoCredentialsError)
foreach ($id in $ids) {
  aws ec2 modify-instance-metadata-options --region us-east-2 --instance-id $id `
    --http-put-response-hop-limit 2 --http-endpoint enabled | Out-Null
  Write-Host "Fixed: $id"
}
# verify: should print hop-limit=2 for all three
foreach ($id in $ids) {
  $hop = aws ec2 describe-instances --region us-east-2 --instance-ids $id `
    --query "Reservations[].Instances[].MetadataOptions.HttpPutResponseHopLimit" --output text
  Write-Host "$id hop-limit=$hop"
}

# 3. Get current node names
kubectl get nodes

# 4. Scale up app deployments
kubectl scale deployment gateway product-svc llm-svc -n otel-lab --replicas=1

# 5. Fix node selectors — pods stick in Pending if selector points at a dead node.
#    Easiest: REMOVE the hostname nodeSelector so the scheduler places freely.
#    PowerShell-safe method (inline JSON patch is unreliable in PS):
'[{"op": "remove", "path": "/spec/template/spec/nodeSelector"}]' | Out-File -Encoding ascii patch.json
kubectl patch deployment gateway     -n otel-lab --type=json --patch-file patch.json
kubectl patch deployment product-svc -n otel-lab --type=json --patch-file patch.json
kubectl patch deployment llm-svc     -n otel-lab --type=json --patch-file patch.json
#    (If a deployment already has no nodeSelector, its patch errors harmlessly — ignore.)

# 6. Wait + verify pods Running
Start-Sleep -Seconds 15
kubectl get pods -n otel-lab -o wide

# 7. (If using Dynatrace) refresh DT token into collector + llm-svc
$encoded = kubectl get secret dynatrace-secret -n observability -o jsonpath='{.data.api-token}'
$DT_TOKEN = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($encoded))
kubectl set env daemonset/otelcol -n observability "DT_API_TOKEN=$DT_TOKEN" "DT_ENVIRONMENT_ID=yta61562"
kubectl set env deployment/llm-svc -n otel-lab "DT_API_TOKEN=$DT_TOKEN" "DT_ENVIRONMENT_ID=yta61562"
kubectl rollout restart daemonset/otelcol -n observability

# 8. Smoke test
$elb = "a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com"
Invoke-WebRequest -Uri "http://$elb/products" -UseBasicParsing -TimeoutSec 10 | Select-Object StatusCode
```

**PowerShell execution-policy note:** local `.ps1` scripts are blocked unless run as
`powershell -ExecutionPolicy Bypass -File .\script.ps1` (or `Unblock-File` the downloaded file).

---

## 5. PROVEN RESULTS — PHASE 7 (2026-06-22)

**Test design:** 20-minute structured fault-injection test, two fault windows.
Replicated post-transition on 2026-06-22 PM — results matched the original run almost exactly
(P5 differed by +1 OK, otherwise identical), proving reproducibility across an infra transition.

Run script committed: `run-phase7-baseline.ps1` (pre-flight checks + 5 phases + Dash0 window print).

| Phase | This run (PM) | Original | Window (PM, local EDT) |
|-------|---------------|----------|------------------------|
| P1 Normal | OK:58 ERR:0 | OK:58 ERR:0 | 17:43:37–17:46:39 |
| P2 Fault1 | OK:1 ERR:38 | OK:1 ERR:38 | 17:46:39–17:51:49 |
| P3 Normal | OK:96 ERR:0 | OK:96 ERR:0 | 17:51:49–17:56:52 |
| P4 Fault2 | OK:1 ERR:45 | OK:1 ERR:45 | 17:56:52–18:02:57 |
| P5 Normal | OK:116 ERR:0 | OK:115 ERR:0 | 18:02:57–18:09:02 |

**Fault mechanism:** `kubectl apply -f cnp-fault.yaml` (CiliumNetworkPolicy blocking gateway)

> ⏱️ TIMEZONE NOTE: terminal logs print **local EDT**. Dash0 / PromQL `@` anchors need **UTC**.
> EDT → UTC = +4h. Fault-2 17:56:52–18:02:57 EDT = **21:56:52–22:02:57Z**.

### Proven Signal Matrix (Dash0, Fault-2 window 21:56:52Z–22:02:57Z, absolute)

| Signal | Metric | Fault value | Behavior | Proven |
|--------|--------|-------------|----------|--------|
| Hubble policy drops | hubble_drop_total{POLICY_DENY} | 464.55 | SPIKE | ✅ |
| Beyla network flows | beyla.network.flow.bytes | 1,185,535 | (retry traffic) | ✅ |
| OBI network flows | obi.network.flow.bytes (gw→product-svc) | 16,921 | DROP | ✅ |
| OBI TCP failed | obi.stat.tcp.failed.connections | 46.23 | SPIKE | ✅ |
| App spans | dash0.spans (product-svc) | 0.0 | DROP TO ZERO | ✅ |
| OBI TCP RTT | obi.stat.tcp.rtt | — | sawtooth artifact | ❌ (rendering TBD) |

> Note on HTTP 5xx: during a hard block, requests never reach the app, so **no
> server-side 5xx span is generated** (error rate reads 0%). The drop / TCP-fail /
> spans-zero triad is the correct evidence for a total block, not the HTTP 5xx count.

### Dash0 PromQL (relative-window form; absolute uses `[<dur>] @ <epoch>`)
```
# Hubble drops
increase({otel_metric_name="hubble_drop_total", otel_metric_type="sum", protocol="TCP"}[2m])
# Beyla flows (gateway→product-svc)
increase({otel_metric_name="beyla.network.flow.bytes", k8s_src_owner_name="gateway", k8s_dst_owner_name="product-svc", k8s_dst_owner_type=~".*servi.*"}[1m])
# OBI flows (gateway→product-svc)
increase({otel_metric_name="obi.network.flow.bytes", k8s_src_owner_name="gateway", k8s_dst_owner_name="product-svc", k8s_dst_owner_type="Service"}[2m])
# OBI TCP failed connections
increase({otel_metric_name="obi.stat.tcp.failed.connections", k8s_src_owner_name="gateway"}[2m])
# Product-svc spans (AppO11y)
increase({otel_metric_name="dash0.spans", service_name="product-svc", telemetry_sdk_name="opentelemetry"}[1m])
# OBI TCP RTT p99
histogram_quantile(0.99, sum by (dash0_resource_id, dash0_resource_type, dash0_resource_name) (rate({otel_metric_name="obi.stat.tcp.rtt", otel_metric_type="histogram"}[2m])))
```

### Causal Chain (interview story)
CAUSE: `kubectl apply cnp-fault.yaml` (CiliumNetworkPolicy)
- EFFECT 1: hubble_drop_total SPIKED — L3/L4 policy enforcement visible
- EFFECT 2: obi.network.flow.bytes DROPPED — application flow bytes stopped
- EFFECT 3: obi.stat.tcp.failed SPIKED — TCP connection failures from gateway
- EFFECT 4: beyla.network.flow.bytes shows retry traffic — Beyla confirms same signal
- EFFECT 5: dash0.spans (product-svc) = ZERO — app layer confirms no traffic reached

---

## 5.5. PHASE 7.5 — AIOPS RCA UPGRADES (2026-06-22 PM) ✅

Three upgrades to the `/diagnose` AIOps pipeline, all deployed and proven live, committed
`d81235d` (gateway stale-file cleanup `7dce73f`).

### (a) Absolute time-window querying
`/diagnose` now accepts `?start=<RFC3339>&end=<RFC3339>` for an EXACT incident window,
not just relative `?window=5m`. Implemented as **instant query + PromQL `@` anchor**
(Option A): range = end−start (whole seconds), evaluation pinned to `end` epoch via `@`.
Relative `?window=` still works as fallback. Real-world: you diagnose the incident window,
not "last N minutes from now."
- Example: `/diagnose?backend=dash0&start=2026-06-22T21:56:52Z&end=2026-06-22T22:02:57Z`
- Response shows `window_absolute: true`, `window_range: "365s"`.

### (b) Three new Dash0 signals added to the RCA
- `obi_network_flow_bytes` (gateway→product-svc, k8s_dst_owner_type=Service)
- `obi_stat_tcp_failed_connections` (k8s_src_owner_name=gateway)
- `dash0_spans` (service_name=**product-svc**, telemetry_sdk_name=opentelemetry) — hardcoded
  to product-svc because that's the proven AppO11y "did traffic arrive" signal.
Prompt reframed to walk the causal chain so Nova reasons over relationships, not just lists values.

### (c) Deterministic healthy-path gate (anti-hallucination)
Before calling Bedrock: if `hubble_drop_total_policy_deny == 0` AND
`obi_tcp_failed_connections == 0`, return a deterministic "No anomaly detected"
(severity=none, model="none (deterministic healthy-path)", cost_usd=0.0) WITHOUT an LLM call.
Fixes a real false-positive where Nova confidently diagnosed a "critical Cilium fault" from
all-zero healthy data. Two-signal rule = the unambiguous "are we being blocked" fingerprint.

### Gateway param passthrough (Problem 1, also fixed today)
The deployed gateway runs `/app/main.py` from ConfigMap `gateway-code` (NOT the repo's old
`gateway.py`, now deleted). Its `/diagnose` handler only forwarded `window`+`service`, silently
dropping `start`/`end`/`backend`. Fixed to forward all of them (start/end only when both present).
Absolute-window RCA now reachable via the public ELB, not just port-forward.

### Proven RCA output (Fault-2, via ELB, absolute window)
```
ROOT CAUSE   Cilium network policy blocking traffic between gateway and product-svc
CONFIDENCE   HIGH        SEVERITY  CRITICAL
SIGNALS      POLICY_DENY 464.55 | OBI flow 16,921 (drop) | TCP failed 46.23 | spans 0.0
MODEL        Amazon Nova Micro (us.amazon.nova-micro-v1:0)
COST/LATENCY $0.0000549 | 3,440 ms total | 660 in / 227 out tokens
```

### The RCA prompt (dash0 backend), as built at runtime
```
You are an expert SRE analyzing a Kubernetes microservices incident.

ARCHITECTURE:
- gateway (8000) → product-svc (8001) → postgres (5432)
- gateway (8000) → llm-svc (8002) → AWS Bedrock
- Cilium CNI enforces CiliumNetworkPolicy — TCP POLICY_DENY means a policy is blocking traffic
- All services run on AWS EKS with Hubble network visibility
- Monitoring backend: DASH0

SIGNALS FROM DASH0 PROMETHEUS API ({window label}):
Network policy layer (L3/L4):
- hubble_drop_total (POLICY_DENY): {v} drops  → non-zero means Cilium is DENYING packets
Application HTTP layer:
- HTTP 5xx errors: {v} | HTTP total requests: {v} | HTTP error rate: {v}%
Network flow layer (eBPF):
- Beyla network flow bytes from {service}: {v} bytes
- OBI network flow bytes {service}→product-svc: {v} bytes  → DROP = app traffic stopped on the wire
TCP connection layer (eBPF StatsO11y):
- OBI TCP failed connections from {service}: {v}  → SPIKE = TCP handshakes failing
Application span layer (OTel SDK):
- product-svc spans emitted: {v}  → ZERO = no request reached product-svc

CAUSAL CHAIN TO EVALUATE:
A Cilium policy block signature: POLICY_DENY drops SPIKE → flow bytes DROP →
TCP failed SPIKE → product-svc spans ZERO, while app returns 5xx. Assess how many
signals align and weight confidence accordingly. If network signals fire but app
spans are non-zero, consider partial/degraded faults instead.

Based on these signals, provide a root cause analysis in this exact JSON format:
{ root_cause, confidence(high|medium|low), evidence[], recommendation,
  severity(critical|high|medium|low), explanation, backend_used }
Return ONLY the JSON object, no other text.
```
Inference config: `maxTokens=512, temperature=0.3`. Healthy-path gate runs BEFORE this; on a
clean window the prompt is never built.

---

## 6. INFRASTRUCTURE FILES

**Key k8s / app files**
- `apps/llm-svc/llm_svc.py` — AIOps /diagnose service (v0.7.0, Phase 7.5)
- `apps/gateway/main.py` — gateway (now in version control; runs from ConfigMap `gateway-code`)
- `k8s/obi-values.yaml` — OBI Helm values (working version)
- `k8s/otelcol-dynatrace.yaml` — Dual Dash0+Dynatrace OTel Collector
- `k8s/dynakube.yaml` — DynaKube CR v1beta6
- `cnp-fault.yaml` — CiliumNetworkPolicy fault injection
- `run-phase7-baseline.ps1` — 20-min baseline test runner

> ⚠️ GATEWAY DEPLOY IS DIFFERENT: gateway runs from ConfigMap `gateway-code` (key `main.py`),
> NOT a rebuilt image. To deploy a gateway change:
> ```powershell
> kubectl create configmap gateway-code -n otel-lab --from-file=main.py=.\apps\gateway\main.py --dry-run=client -o yaml | kubectl apply -f -
> kubectl rollout restart deployment/gateway -n otel-lab
> ```

> ⚠️ LLM-SVC DEPLOY — the `:latest` + IfNotPresent trap: `kubectl apply` / `rollout restart`
> may reuse a cached old image. Deploy by DIGEST to force the pull:
> ```powershell
> # after docker build/tag/push, take the digest the push prints:
> $DIGEST = "sha256:<from-push-output>"   # use the REAL digest, not a placeholder
> kubectl set image deployment/llm-svc llm-svc="982920153340.dkr.ecr.us-east-2.amazonaws.com/otel-lab/llm-svc@${DIGEST}" -n otel-lab
> kubectl rollout status deployment/llm-svc -n otel-lab --timeout=180s
> ```
> Verify via direct port-forward (the ELB `/health` reports the GATEWAY, not llm-svc):
> ```powershell
> kubectl port-forward deployment/llm-svc -n otel-lab 8002:8002   # terminal 1
> Invoke-RestMethod -Uri "http://localhost:8002/health" | ConvertTo-Json   # terminal 2 → expect "version":"0.7.0"
> ```

### OBI Configuration (WORKING — committed)
```yaml
# k8s/obi-values.yaml — key sections
preset: "application"
privileged: true
extraCapabilities: [SYS_RESOURCE]
volumes:
  - name: debugfs  | hostPath: { path: /sys/kernel/debug,   type: DirectoryOrCreate }
  - name: tracefs  | hostPath: { path: /sys/kernel/tracing, type: DirectoryOrCreate }
config.data:
  meter_provider.features: [network, stats, application]   # enables StatsO11y
  network: { enable: true, source: socket_filter }         # REQUIRED — Cilium uses TC direct action
env:
  OTEL_EBPF_METRICS_FEATURES: "network,stats,application"
  OTEL_EBPF_NETWORK_SOURCE: "socket_filter"
  OTEL_EBPF_KUBE_METADATA_ENABLE: "true"
```
Install: `helm install obi open-telemetry/opentelemetry-ebpf-instrumentation -f k8s\obi-values.yaml --namespace observability --version 0.9.2`

### Terraform / Ansible
- `terraform/eks/main.tf` — EKS (AL2023, k8s 1.35)
- `terraform/observability/main.tf` — observability module
- `ansible/fix-imds-hop-limit.yml` + `ansible/requirements.yml`
- `AmazonSSMManagedInstanceCore` + `AmazonBedrockFullAccess` on node role `otel-lab-node-group-role`

---

## 7. KNOWN ISSUES & LIMITATIONS

1. **IMDSv2 hop-limit resets to 1 on every node replacement** → botocore `NoCredentialsError`
   → llm-svc Bedrock 500s. MUST re-apply hop-limit=2 every restart (see Startup §4 step 2).
2. **Pixie** — ABANDONED. Kernel 6.12 (AL2023) breaks BCC runtime compilation. OBI (libbpf/CO-RE)
   is the replacement — works on 6.12.
3. **OBI TCP RTT** — exports but renders as sawtooth artifact in Dash0 (rate()+[2m] reset artifact).
   Try heatmap or p50/p99. BACKLOGGED.
4. **OneAgent** — ImagePullBackOff (trial PaaS token). Not blocking. Davis still readable via API.
5. **Dynatrace** — rejects monotonic cumulative sum + histogram metrics (beyla.network.flow.bytes,
   http.server.request.duration). Dash0 accepts all.
6. **OBI obi.network.flow.bytes under Cilium** — socket_filter captures retry traffic, not normal
   successful HTTP flows. Shows retry increase during fault. Complementary to Hubble, not a replacement.
7. **Gateway/ConfigMap drift risk** — gateway runs from ConfigMap, edited manually. Repo `main.py`
   and the live ConfigMap can diverge. Currently in sync (2026-06-22). Drift-proofing backlogged.
8. **DT token** — OTel_API_Token_v2 ROTATED 2026-06-22. When DT returns to scope, refresh the new
   value into BOTH `dynatrace-secret` (observability ns) AND `DT_API_TOKEN` env on llm-svc.

---

## 8. PENDING ITEMS (PRIORITIZED)

**Immediate (next session)**
1. Fix OBI TCP RTT rendering in Dash0 — try heatmap visualization
2. Resolve outstanding TC (Traffic Control) eBPF pipeline item
3. Gateway drift-proofing — build gateway from image OR generate ConfigMap from repo file in a script

**Phase 8 — On-prem bridge (k3s + NetFlow/sFlow)**
- Deploy k3s on local Ubuntu VM (kernel 5.15 — Pixie works here)
- Install NetFlow/sFlow receiver in OTel Collector
- Bridge on-prem flows to same Dash0 backend
- Prove the same AppResponse vision works across cloud + on-prem

**Other deferred**
- Re-sync rotated DT token into cluster when Dynatrace returns to scope
- Send blog posts to 4 contacts; Substack "The Bridge" setup

---

## 9. SIGNAL COVERAGE — AppResponse Vision

| Signal | Tool | Metric | Status |
|--------|------|--------|--------|
| Policy drops | Hubble → OTel | hubble_drop_total | ✅ PROVEN |
| HTTP RED metrics | Beyla AppO11y | http.server.request.duration | ✅ PROVEN |
| Network flow bytes | Beyla NetO11y | beyla.network.flow.bytes | ✅ PROVEN |
| Network flow bytes | OBI NetO11y | obi.network.flow.bytes | ✅ PROVEN |
| TCP failed connections | OBI StatsO11y | obi.stat.tcp.failed.connections | ✅ PROVEN |
| TCP RTT | OBI StatsO11y | obi.stat.tcp.rtt | ⚠️ EXISTS, rendering TBD |
| App spans | OTel SDK | dash0.spans | ✅ PROVEN |
| Multi-backend export | OTel Collector | Dash0 + Dynatrace | ✅ PROVEN |
| AIOps RCA | Bedrock (Nova Micro) | /diagnose endpoint | ✅ PROVEN (absolute window + healthy gate) |
| NetFlow/sFlow | Phase 8 | TBD | 🔲 PENDING |

---

## 10. NEW CONVERSATION STARTER

Paste the following as your first message in the new conversation:

> I am continuing an OTel observability lab project. Please read this entire context document carefully before responding.
>
> [PASTE THIS ENTIRE DOCUMENT]
>
> We are picking up where we left off. Completed in the last session (Phase 7.5): replicated the 20-min baseline post-transition, fixed the IMDS hop-limit Bedrock issue, upgraded /diagnose with absolute time-window querying + 3 new Dash0 signals + a deterministic healthy-path gate, fixed gateway param passthrough, committed everything, deleted the stale gateway.py, rotated the DT token.
>
> The immediate next steps are:
> 1. Fix OBI TCP RTT rendering in Dash0 (heatmap)
> 2. Resolve the outstanding TC eBPF pipeline item
> 3. Gateway drift-proofing
> 4. Begin Phase 8 — k3s on-prem bridge
>
> Check cluster state first (it may be STOPPED or RUNNING — re-check node IPs, they change on ASG replacement). If starting from stopped, run the full Startup Sequence including the IMDS hop-limit fix.
