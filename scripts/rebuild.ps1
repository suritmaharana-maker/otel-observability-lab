# ============================================================
# OTel Lab - FULL REBUILD (from zero, Dash0-only)
# Recreates everything terraform destroy removed. ~10-15 min.
# Run from anywhere; script resolves repo root itself.
# ============================================================
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$ts = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force -Path logs | Out-Null
$logFile = "logs\rebuild-$ts.log"
Start-Transcript -Path $logFile -Append | Out-Null

Write-Host "=== OTel Lab Rebuild ===" -ForegroundColor Cyan
Write-Host "Full session log: $logFile" -ForegroundColor DarkGray

# --- 1. Terraform apply ---
# Creates VPC, NAT, EKS cluster, nodegroup, IAM, cilium (helm_release in
# state), and namespaces otel-lab/observability. NOT auto-approved.
Write-Host "`n[1/7] terraform apply (you will be asked to confirm)..." -ForegroundColor Yellow
Set-Location terraform\eks
terraform apply
Set-Location (Join-Path $PSScriptRoot "..")

# --- 2. Kubeconfig + wait for nodes ---
Write-Host "`n[2/7] Updating kubeconfig, waiting for nodes Ready..." -ForegroundColor Yellow
aws eks update-kubeconfig --name otel-lab --region us-east-2
kubectl wait --for=condition=Ready node --all --timeout=300s
kubectl wait --for=condition=Ready pod -n kube-system -l k8s-app=cilium --timeout=180s

# --- 3. Postgres ---
Write-Host "`n[3/7] Deploying postgres..." -ForegroundColor Yellow
kubectl apply -f k8s\postgres.yaml
kubectl rollout status statefulset/postgres -n otel-lab --timeout=180s

# --- 4. Secrets + code ConfigMaps ---
# dash0-secret from clean backup; code ConfigMaps rebuilt FROM apps/*.py
# (source of truth as of the 2026-08-03 live/local sync - see CLAUDE_CONTEXT.md)
Write-Host "`n[4/7] Applying dash0-secret and code ConfigMaps..." -ForegroundColor Yellow
kubectl apply -f backup\secrets\dash0-secret.yaml
kubectl get secret dash0-secret -n observability -o json | ForEach-Object { $_ -replace '"namespace": "observability"', '"namespace": "otel-lab"' } | kubectl apply -f -
kubectl create configmap gateway-code -n otel-lab --from-file=main.py=apps\gateway\main.py --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap product-svc-code -n otel-lab --from-file=main.py=apps\product-svc\product_svc.py --dry-run=client -o yaml | kubectl apply -f -

# --- 5. otelcol ---
# otelcol-direct.yaml owns the DaemonSet+ServiceAccount (and a stale
# placeholder ConfigMap). k8s\otelcol-config.yaml is the REAL, current
# Dash0-only config (verified 2026-08-03 to match live) - apply it
# second so it overwrites the placeholder, then restart to pick it up.
Write-Host "`n[5/7] Deploying otelcol..." -ForegroundColor Yellow
kubectl apply -f k8s\otelcol-direct.yaml
kubectl apply -f k8s\otelcol-config.yaml
kubectl rollout restart daemonset/otelcol -n observability
kubectl rollout status daemonset/otelcol -n observability --timeout=120s

# --- 6. OBI (eBPF instrumentation) ---
Write-Host "`n[6/7] Installing OBI via Helm..." -ForegroundColor Yellow
helm upgrade --install obi open-telemetry/opentelemetry-ebpf-instrumentation -n observability -f k8s\obi-values.yaml --version 0.10.0
kubectl rollout status daemonset/obi-opentelemetry-ebpf-instrumentation -n observability --timeout=120s

# --- 7. App workloads + verification ---
# NOTE: no nodeSelector patching needed - gateway/product-svc use
# podAntiAffinity/podAffinity against 'app=postgres' (kubernetes.io/hostname
# topology key), which schedules them correctly regardless of new hostnames.
Write-Host "`n[7/7] Deploying postgres-dependent app services..." -ForegroundColor Yellow
kubectl apply -f k8s\product-svc.yaml
kubectl apply -f k8s\gateway.yaml
kubectl apply -f k8s\llm-svc.yaml
kubectl rollout status deployment/product-svc -n otel-lab --timeout=120s
kubectl rollout status deployment/gateway -n otel-lab --timeout=120s
kubectl rollout status deployment/llm-svc -n otel-lab --timeout=120s

Write-Host "`n=== Verifying topology (gateway and product-svc must be on DIFFERENT nodes) ===" -ForegroundColor Cyan
kubectl get pods -n otel-lab -o wide

Write-Host "`n=== Waiting for ELB DNS to propagate (60s) ===" -ForegroundColor Cyan
Start-Sleep -Seconds 60
$elb = kubectl get svc gateway -n otel-lab -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
Write-Host "Gateway ELB: $elb"
try {
    $r = Invoke-WebRequest -Uri "http://$elb/products" -UseBasicParsing -TimeoutSec 15
    Write-Host "Sanity check: $($r.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "Sanity check failed (DNS may need more time) - retry manually: curl http://$elb/products" -ForegroundColor DarkYellow
}
Write-Host "`n=== Rebuild complete ===" -ForegroundColor Cyan
Write-Host "Full log saved to $logFile" -ForegroundColor DarkGray
Stop-Transcript | Out-Null
