# OTel Observability Lab — Master Project Context
> **Last updated:** June 17, 2026 — Phase 4 complete
> **Purpose:** Paste this at the start of any new Claude session to restore full context.

---

## Who I Am

**Name:** Surit Maharana | Columbus OH | suritmaharana@gmail.com | 614.638.9751
**GitHub:** suritmaharana-maker | **Repo:** https://github.com/suritmaharana-maker/otel-observability-lab
**Background:** 20yr JPMorgan Chase (ending 5/2026) — Riverbed AppResponse, Arista DMF, NetFlow 120M FPM, CA APM Wily Introscope (~40% MTTR reduction), Cisco Nexus Dashboard POC

**Core thesis:** "App observability tells you something is broken. Network observability tells you why. The OTel pipeline is the missing bridge between them at enterprise scale."

---

## 8-Phase Roadmap

| Phase | Title | Status |
|---|---|---|
| 1 | Foundation — EKS, Cilium, Terraform IaC, GitHub CI | ✅ COMPLETE |
| 2 | Full MELT — OTel SDK, Beyla eBPF, Hubble, Dash0 | ✅ COMPLETE |
| 3 | Network Blindspot Demo — CiliumNetworkPolicy fault, POLICY_DENY in Dash0 | ✅ COMPLETE |
| 4 | GenAI Observability — Bedrock Converse API, gen_ai.* spans, cost/token tracking | ✅ COMPLETE |
| 5 | AIOps Layer — adaptive baselines, anomaly detection | 🔲 NEXT |
| 6 | Hybrid & Multi-Cloud — on-prem k3s, NetFlow/sFlow via OTel, GKE, AKS | 🔲 PENDING |
| 7 | Multi-Backend — Dynatrace + Datadog + Dash0 comparison | 🔲 PENDING |
| 8 | Public Packaging — README, one-click deploy, Substack | 🔲 PENDING |

---

## Live Cluster State (June 17, 2026)

**EKS:** otel-lab — k8s v1.35.5-eks-0de9cde | us-east-2
**ELB:** a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com
**VPC:** vpc-00a1138c8d1c4d109

### EC2 Instances (current — change after restart)
| Instance | AZ | IP |
|---|---|---|
| i-0ffab8f7b1ba96746 | us-east-2c | 10.0.3.223 (node C) |
| i-069cb3daa8dbeb5f7 | us-east-2b | 10.0.2.140 (node B) |
| i-026ca1f368d7d3690 | us-east-2a | 10.0.1.245 (node A) |

**IMDSv2 hop limit = 2 on all three instances** (required for Cilium + Bedrock)

### Pod Placement
| Pod | IP | Node |
|---|---|---|
| gateway | 10.0.3.146 | node C |
| product-svc | 10.0.2.183 | node B |
| llm-svc | 10.0.2.155 | node B |
| postgres-0 | 10.0.3.162 | node C |
| cilium on node C | — | cilium-vdzdt |

### ECR Repositories
| Repo | Image |
|---|---|
| 982920153340.dkr.ecr.us-east-2.amazonaws.com/otel-lab/gateway | ConfigMap-based (see below) |
| 982920153340.dkr.ecr.us-east-2.amazonaws.com/otel-lab/product-svc | ECR image |
| 982920153340.dkr.ecr.us-east-2.amazonaws.com/otel-lab/llm-svc | ECR image — Converse API |

### Important: gateway and product-svc use ConfigMap-mounted code
Gateway and product-svc load Python code from Kubernetes ConfigMaps:
- `gateway-code` ConfigMap → mounts as `/app/main.py`
- `product-svc-code` ConfigMap → mounts as `/app/main.py`
- llm-svc uses ECR image directly (no ConfigMap)

**To update gateway or product-svc code: update the ConfigMap, then rollout restart.**
**To update llm-svc: rebuild Docker image, push to ECR, rollout restart.**

---

## Phase 4 — GenAI Observability (COMPLETE)

### What was built
New `llm-svc` (Python FastAPI) deployed on node B:
- Calls `product-svc` to fetch catalog
- Calls AWS Bedrock via Converse API
- Emits manual OTel span `bedrock.converse` with full GenAI semantic convention attributes

### Key findings
- **Model:** `us.amazon.nova-micro-v1:0` (inference profile required — bare model IDs not supported)
- **IMDSv2 hop limit:** Must be 2 on EC2 nodes for Cilium + Bedrock IAM credentials to work
- **Bedrock Converse API** works with all models (Nova, Titan, Claude) — use instead of `invoke_model`
- **Anthropic Claude models** require FTU (First Time Use) form submission before first call
- **Docker credential helper** `docker-credential-ecr-login` required for ECR push on Windows

### The trace waterfall in Dash0
```
GET /recommendations (gateway) 936ms
  GET /recommendations (gateway client) 924ms
    GET /recommendations (llm-svc) 928ms
      GET /products (llm-svc→product-svc) 36ms
        SELECT products (postgres) 2ms
      bedrock.converse (llm-svc→Bedrock) 856ms
        gen_ai.system = aws.bedrock
        gen_ai.request.model = us.amazon.nova-micro-v1:0
        gen_ai.request.temperature = 0.3
        gen_ai.usage.input_tokens = 123
        gen_ai.usage.output_tokens = 62
        llm.cost_usd = 0.0000309
        llm.latency_ms = 855.8
```

### Beyla retransmit finding (verified June 17, 2026)
- Beyla 3.20.0 does NOT expose `tcp_retransmit_skb` as a user-facing metric
- Only `beyla_network_flow_bytes_total` is exposed at Prometheus endpoint
- Gemini hallucinated this capability — verified against official Grafana docs
- TCP retransmit visibility requires custom eBPF program (Phase 6 opportunity)

---

## Verified Versions

| Component | Version |
|---|---|
| EKS | k8s v1.35.5-eks-0de9cde |
| Kernel | 6.12.90-120.164.amzn2023.x86_64 |
| Cilium | 1.19.4 |
| Beyla | 3.20.0 |
| OTel Collector | v0.154.0 |
| OTel SDK | 1.42.1 |
| Bedrock model | us.amazon.nova-micro-v1:0 |
| Python | 3.13 |
| Docker | 29.5.2 |
| AWS CLI | v2 |

---

## Startup Sequence (EVERY RESTART)

```powershell
# 1. Start instances
aws ec2 start-instances --region us-east-2 --instance-ids i-0ffab8f7b1ba96746 i-069cb3daa8dbeb5f7 i-026ca1f368d7d3690

# 2. Wait 2 minutes then run startup script
Start-Sleep -Seconds 120
.\startup.ps1

# 3. Deploy netshoot on gateway node
$gwNode = kubectl get pod -n otel-lab -l app=gateway -o jsonpath='{.items[0].spec.nodeName}'
(Get-Content netshoot-pod.yaml) -replace 'nodeName:.*', "  nodeName: $gwNode" | Set-Content netshoot-pod.yaml
kubectl apply -f netshoot-pod.yaml
kubectl wait --for=condition=Ready pod/netshoot -n otel-lab --timeout=60s

# 4. Find gateway PID
$gwIP = kubectl get pod -n otel-lab -l app=gateway -o jsonpath='{.items[0].status.podIP}'
# Update findgw.sh with new IP, then:
kubectl cp findgw.sh otel-lab/netshoot:/tmp/findgw.sh
kubectl exec -n otel-lab netshoot -- bash /tmp/findgw.sh

# 5. Sanity check
$elb = "a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com"
Invoke-WebRequest -Uri "http://$elb/products" -UseBasicParsing
Invoke-WebRequest -Uri "http://$elb/recommendations?query=test" -UseBasicParsing -TimeoutSec 30
```

## Shutdown Sequence (BEFORE STOPPING)

```powershell
kubectl delete -f cnp-fault.yaml --ignore-not-found
kubectl scale deployment gateway product-svc llm-svc -n otel-lab --replicas=0
kubectl delete pod netshoot -n otel-lab --ignore-not-found
git add -A && git commit -m "wip: end of session $(Get-Date -Format 'yyyy-MM-dd')" && git push
aws ec2 stop-instances --region us-east-2 --instance-ids i-0ffab8f7b1ba96746 i-069cb3daa8dbeb5f7 i-026ca1f368d7d3690
```

---

## Repo Files Reference

| File | Purpose |
|---|---|
| `startup.ps1` | One-command startup automation |
| `load-generator.ps1` | Timestamped traffic generator with color-coded latency |
| `findgw.sh` | Find gateway PID inside netshoot |
| `cnp-fault.yaml` | CiliumNetworkPolicy fault injection |
| `netshoot-pod.yaml` | Privileged debug pod |
| `build-and-deploy-all.ps1` | Build + push + deploy all three services |
| `k8s/gateway.yaml` | Gateway deployment (ConfigMap-based) |
| `k8s/gateway-configmap.yaml` | Gateway Python code with /recommendations route |
| `k8s/product-svc.yaml` | Product-svc deployment (ConfigMap-based) |
| `k8s/llm-svc.yaml` | LLM-svc deployment (ECR image) |
| `apps/llm-svc/llm_svc.py` | Bedrock Converse API + gen_ai.* spans |
| `helm/beyla-values.yaml` | Beyla 3.20.0, socket_filter mode, 5s interval |
| `BACKUP_RECOVERY_PLAN.md` | Full backup and recovery procedures |
| `RUNBOOK_shutdown_startup.md` | Ops runbook |

---

## Known Issues / Tech Debt

| Issue | Impact | Fix |
|---|---|---|
| startup.ps1 nodeSelector patch broken | Pods may land on wrong nodes | Manual kubectl patch after startup |
| Anthropic Claude models need FTU form | Cannot use Claude on Bedrock | Submit form at console.aws.amazon.com/bedrock |
| Dash0 auth token needs rotation | Security | Rotate in Dash0 console → update k8s secret |
| product-svc uses old product descriptions | Minor | Update ConfigMap with better descriptions |
| Docker build uses cached layers | Stale code in images | Always use --no-cache for app code changes |

---

## Session History

| Session | Date | Outcome |
|---|---|---|
| 1-4 | Jun 13-14 | Infrastructure, CI, Phase 1+2 complete |
| 5-6 | Jun 15-16 | Phase 3 complete — POLICY_DENY smoking gun |
| 7 | Jun 17 | Phase 4 complete — bedrock.converse span in Dash0 |
