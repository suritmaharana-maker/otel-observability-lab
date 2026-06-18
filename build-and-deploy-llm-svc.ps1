# Phase 4 — Build and deploy llm-svc
# Run from repo root: .\build-and-deploy-llm-svc.ps1

$ACCOUNT_ID = "982920153340"
$REGION = "us-east-2"
$REPO = "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/otel-lab/llm-svc"

Write-Host "=== Phase 4: llm-svc build and deploy ===" -ForegroundColor Cyan

# Step 1 - Create ECR repo
Write-Host "Creating ECR repository..." -ForegroundColor Yellow
aws ecr create-repository --repository-name otel-lab/llm-svc --region $REGION 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "Repo already exists - continuing" -ForegroundColor Gray }

# Step 2 - Docker login to ECR
Write-Host "Logging in to ECR..." -ForegroundColor Yellow
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

# Step 3 - Build image from apps/llm-svc directory
Write-Host "Building Docker image..." -ForegroundColor Yellow
Set-Location apps/llm-svc
docker build -t otel-lab/llm-svc:latest .
docker tag otel-lab/llm-svc:latest "${REPO}:latest"

# Step 4 - Push
Write-Host "Pushing to ECR..." -ForegroundColor Yellow
docker push "${REPO}:latest"
Set-Location ../..

# Step 5 - Deploy to EKS
Write-Host "Deploying to EKS..." -ForegroundColor Yellow
kubectl apply -f k8s/llm-svc.yaml
kubectl rollout status deployment/llm-svc -n otel-lab --timeout=120s

# Step 6 - Update gateway with new image
Write-Host "Updating gateway..." -ForegroundColor Yellow
$GW_REPO = "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/otel-lab/gateway"
Set-Location apps/gateway
docker build -t otel-lab/gateway:latest .
docker tag otel-lab/gateway:latest "${GW_REPO}:latest"
docker push "${GW_REPO}:latest"
Set-Location ../..
kubectl rollout restart deployment/gateway -n otel-lab
kubectl rollout status deployment/gateway -n otel-lab --timeout=90s

# Step 7 - Verify all pods
Write-Host "`n=== Pod state ===" -ForegroundColor Cyan
kubectl get pods -n otel-lab -o wide

# Step 8 - Sanity check
Write-Host "`n=== Testing /recommendations ===" -ForegroundColor Cyan
$elb = "a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com"
Start-Sleep -Seconds 5
$result = Invoke-WebRequest -Uri "http://$elb/recommendations?query=best+product+for+developers" -UseBasicParsing -TimeoutSec 30
Write-Host "Status: $($result.StatusCode)"
$body = $result.Content | ConvertFrom-Json
Write-Host "Model:         $($body.model)"
Write-Host "Temperature:   $($body.temperature)"
Write-Host "Input tokens:  $($body.tokens.input)"
Write-Host "Output tokens: $($body.tokens.output)"
Write-Host "Cost USD:      $($body.cost_usd)"
Write-Host "LLM latency:   $($body.llm_latency_ms)ms"
Write-Host "`nRecommendation:"
Write-Host $body.recommendation -ForegroundColor Green
