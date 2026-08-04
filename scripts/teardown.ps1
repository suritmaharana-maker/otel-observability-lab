# ============================================================
# OTel Lab - FULL TEARDOWN (terraform destroy lifecycle)
# Brings AWS spend to ~$0. Rebuild via scripts\rebuild.ps1
# Run from anywhere; script resolves repo root itself.
# ============================================================
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$ts = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force -Path logs | Out-Null
$logFile = "logs\teardown-$ts.log"
Start-Transcript -Path $logFile -Append | Out-Null

Write-Host "=== OTel Lab Teardown ===" -ForegroundColor Cyan
Write-Host "Full session log: $logFile" -ForegroundColor DarkGray

# --- 1. Backup terraform state (belt + suspenders vs corrupt/lost state) ---
Write-Host "`n[1/5] Backing up terraform state..." -ForegroundColor Yellow
$stateDir = "terraform\eks\state-backups"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
Copy-Item terraform\eks\terraform.tfstate "$stateDir\terraform.tfstate.$ts.bak" -ErrorAction SilentlyContinue
Copy-Item terraform\eks\terraform.tfstate.backup "$stateDir\terraform.tfstate.backup.$ts.bak" -ErrorAction SilentlyContinue
Write-Host "  Saved to $stateDir"

# --- 2. Backup live ConfigMaps (code + otelcol config) in case they drifted ---
# since the last rebuild - these live objects vanish with the cluster.
Write-Host "`n[2/5] Backing up live ConfigMaps..." -ForegroundColor Yellow
$cmDir = "backup\live-configmaps-$ts"
New-Item -ItemType Directory -Force -Path $cmDir | Out-Null
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
try {
    $psc = kubectl get configmap product-svc-code -n otel-lab -o jsonpath='{.data.main\.py}' 2>$null
    if ($psc) { [System.IO.File]::WriteAllText("$PWD\$cmDir\product-svc-code.py", $psc, $utf8NoBom) }
    $gwc = kubectl get configmap gateway-code -n otel-lab -o jsonpath='{.data.main\.py}' 2>$null
    if ($gwc) { [System.IO.File]::WriteAllText("$PWD\$cmDir\gateway-code.py", $gwc, $utf8NoBom) }
    $otc = kubectl get configmap otelcol-config -n observability -o jsonpath='{.data.config\.yaml}' 2>$null
    if ($otc) { [System.IO.File]::WriteAllText("$PWD\$cmDir\otelcol-config.yaml", $otc, $utf8NoBom) }
    Write-Host "  Saved to $cmDir (skip if cluster unreachable - nodes may already be down)"
} catch {
    Write-Host "  Cluster unreachable, skipping live backup (state already in backup/live-configmaps-* from prior runs)" -ForegroundColor DarkYellow
}

# --- 3. Release the Classic ELB via its owning k8s Service ---
# MUST happen before terraform destroy - the ELB is not Terraform-managed
# (created by the AWS cloud controller for the 'gateway' Service), so if
# the VPC/subnets get destroyed while it still exists, destroy can fail
# or leave it orphaned and billing forever.
Write-Host "`n[3/5] Releasing LoadBalancer Service (deprovisions the ELB)..." -ForegroundColor Yellow
kubectl delete svc gateway -n otel-lab --ignore-not-found --timeout=90s
Write-Host "  Waiting 30s for AWS to finish deprovisioning..." -ForegroundColor DarkGray
Start-Sleep -Seconds 30
$remaining = aws elb describe-load-balancers --region us-east-2 --query "LoadBalancerDescriptions[].LoadBalancerName" --output text 2>$null
if ($remaining) {
    Write-Host "  WARNING: ELB(s) still present: $remaining - waiting 30s more" -ForegroundColor Red
    Start-Sleep -Seconds 30
}

# --- 4. Terraform destroy ---
# NOT auto-approved on purpose - terraform's own interactive "yes" prompt
# is the last safety gate before deleting real infrastructure.
Write-Host "`n[4/5] Running terraform destroy (you will be asked to confirm)..." -ForegroundColor Yellow
Set-Location terraform\eks
terraform destroy
Set-Location (Join-Path $PSScriptRoot "..")

# --- 5. Post-destroy billing sweep ---
Write-Host "`n[5/5] Verifying no billable resources remain..." -ForegroundColor Yellow
Write-Host "NAT Gateways:"
aws ec2 describe-nat-gateways --region us-east-2 --filter "Name=state,Values=available,pending" --query "NatGateways[].NatGatewayId" --output text
Write-Host "Classic ELBs:"
aws elb describe-load-balancers --region us-east-2 --query "LoadBalancerDescriptions[].LoadBalancerName" --output text
Write-Host "Running EC2:"
aws ec2 describe-instances --region us-east-2 --filters "Name=instance-state-name,Values=running,pending" --query "Reservations[].Instances[].InstanceId" --output text
Write-Host "EKS clusters:"
aws eks list-clusters --region us-east-2 --query "clusters" --output text
Write-Host "`nIf all sections above are empty, spend is back to ~`$0 (ECR image storage is the only residual, a few cents/mo)." -ForegroundColor Green
Write-Host "=== Teardown complete ===" -ForegroundColor Cyan
Write-Host "Full log saved to $logFile" -ForegroundColor DarkGray
Stop-Transcript | Out-Null
