# OTel Lab - Full build and deploy all three services
# Run from repo root: .\build-and-deploy-all.ps1

param(
    [switch]$GatewayOnly,
    [switch]$LlmOnly
)

$ACCOUNT  = "982920153340"
$REGION   = "us-east-2"
$REGISTRY = "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
$ELB      = "a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com"

function Build-Push-Deploy {
    param($Service, $AppDir, $K8sFile)
    Write-Host ""
    Write-Host "=== $Service ===" -ForegroundColor Cyan
    $repo = "$REGISTRY/otel-lab/$Service"

    aws ecr create-repository --repository-name "otel-lab/$Service" --region $REGION 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ECR repo created" -ForegroundColor Gray
    } else {
        Write-Host "  ECR repo already exists" -ForegroundColor Gray
    }

    Write-Host "  Building image..." -ForegroundColor Yellow
    Push-Location $AppDir
    docker build -t "otel-lab/${Service}:latest" .
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  BUILD FAILED" -ForegroundColor Red
        Pop-Location
        return
    }
    docker tag "otel-lab/${Service}:latest" "${repo}:latest"
    Pop-Location

    Write-Host "  Pushing to ECR..." -ForegroundColor Yellow
    docker push "${repo}:latest"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  PUSH FAILED" -ForegroundColor Red
        return
    }

    Write-Host "  Deploying to EKS..." -ForegroundColor Yellow
    kubectl apply -f $K8sFile
    kubectl rollout restart deployment/$Service -n otel-lab 2>$null
    kubectl rollout status deployment/$Service -n otel-lab --timeout=120s
    Write-Host "  $Service deployed successfully" -ForegroundColor Green
}

Write-Host "=== ECR login ===" -ForegroundColor Cyan
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin "$REGISTRY"

if ($LlmOnly) {
    Build-Push-Deploy "llm-svc" "apps/llm-svc" "k8s/llm-svc.yaml"
    Build-Push-Deploy "gateway" "apps/gateway" "k8s/gateway.yaml"
} elseif ($GatewayOnly) {
    Build-Push-Deploy "gateway" "apps/gateway" "k8s/gateway.yaml"
} else {
    Build-Push-Deploy "product-svc" "apps/product-svc" "k8s/product-svc.yaml"
    Build-Push-Deploy "llm-svc"     "apps/llm-svc"     "k8s/llm-svc.yaml"
    Build-Push-Deploy "gateway"     "apps/gateway"      "k8s/gateway.yaml"
}

Write-Host ""
Write-Host "=== Pod state ===" -ForegroundColor Cyan
kubectl get pods -n otel-lab -o wide

Write-Host ""
Write-Host "=== Smoke tests ===" -ForegroundColor Cyan
Start-Sleep -Seconds 5

Write-Host "Testing /products..." -ForegroundColor Yellow
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$r = Invoke-WebRequest -Uri "http://$ELB/products" -UseBasicParsing -TimeoutSec 15
$sw.Stop()
$products = $r.Content | ConvertFrom-Json
Write-Host "/products: $($r.StatusCode) $($sw.ElapsedMilliseconds)ms - $($products.Count) products" -ForegroundColor Green

Write-Host ""
Write-Host "Testing /recommendations (Bedrock call, may take 2-3s)..." -ForegroundColor Yellow
$sw2 = [System.Diagnostics.Stopwatch]::StartNew()
try {
    $r2 = Invoke-WebRequest -Uri "http://$ELB/recommendations?query=best+product+for+developers" -UseBasicParsing -TimeoutSec 30
    $sw2.Stop()
    $rec = $r2.Content | ConvertFrom-Json
    Write-Host "/recommendations: $($r2.StatusCode) $($sw2.ElapsedMilliseconds)ms" -ForegroundColor Green
    Write-Host "  Model:          $($rec.model)"         -ForegroundColor Cyan
    Write-Host "  Temperature:    $($rec.temperature)"   -ForegroundColor Cyan
    Write-Host "  Input tokens:   $($rec.tokens.input)"  -ForegroundColor Cyan
    Write-Host "  Output tokens:  $($rec.tokens.output)" -ForegroundColor Cyan
    Write-Host "  Cost USD:       $($rec.cost_usd)"      -ForegroundColor Cyan
    Write-Host "  LLM latency:    $($rec.llm_latency_ms)ms" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Recommendation:" -ForegroundColor Yellow
    Write-Host "  $($rec.recommendation)" -ForegroundColor White
} catch {
    $sw2.Stop()
    Write-Host "/recommendations: ERROR after $($sw2.ElapsedMilliseconds)ms" -ForegroundColor Red
    Write-Host "  $_" -ForegroundColor Red
    Write-Host "  Check logs: kubectl logs -n otel-lab deployment/llm-svc --tail=30"
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Cyan
Write-Host "Check Dash0 Tracing for spans with gen_ai.* attributes" -ForegroundColor Green
