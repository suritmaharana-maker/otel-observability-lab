# OTel Observability Lab — Claude Code Context

## CODING RULES — READ BEFORE DOING ANYTHING
1. VERSIONED DEPENDENCIES: Before writing any code referencing an external module,
   library, package, or tool — fetch the official docs for the EXACT pinned version.
   Never rely on memory or training data for argument names, API shape, or flags.
2. CLI COMMANDS: Verify exact flag syntax from official docs before writing any
   shell command or CI step. Never assume a flag exists — confirm it.
3. FORMAT FIRST: All Terraform must comply with terraform fmt before presenting.
   All YAML must have correct indentation. All Python must pass ruff.
4. VERIFY FILES LANDED: After any file correction, ask the user to grep/Select-String
   to confirm the change is on disk before committing. Never assume it worked.
5. NO INCREMENTAL PATCHES: When a file has errors, rewrite from scratch after
   fetching authoritative docs. Do not patch incrementally.
6. STATE EXPECTED OUTPUT: Before asking the user to run any command, state what
   the expected output looks like so deviations are caught immediately.
7. ONE CHANGE PER COMMIT: Never bundle multiple fixes. Makes failures impossible to isolate.
8. NEVER ASSUME: If uncertain about a version, flag, or argument — say so and look it up.

---

## Project owner
Surit Maharana — Principal Network Observability Engineer
GitHub: suritmaharana-maker
Repo: https://github.com/suritmaharana-maker/otel-observability-lab

## What this project is
A fully public, production-grade lab demonstrating:
- Network observability (eBPF — Cilium/Hubble + Grafana Beyla)
- APM / distributed tracing (OpenTelemetry SDK)
- LLM / GenAI observability (OpenLLMetry / traceloop-sdk)

All married into ONE unified OTel Collector pipeline across AWS EKS,
on-prem k3s, GCP GKE, and Azure AKS.

Core thesis: "App observability tells you something is broken.
Network observability tells you why."

## Current status
Phase 1 — Foundation complete.
- GitHub repo live: https://github.com/suritmaharana-maker/otel-observability-lab
- CI pipeline green (terraform-validate, helm-lint, python-lint, docker-build)
- Next step: terraform init → terraform plan → terraform apply

## Architecture
Three Python FastAPI services:
- gateway (port 8000) — API gateway, routes to product-svc and llm-svc
- product-svc (port 8001) — product catalog + PostgreSQL
- llm-svc (port 8002) — calls AWS Bedrock (Claude) for AI features

## Pinned versions — DO NOT change without checking VERSIONS.md
- Python: 3.13.14
- Node.js: 24.16.0 LTS
- opentelemetry-sdk: 1.42.1
- opentelemetry-instrumentation-fastapi: 0.63b1  (aligns with SDK 1.42.1)
- opentelemetry-instrumentation-psycopg2: 0.63b0  (aligns with SDK 1.42.1)
- traceloop-sdk: 0.61.0
- Cilium CNI: 1.19.4
- Grafana Beyla: 3.12.x
- OTel Collector Contrib: v0.154.0
- Terraform: 1.15.6
- Terraform AWS provider: 6.50.0
- EKS module: ~> 21.0 (latest 21.23.0)
- VPC module: ~> 6.6 (latest 6.6.1)
- Helm: 4.2.1
- EKS Kubernetes: 1.35
- kubectl client: 1.34.1

## AWS configuration
- Region: us-east-2
- Account: 982920153340
- IAM user: terraform-dev
- LLM: AWS Bedrock (anthropic.claude-3-5-sonnet-20241022-v2:0)
- EKS node type: t3.xlarge (4 vCPU, 16GB)
- Node count: 3

## EKS module v21 argument names (VERIFIED from UPGRADE-21.0.md)
These were renamed from v20 — using old names causes immediate Terraform errors:
  cluster_name              → name
  cluster_version           → kubernetes_version
  cluster_endpoint_public_access → endpoint_public_access
  cluster_addons            → addons

## Critical rules — never violate these
1. Cilium MUST be installed via Helm BEFORE EKS node groups are created
   node_group depends_on null_resource.delete_aws_node depends_on helm_release.cilium
2. aws-node DaemonSet MUST be deleted after Cilium installs, before nodes join
3. Node group MUST have taint node.cilium.io/agent-not-ready=true:NoExecute
4. OTel TracerProvider MUST be configured BEFORE Traceloop.init() is called
5. Beyla DaemonSet MUST have /sys/fs/cgroup volume mount
6. k8sattributes processor MUST have ClusterRole RBAC before Collector deploys
7. Datadog connector (datadog/connector) MUST feed the metrics pipeline (Phase 7)
8. Never mix OTel SDK release cycles — SDK 1.42.1 + contrib 0.63b1 always together
9. Pin traceloop-sdk==0.61.0 — do not float
10. Dynatrace: OTLP ingest endpoint ONLY — no OneAgent (conflicts with Cilium CNI)

## Dependency chain (Terraform)
module.eks → helm_release.cilium → null_resource.delete_aws_node → aws_eks_node_group.main → namespaces

## Phase roadmap
- Phase 1: Foundation — vanilla app + EKS + IaC (COMPLETE — CI green)
- Phase 2: Full MELT + Network — OTel SDK + Beyla + Hubble + Dash0
- Phase 3: Network Blindspot Demo — fault injection, eBPF catches what APM misses
- Phase 4: GenAI Observability — OpenLLMetry + Bedrock
- Phase 5: AIOps Layer — adaptive baselines, predictive alerting
- Phase 6: Multi-Cloud — on-prem k3s + GCP GKE + Azure AKS
- Phase 7: Multi-Backend — Dynatrace + Datadog alongside Dash0
- Phase 8: Public Packaging — README, runbooks, one-click deploy

## Repo structure
otel-observability-lab/
├── CLAUDE.md                  # This file
├── VERSIONS.md                # Pinned versions
├── PREFLIGHT_RISKS.md         # Risk analysis
├── PROJECT_CONTEXT.md         # Full project context
├── README.md                  # Public-facing description
├── renovate.json              # Automated dependency updates
├── .env.example               # All required env vars (no secrets)
├── terraform/eks/             # AWS EKS cluster
├── helm/                      # Helm values files
├── apps/gateway/              # Python FastAPI API gateway
├── apps/product-svc/          # Python FastAPI + PostgreSQL
├── apps/llm-svc/              # Python FastAPI + AWS Bedrock
├── collector/                 # OTel Collector configs
├── rbac/                      # Kubernetes RBAC
├── scripts/                   # Bootstrap and fault injection
└── docs/                      # Architecture diagrams and runbooks

## Common commands
terraform -chdir=terraform/eks init
terraform -chdir=terraform/eks plan
terraform -chdir=terraform/eks apply
aws eks update-kubeconfig --region us-east-2 --name otel-lab
kubectl get nodes
kubectl get pods -A
helm list -A
