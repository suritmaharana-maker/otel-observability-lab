# OTel Observability Lab — Backup & Recovery Plan

> **Last updated:** June 16, 2026
> **Purpose:** Complete backup strategy and recovery procedures for all lab assets.

---

## What Needs to Be Backed Up

| Asset | Location | Criticality | Recovery time if lost |
|---|---|---|---|
| All code + configs | GitHub | 🔴 Critical | Minutes — re-clone |
| Terraform state | Local only | 🔴 Critical | Hours — must rebuild infra |
| Dash0 auth token | Local env only | 🔴 Critical | Minutes — regenerate in Dash0 |
| EKS cluster | AWS | 🟡 Medium | 30–45 min — re-run startup.ps1 |
| EC2 instances | AWS | 🟡 Medium | 10 min — restart |
| PostgreSQL data | In-cluster | 🟢 Low | Seconds — seed data only |
| Screenshots / evidence | Local Downloads | 🟡 Medium | Cannot regenerate |

---

## Tier 1 — GitHub (primary backup)

GitHub is the source of truth for all code, configs, and runbooks.

### What is committed
```
otel-observability-lab/
├── MASTER_PROJECT_CONTEXT.md     ← full project memory
├── VERSIONS.md                   ← pinned component versions
├── RUNBOOK_shutdown_startup.md   ← ops runbook
├── PHASE3_NEXT_SESSION_PLAN.md   ← phase plan + LinkedIn draft
├── BACKUP_RECOVERY_PLAN.md       ← this file
├── startup.ps1                   ← one-command startup
├── load-generator.ps1            ← timestamped traffic generator
├── findgw.sh                     ← find gateway PID
├── cnp-fault.yaml                ← CiliumNetworkPolicy fault injection
├── netshoot-pod.yaml             ← privileged debug pod
├── inject.sh / inject_netshoot.sh ← netem fault scripts
├── helm/beyla-values.yaml        ← Beyla 3.20.0 config
└── terraform/                    ← EKS + VPC infrastructure
```

### What is NOT committed (and where it lives)
| Item | Where | Action needed |
|---|---|---|
| Terraform state (terraform.tfstate) | Local: C:\Users\surit\Documents\otel-observability-lab\terraform\eks\ | Back up to S3 (see below) |
| Dash0 auth token | Local .env or PowerShell profile | Regenerate from Dash0 console |
| kubectl credentials | ~/.kube/config | Re-run aws eks update-kubeconfig |

### Commit everything now
```powershell
cd C:\Users\surit\Documents\otel-observability-lab
git add -A
git status
git commit -m "backup: complete phase 3 state — all docs, scripts, diagrams"
git push origin main
```

---

## Tier 2 — Terraform State Backup

Terraform state tracks exactly what AWS resources exist. If it's lost, Terraform thinks nothing was created and will either fail or create duplicates.

### Option A — S3 backend (recommended for ongoing use)
Add to `terraform/eks/main.tf`:
```hcl
terraform {
  backend "s3" {
    bucket = "surit-otel-lab-tfstate"
    key    = "eks/terraform.tfstate"
    region = "us-east-2"
  }
}
```

Create the bucket first:
```powershell
aws s3 mb s3://surit-otel-lab-tfstate --region us-east-2
aws s3api put-bucket-versioning --bucket surit-otel-lab-tfstate --versioning-configuration Status=Enabled
```

Then migrate:
```powershell
terraform -chdir=terraform/eks init -migrate-state
```

### Option B — Manual backup before shutdown (minimum viable)
```powershell
# Run this before every EC2 stop
$date = Get-Date -Format "yyyyMMdd-HHmm"
Copy-Item terraform\eks\terraform.tfstate "C:\Users\surit\OneDrive\otel-lab-backups\tfstate-$date.json"
Write-Host "State backed up: tfstate-$date.json"
```

---

## Tier 3 — Dash0 Token Rotation

The Dash0 auth token was exposed in an earlier session and must be rotated.

### Steps to rotate
1. Log in to Dash0 → Settings → Access Tokens
2. Revoke the old token
3. Create new token: `otel-lab-collector`
4. Update the Kubernetes secret:

```powershell
kubectl create secret generic dash0-secret \
  -n observability \
  --from-literal=token=NEW_TOKEN_HERE \
  --dry-run=client -o yaml | kubectl apply -f -
```

5. Restart otelcol to pick up new token:
```powershell
kubectl rollout restart daemonset/otelcol -n observability
```

6. Verify export is working:
```powershell
kubectl logs -n observability -l app=otelcol --tail=5
# Should show: Traces {...} spans: N
```

---

## Tier 4 — Screenshots and Evidence

Phase 3 smoking gun screenshots should be committed to the repo under `docs/evidence/`.

### What to save
- `phase3-hubble-drop-total-policy-deny.png` — TCP POLICY_DENY hump in Dash0
- `phase3-tracing-90-errors.png` — 90 errors 38.3% in tracing view
- `phase3-logging-60-errors.png` — 60 error/fatal log records
- `phase3-fault-trace-5016ms.png` — single fault trace waterfall
- `phase3-baseline-trace-66ms.png` — baseline trace with SQL span

### Commit them
```powershell
mkdir docs\evidence -ErrorAction SilentlyContinue
# Copy screenshots from Downloads
Copy-Item "C:\Users\surit\Downloads\phase3-*.png" docs\evidence\
git add docs\evidence\
git commit -m "phase3: smoking gun evidence screenshots"
git push origin main
```

---

## Recovery Procedures

### Scenario A — New laptop / fresh clone
```powershell
# 1. Install tools
# kubectl, helm, terraform, aws cli, git — see VERSIONS.md

# 2. Clone repo
git clone https://github.com/suritmaharana-maker/otel-observability-lab
cd otel-observability-lab

# 3. Configure AWS credentials
aws configure

# 4. Restore kubectl access
aws eks update-kubeconfig --name otel-lab --region us-east-2

# 5. Verify cluster access
kubectl get nodes
kubectl get pods -A

# 6. Run startup sequence
.\startup.ps1
```

### Scenario B — Terraform state lost (cluster still running)
```powershell
# Import existing resources back into state
terraform -chdir=terraform/eks init

# Import the EKS cluster
terraform -chdir=terraform/eks import module.eks.aws_eks_cluster.this otel-lab

# Import the node group
terraform -chdir=terraform/eks import aws_eks_node_group.main otel-lab:otel-lab-main

# Import the VPC (get VPC ID from AWS console)
terraform -chdir=terraform/eks import module.vpc.aws_vpc.this vpc-00a1138c8d1c4d109

# Then plan to verify state matches reality
terraform -chdir=terraform/eks plan
# Should show: No changes
```

### Scenario C — EKS cluster accidentally destroyed
```powershell
# Full rebuild from scratch — 30-45 minutes

# 1. Apply in stages (NEVER all at once)
terraform -chdir=terraform/eks apply -target="module.vpc"
terraform -chdir=terraform/eks apply -target="module.eks"
terraform -chdir=terraform/eks apply -target="null_resource.patch_aws_node" -target="helm_release.cilium"
terraform -chdir=terraform/eks apply -target="aws_eks_node_group.main"
terraform -chdir=terraform/eks apply -target="aws_eks_addon.coredns" -target="aws_eks_addon.kube_proxy"
terraform -chdir=terraform/eks apply

# 2. Restore kubeconfig
aws eks update-kubeconfig --name otel-lab --region us-east-2

# 3. Deploy observability stack
kubectl apply -f k8s/otelcol-direct.yaml
helm upgrade --install beyla grafana/beyla -f helm/beyla-values.yaml -n otel-lab

# 4. Deploy app
kubectl apply -f k8s/gateway.yaml
kubectl apply -f k8s/product-svc.yaml
kubectl apply -f k8s/postgres.yaml

# 5. Run startup.ps1
.\startup.ps1
```

### Scenario D — Pod won't start after restart (Pending state)
```powershell
# Check nodeSelector — most common cause after restart
kubectl describe pod <pod-name> -n otel-lab | Select-String "node|selector|affinity"

# Get new node names
kubectl get nodes -o wide

# Re-pin with new hostname
kubectl patch deployment gateway -n otel-lab -p '{\"spec\":{\"template\":{\"spec\":{\"nodeSelector\":{\"kubernetes.io/hostname\":\"NEW_NODE_C\"}}}}}'
kubectl patch deployment product-svc -n otel-lab -p '{\"spec\":{\"template\":{\"spec\":{\"nodeSelector\":{\"kubernetes.io/hostname\":\"NEW_NODE_B\"}}}}}'
```

### Scenario E — No data in Dash0 after restart
```powershell
# 1. Check Beyla DNS (most common cause)
kubectl logs -n otel-lab -l app.kubernetes.io/name=beyla --tail=10 | Select-String "error|dns|failed"
# If DNS errors: kubectl rollout restart daemonset/beyla -n otel-lab

# 2. Check otelcol is exporting
kubectl logs -n observability -l app=otelcol --tail=10
# If connection reset: kubectl rollout restart daemonset/otelcol -n observability

# 3. Restart product-svc to fix OTel connection
kubectl rollout restart deployment/product-svc -n otel-lab

# 4. Send test traffic
$elb = "a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com"
Invoke-WebRequest -Uri "http://$elb/products" -UseBasicParsing
```

### Scenario F — Fault injection stuck (policy still active)
```powershell
# Remove CiliumNetworkPolicy
kubectl delete -f cnp-fault.yaml --ignore-not-found
kubectl get ciliumnetworkpolicy -n otel-lab
# Should return: No resources found

# Remove netem if active
kubectl exec -n otel-lab netshoot -- bash -c "nsenter --net=/proc/GATEWAY_PID/ns/net -- tc qdisc del dev eth0 root" 2>$null

# Verify traffic is clean
$elb = "a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com"
for ($i=1; $i -le 5; $i++) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $r = Invoke-WebRequest -Uri "http://$elb/products" -UseBasicParsing -TimeoutSec 10
    $sw.Stop()
    Write-Host "[$i] $($r.StatusCode) - $($sw.ElapsedMilliseconds)ms"
}
# All should be 200, under 200ms
```

---

## Daily Habits

### Before stopping for the day
```powershell
# 1. Remove any active faults
kubectl delete -f cnp-fault.yaml --ignore-not-found

# 2. Scale down to save cost
kubectl scale deployment gateway -n otel-lab --replicas=0
kubectl scale deployment product-svc -n otel-lab --replicas=0
kubectl delete pod netshoot -n otel-lab --ignore-not-found

# 3. Commit any changes
git add -A
git commit -m "wip: end of session $(Get-Date -Format 'yyyy-MM-dd')"
git push origin main

# 4. Stop instances
aws ec2 stop-instances --region us-east-2 --instance-ids `
  i-0e94796ce751202a9 `
  i-09d84dc38796ba523 `
  i-0d66e999774a4e2b6
Write-Host "Instances stopped. Cost saving active."
```

### Before starting a session
```powershell
# 1. Start instances
aws ec2 start-instances --region us-east-2 --instance-ids `
  i-0e94796ce751202a9 `
  i-09d84dc38796ba523 `
  i-0d66e999774a4e2b6

# 2. Wait 2 minutes then run startup
Start-Sleep -Seconds 120
.\startup.ps1
```

---

## Fixed Values (never change between restarts)

| Item | Value |
|---|---|
| ELB | a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com |
| VPC | vpc-00a1138c8d1c4d109 |
| EKS endpoint | 99B389CBB5B02A44A96D570AA7358F4E.gr7.us-east-2.eks.amazonaws.com |
| Instance A | i-0e94796ce751202a9 (us-east-2a) |
| Instance B | i-09d84dc38796ba523 (us-east-2b) |
| Instance C | i-0d66e999774a4e2b6 (us-east-2c) |
| Dash0 endpoint | ingress.us-west-2.aws.dash0.com:4317 |
| GitHub repo | https://github.com/suritmaharana-maker/otel-observability-lab |

## Values that CHANGE on every restart

- Node hostnames (ip-10-0-X-YYY)
- Pod IPs
- Pod names (random suffix)
- Gateway PID inside netshoot
- Cilium agent pod name

