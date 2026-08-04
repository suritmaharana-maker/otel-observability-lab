# ============================================================
# Fault Injection Test: 3m normal / 4m error / 3m normal / 4m error / 2m normal
# Uses cnp-fault.yaml (CiliumNetworkPolicy, blocks gateway->product-svc:8001)
# Generates continuous traffic throughout (normal AND fault segments) so
# there's actually something to observe - a fault with no traffic produces
# no telemetry at all. Logs precise UTC timestamps at every transition for
# Dash0 PromQL correlation.
# ============================================================
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$ts = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force -Path logs | Out-Null
$logFile = "logs\fault-test-$ts.log"
Start-Transcript -Path $logFile -Append | Out-Null

$elb = kubectl get svc gateway -n otel-lab -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'

function Log-Transition($label) {
    $utc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss") + " UTC"
    Write-Host "[$utc] $label" -ForegroundColor Cyan
}

function Run-Segment($seconds, $label) {
    Log-Transition $label
    $end = (Get-Date).AddSeconds($seconds)
    $ok = 0; $err = 0
    while ((Get-Date) -lt $end) {
        try { Invoke-RestMethod -Uri "http://$elb/products" -TimeoutSec 5 | Out-Null; $ok++ }
        catch { $err++ }
        Start-Sleep -Seconds 3
    }
    $utc = (Get-Date).ToUniversalTime().ToString("HH:mm:ss")
    Write-Host "  [$utc UTC] segment traffic: ok=$ok err=$err" -ForegroundColor DarkGray
}

Write-Host "=== Fault Injection Test ===" -ForegroundColor Green
Write-Host "Sequence: 3m normal -> 4m error -> 3m normal -> 4m error -> 2m normal (16 min total)"
Write-Host "Gateway: $elb"
Write-Host "Full log: $logFile`n"

Run-Segment 180 "SEGMENT 1/5 START: normal baseline (3 min)"

kubectl apply -f cnp-fault.yaml
Run-Segment 240 "SEGMENT 2/5 START: FAULT INJECTED (policy-deny, gateway->product-svc:8001) (4 min)"

kubectl delete -f cnp-fault.yaml
Run-Segment 180 "SEGMENT 3/5 START: fault cleared, normal (3 min)"

kubectl apply -f cnp-fault.yaml
Run-Segment 240 "SEGMENT 4/5 START: FAULT INJECTED again (4 min)"

kubectl delete -f cnp-fault.yaml
Run-Segment 120 "SEGMENT 5/5 START: fault cleared, normal (2 min)"

Log-Transition "TEST COMPLETE"
Write-Host "`nFull log saved to $logFile" -ForegroundColor Green
Stop-Transcript | Out-Null
