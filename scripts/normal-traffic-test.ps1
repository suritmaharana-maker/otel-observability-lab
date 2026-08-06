# ============================================================
# Normal Traffic Test: 5 minutes of real requests, no fault injected.
# Generates real telemetry (traces/logs/metrics) to verify the full
# pipeline end-to-end, including previously-unconfirmed obi_* metrics.
# ============================================================
$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..")

$ts = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force -Path logs | Out-Null
$logFile = "logs\normal-traffic-$ts.log"
Start-Transcript -Path $logFile -Append | Out-Null

$elb = kubectl get svc gateway -n otel-lab -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
Write-Host "=== Normal Traffic Test (5 min) ===" -ForegroundColor Green
Write-Host "Gateway: $elb"
Write-Host "Start (UTC): $((Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss'))"

$endTime = (Get-Date).AddMinutes(5)
$counters = @{ products = 0; health = 0; recommendations = 0; diagnose = 0; errors = 0 }
$i = 0

while ((Get-Date) -lt $endTime) {
    $i++
    try { Invoke-RestMethod -Uri "http://$elb/health" -TimeoutSec 5 | Out-Null; $counters.health++ } catch { $counters.errors++ }
    try { Invoke-RestMethod -Uri "http://$elb/products" -TimeoutSec 5 | Out-Null; $counters.products++ } catch { $counters.errors++ }

    if ($i % 3 -eq 0) {
        try { Invoke-RestMethod -Uri "http://$elb/recommendations" -TimeoutSec 15 | Out-Null; $counters.recommendations++ } catch { $counters.errors++ }
    }
    if ($i % 6 -eq 0) {
        try { Invoke-RestMethod -Uri "http://$elb/diagnose?window=2m" -TimeoutSec 15 | Out-Null; $counters.diagnose++ } catch { $counters.errors++ }
    }

    $remaining = [math]::Round(($endTime - (Get-Date)).TotalSeconds)
    Write-Host "[$((Get-Date).ToUniversalTime().ToString('HH:mm:ss')) UTC] iter=$i remaining=${remaining}s | health=$($counters.health) products=$($counters.products) recs=$($counters.recommendations) diag=$($counters.diagnose) errors=$($counters.errors)"
    Start-Sleep -Seconds 10
}

Write-Host "`n=== Test complete ===" -ForegroundColor Green
Write-Host "End (UTC): $((Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss'))"
Write-Host "Totals: $($counters | ConvertTo-Json -Compress)"
Write-Host "Full log saved to $logFile" -ForegroundColor DarkGray
Stop-Transcript | Out-Null
