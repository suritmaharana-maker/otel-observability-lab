# OTel Observability Lab — Claude Code Context

## Project owner
Surit Maharana — Principal Network Observability Engineer
GitHub: suritm7543
Repo: https://github.com/suritm7543/otel-observability-lab

## What this project is
A fully public, production-grade lab demonstrating:
- Network observability (eBPF — Cilium/Hubble + Grafana Beyla)
- APM / distributed tracing (OpenTelemetry SDK)
- LLM / GenAI observability (OpenLLMetry / traceloop-sdk)

All married into ONE unified OTel Collector pipeline across AWS EKS, on-prem k3s, GCP GKE, and Azure AKS.

Core thesis: "App observability tells you something is broken. Network observability tells you why."

## Current phase
Phase 1 — Foundation. Vanilla 3-service app on AWS EKS. No instrumentation yet.

## Architecture
Three Python FastAPI services:
- gateway (port 8000) — API gateway, routes to product-svc and llm-svc
- product-svc (port 8001) — product catalog + PostgreSQL
- llm-svc (port 8002) — calls AWS Bedrock (Claude) for AI features

## Pinned versions — DO NOT change without checking VERSIONS.md
- Python: 3.13.14
- opentelemetry-sdk: 1.42.1
- opentelemetry-instrumentation-fastapi: 0.55b1
- traceloop-sdk: 0.61.0
- Cilium CNI: 1.19.4
- Grafana Beyla: 3.12.x
- OTel Collector Contrib: v0.154.0
- Terraform: 1.15.6
- Terraform AWS provider: 6.50.0
- Helm: 4.2.1
- EKS Kubernetes: 1.35
- Node.js: 24.16.0 LTS

## AWS configuration
- Region: us-east-2
- LLM: AWS Bedrock (Claude model)
- EKS node type: t3.xlarge (4 vCPU, 16GB — minimum for Cilium + Beyla + OTel Collector)

## Critical rules — never violate these
1. Cilium MUST be installed via Helm BEFORE EKS node groups are created
   - node_group depends_on helm_release.cilium in Terraform
   - VPC CNI addon MUST be disabled at cluster creation
2. OTel TracerProvider MUST be configured BEFORE Traceloop.init() is called
3. Beyla DaemonSet MUST have /sys/fs/cgroup volume mount
4. k8sattributes processor MUST have ClusterRole RBAC applied before Collector deploys
5. Datadog connector (datadog/connector) MUST feed the metrics pipeline (Phase 7)
6. Never mix OTel SDK release cycles (1.42.1 SDK + 0.55b1 contrib — always together)
7. Pin traceloop-sdk==0.61.0 — do not float
8. Dynatrace: OTLP ingest endpoint ONLY — no OneAgent (conflicts with Cilium CNI)

## Phase roadmap
- Phase 1: Foundation — vanilla app + EKS + IaC (CURRENT)
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
├── terraform/gke/             # Phase 6
├── terraform/aks/             # Phase 6
├── terraform/k3s-onprem/      # Phase 6
├── helm/                      # Helm values files
├── apps/gateway/              # Python FastAPI API gateway
├── apps/product-svc/          # Python FastAPI + PostgreSQL
├── apps/llm-svc/              # Python FastAPI + AWS Bedrock
├── collector/                 # OTel Collector configs
├── rbac/                      # Kubernetes RBAC
├── scripts/                   # Bootstrap and fault injection
└── docs/                      # Architecture diagrams and runbooks

## Commands you will commonly run in this project
terraform -chdir=terraform/eks init
terraform -chdir=terraform/eks plan
terraform -chdir=terraform/eks apply
aws eks update-kubeconfig --region us-east-2 --name otel-lab
kubectl get nodes
helm list -A
helm template --dry-run
kubectl get pods -A
