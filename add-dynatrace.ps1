# Phase 6 — Add Dynatrace as second OTel backend
# Run from repo root after rotating your Dynatrace token

param(
    [Parameter(Mandatory=$true)]
    [string]$DtToken
)

$DT_ENV_ID = "yta61562"

Write-Host "=== Step 1: Create Dynatrace secret ===" -ForegroundColor Cyan
kubectl create secret generic dynatrace-secret `
  -n observability `
  --from-literal=api-token=$DtToken `
  --from-literal=environment-id=$DT_ENV_ID `
  --dry-run=client -o yaml | kubectl apply -f -

kubectl get secret dynatrace-secret -n observability
Write-Host "Secret created" -ForegroundColor Green

Write-Host ""
Write-Host "=== Step 2: Patch otelcol DaemonSet to add DT env vars ===" -ForegroundColor Cyan
$patch = @'
{
  "spec": {
    "template": {
      "spec": {
        "containers": [{
          "name": "otelcol",
          "env": [
            {
              "name": "DASH0_AUTH_TOKEN",
              "valueFrom": {"secretKeyRef": {"name": "dash0-secret", "key": "auth-token"}}
            },
            {
              "name": "DT_API_TOKEN",
              "valueFrom": {"secretKeyRef": {"name": "dynatrace-secret", "key": "api-token"}}
            },
            {
              "name": "DT_ENVIRONMENT_ID",
              "valueFrom": {"secretKeyRef": {"name": "dynatrace-secret", "key": "environment-id"}}
            },
            {
              "name": "MY_POD_IP",
              "valueFrom": {"fieldRef": {"fieldPath": "status.podIP"}}
            }
          ]
        }]
      }
    }
  }
}
'@

kubectl patch daemonset otelcol -n observability -p $patch
Write-Host "DaemonSet patched" -ForegroundColor Green

Write-Host ""
Write-Host "=== Step 3: Apply updated Collector config (dual export) ===" -ForegroundColor Cyan
kubectl apply -f k8s\otelcol-dynatrace.yaml

Write-Host ""
Write-Host "=== Step 4: Rollout restart ===" -ForegroundColor Cyan
kubectl rollout restart daemonset/otelcol -n observability
kubectl rollout status daemonset/otelcol -n observability --timeout=120s

Write-Host ""
Write-Host "=== Step 5: Verify Collectors are running ===" -ForegroundColor Cyan
kubectl get pods -n observability -o wide
Write-Host ""
Write-Host "Check logs for export errors:" -ForegroundColor Yellow
kubectl logs -n observability -l app=otelcol --tail=15
