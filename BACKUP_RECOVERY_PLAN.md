# OTel Lab — Backup & Recovery Plan
> **Last updated:** June 17, 2026 — Phase 4 complete

---

## Asset Inventory

| Asset | Location | Criticality | Recovery time |
|---|---|---|---|
| All code + configs | GitHub main branch | 🔴 Critical | Minutes |
| Terraform state | Local + S3 (recommended) | 🔴 Critical | Hours if lost |
| Dash0 auth token | k8s secret + local | 🔴 Critical | Minutes to rotate |
| ECR images | AWS ECR us-east-2 | 🟡 Medium | 15 min to rebuild |
| EC2 instances | AWS | 🟡 Medium | 10 min to restart |
| IMDSv2 hop limit setting | AWS EC2 metadata | 🔴 Critical for Bedrock | 2 min to reapply |
| PostgreSQL data | In-cluster | 🟢 Low | Seconds — seed data |
| Screenshots/evidence | Local Downloads | 🟡 Medium | Cannot regenerate |

---

## Daily Shutdown (run before stopping every session)

```powershell
# 1. Remove any active faults
kubectl delete -f cnp-fault.yaml --ignore-not-found
kubectl exec -n otel-lab netshoot -- bash -c "nsenter --net=/proc/GATEWAY_PID/ns/net -- tc qdisc del dev eth0 root" 2>$null

# 2. Scale down to save cost (~$3/hr saved)
kubectl scale deployment gateway product-svc llm-svc -n otel-lab --replicas=0
kubectl delete pod netshoot -n otel-lab --ignore-not-found

# 3. Commit everything
git add -A
git commit -m "wip: end of session $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
git push origin main

# 4. Stop EC2 instances
aws ec2 stop-instances --region us-east-2 --instance-ids `
  i-0ffab8f7b1ba96746 i-069cb3daa8dbeb5f7 i-026ca1f368d7d3690
Write-Host "Instances stopping. Cost saving active." -ForegroundColor Green
```

---

## Daily Startup

```powershell
# 1. Start instances
aws ec2 start-instances --region us-east-2 --instance-ids `
  i-0ffab8f7b1ba96746 i-069cb3daa8dbeb5f7 i-026ca1f368d7d3690

# 2. Wait for nodes ready (~2 min)
Start-Sleep -Seconds 120

# 3. Run startup automation
.\startup.ps1

# 4. Verify IMDSv2 hop limit (required for Bedrock!)
# Only needed if instances were replaced by ASG
$ids = (aws ec2 describe-instances --region us-east-2 `
  --filters "Name=tag:eks:cluster-name,Values=otel-lab" "Name=instance-state-name,Values=running" `
  --query "Reservations[].Instances[].InstanceId" --output text) -split '\s+'
foreach ($id in $ids) {
    $hop = aws ec2 describe-instance-metadata-options --region us-east-2 --instance-id $id `
      --query "InstanceMetadataOptions.HttpPutResponseHopLimit" --output text
    if ($hop -ne "2") {
        Write-Host "Fixing hop limit on $id" -ForegroundColor Yellow
        aws ec2 modify-instance-metadata-options --region us-east-2 --instance-id $id `
          --http-put-response-hop-limit 2 --http-endpoint enabled
    }
}

# 5. Deploy netshoot and find gateway PID
$gwNode = kubectl get pod -n otel-lab -l app=gateway -o jsonpath='{.items[0].spec.nodeName}'
(Get-Content netshoot-pod.yaml) -replace '  nodeName:.*', "  nodeName: $gwNode" | Set-Content netshoot-pod.yaml
kubectl apply -f netshoot-pod.yaml
kubectl wait --for=condition=Ready pod/netshoot -n otel-lab --timeout=60s
$gwIP = kubectl get pod -n otel-lab -l app=gateway -o jsonpath='{.items[0].status.podIP}'
# Update findgw.sh with new IP then:
kubectl cp findgw.sh otel-lab/netshoot:/tmp/findgw.sh
kubectl exec -n otel-lab netshoot -- bash /tmp/findgw.sh

# 6. Smoke test all endpoints
$elb = "a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com"
.\load-generator.ps1 -DurationSeconds 10 -IntervalMs 500
Invoke-WebRequest -Uri "http://$elb/recommendations?query=test" -UseBasicParsing -TimeoutSec 30
```

---

## Recovery Scenarios

### Scenario A — Fresh clone on new machine
```powershell
git clone https://github.com/suritmaharana-maker/otel-observability-lab
cd otel-observability-lab
aws configure  # set region to us-east-2
aws eks update-kubeconfig --name otel-lab --region us-east-2
kubectl get nodes  # verify access
.\startup.ps1
```

### Scenario B — Pods stuck in Pending after restart
```powershell
# Root cause: nodeSelector pointing to old hostname
kubectl describe pod <pod-name> -n otel-lab | Select-String "hostname|selector"
kubectl get nodes -o wide  # get new hostnames
kubectl patch deployment gateway -n otel-lab -p '{"spec":{"template":{"spec":{"nodeSelector":{"kubernetes.io/hostname":"NEW_NODE_C"}}}}}'
kubectl patch deployment product-svc -n otel-lab -p '{"spec":{"template":{"spec":{"nodeSelector":{"kubernetes.io/hostname":"NEW_NODE_B"}}}}}'
```

### Scenario C — No data in Dash0 after restart
```powershell
# Step 1: Check Beyla DNS
kubectl logs -n otel-lab -l app.kubernetes.io/name=beyla --tail=5 | Select-String "error|dns|failed"
# If DNS errors: kubectl rollout restart daemonset/beyla -n otel-lab

# Step 2: Check otelcol
kubectl logs -n observability -l app=otelcol --tail=5
# If errors: kubectl rollout restart daemonset/otelcol -n observability

# Step 3: Restart apps
kubectl rollout restart deployment/product-svc deployment/llm-svc -n otel-lab
```

### Scenario D — Bedrock "Unable to locate credentials"
```powershell
# Root cause: IMDSv2 hop limit = 1 (Cilium needs 2)
$ids = (aws ec2 describe-instances --region us-east-2 `
  --filters "Name=tag:eks:cluster-name,Values=otel-lab" "Name=instance-state-name,Values=running" `
  --query "Reservations[].Instances[].InstanceId" --output text) -split '\s+'
foreach ($id in $ids) {
    aws ec2 modify-instance-metadata-options --region us-east-2 --instance-id $id `
      --http-put-response-hop-limit 2 --http-endpoint enabled
}
kubectl rollout restart deployment/llm-svc -n otel-lab
```

### Scenario E — ECR push fails (authentication error)
```powershell
# Root cause: Docker Desktop credential helper
# Fix: ensure credHelpers in docker config points to ecr-login
$config = @{
  auths = @{ "ghcr.io" = @{} }
  credHelpers = @{ "982920153340.dkr.ecr.us-east-2.amazonaws.com" = "ecr-login" }
  currentContext = "desktop-linux"
} | ConvertTo-Json -Depth 5
$config | Out-File "$env:USERPROFILE\.docker\config.json" -Encoding ascii
# Then push directly:
docker push "982920153340.dkr.ecr.us-east-2.amazonaws.com/otel-lab/llm-svc:latest"
```

### Scenario F — Fault injection stuck
```powershell
kubectl delete -f cnp-fault.yaml --ignore-not-found
kubectl get ciliumnetworkpolicy -n otel-lab  # should return nothing
kubectl exec -n otel-lab netshoot -- bash -c "nsenter --net=/proc/GATEWAY_PID/ns/net -- tc qdisc del dev eth0 root" 2>$null
# Verify clean
$elb = "a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com"
for ($i=1; $i -le 5; $i++) {
    $r = Invoke-WebRequest -Uri "http://$elb/products" -UseBasicParsing -TimeoutSec 10
    Write-Host "[$i] $($r.StatusCode)"
}
```

### Scenario G — Update gateway/product-svc code
```powershell
# These use ConfigMaps NOT ECR images
# Edit the ConfigMap YAML then:
kubectl apply -f k8s\gateway-configmap.yaml
kubectl rollout restart deployment/gateway -n otel-lab
kubectl exec -n otel-lab deployment/gateway -- grep -c "recommendations" /app/main.py
# Must return > 0
```

### Scenario H — Update llm-svc code
```powershell
# llm-svc uses ECR image
# Edit apps\llm-svc\llm_svc.py then:
Push-Location apps\llm-svc
docker build --no-cache -t "982920153340.dkr.ecr.us-east-2.amazonaws.com/otel-lab/llm-svc:latest" .
Pop-Location
docker push "982920153340.dkr.ecr.us-east-2.amazonaws.com/otel-lab/llm-svc:latest"
kubectl rollout restart deployment/llm-svc -n otel-lab
kubectl rollout status deployment/llm-svc -n otel-lab --timeout=120s
```

---

## Terraform State Backup (one-time setup)

```powershell
# Create versioned S3 bucket for state
aws s3 mb s3://surit-otel-lab-tfstate --region us-east-2
aws s3api put-bucket-versioning --bucket surit-otel-lab-tfstate `
  --versioning-configuration Status=Enabled

# Add to terraform/eks/main.tf:
# terraform {
#   backend "s3" {
#     bucket = "surit-otel-lab-tfstate"
#     key    = "eks/terraform.tfstate"
#     region = "us-east-2"
#   }
# }

terraform -chdir=terraform/eks init -migrate-state
```

---

## Fixed Values (never change between restarts)

| Item | Value |
|---|---|
| ELB | a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com |
| VPC | vpc-00a1138c8d1c4d109 |
| EKS cluster | otel-lab |
| AWS account | 982920153340 |
| ECR registry | 982920153340.dkr.ecr.us-east-2.amazonaws.com |
| Dash0 endpoint | ingress.us-west-2.aws.dash0.com:4317 |
| otelcol service | otelcol.observability.svc.cluster.local:4317 |
| Bedrock model | us.amazon.nova-micro-v1:0 |

## Values that CHANGE on every restart

- EC2 instance IDs (if ASG replaces them)
- Node hostnames (ip-10-0-X-YYY)
- Pod IPs and pod names
- Gateway PID inside netshoot
- Cilium agent pod name
