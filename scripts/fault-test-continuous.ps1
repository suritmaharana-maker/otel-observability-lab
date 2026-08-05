# ============================================================
# Fault Injection Test: CONTINUOUS - alternates normal/fault segments
# indefinitely until cancelled (Ctrl+C). Each normal segment is a
# random 3-5 min, each fault segment a random 4-5 min. Generates real
# traffic throughout (both states) so there's always something to
# observe. Uses cnp-fault.yaml (CiliumNetworkPolicy, blocks
# gateway->product-svc:8001). Logs precise UTC timestamps at every
# transition for Dash0 PromQL correlation.
#
# SAFETY: on Ctrl+C or any exit, the finally block deletes the fault
# policy so it never gets stuck applied. If PowerShell is killed hard
# (closed window, not Ctrl+C) the finally block may not run - check
# `kubectl get ciliumnetworkpolicy -n otel-lab` afterward as a safety
# net and `kubectl delete -f cnp-fault.yaml` if it's still there.
# ============================================================
$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..")

$ts = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force -Path logs | Out-Null
$logFile = "logs\fault-test-continuous-$ts.log"
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

Write-Host "=== Continuous Fault Injection Test ===" -ForegroundColor Green
Write-Host "Normal: random 3-5 min | Fault: random 4-5 min | runs until Ctrl+C"
Write-Host "Gateway: $elb"
Write-Host "Full log: $logFile`n"

$cycle = 0
try {
    while ($true) {
        $cycle++
        $normalSec = Get-Random -Minimum 180 -Maximum 301
        $faultSec  = Get-Random -Minimum 240 -Maximum 301

        Run-Segment $normalSec "CYCLE $cycle - normal baseline ($([math]::Round($normalSec/60,1)) min)"

        kubectl apply -f cnp-fault.yaml | Out-Null
        Run-Segment $faultSec "CYCLE $cycle - FAULT INJECTED (policy-deny, gateway->product-svc:8001) ($([math]::Round($faultSec/60,1)) min)"

        kubectl delete -f cnp-fault.yaml | Out-Null
    }
}
finally {
    Write-Host "`n=== Stopping - cleaning up fault policy ===" -ForegroundColor Yellow
    kubectl delete -f cnp-fault.yaml --ignore-not-found | Out-Null
    $remaining = kubectl get ciliumnetworkpolicy -n otel-lab --no-headers 2>$null
    if ($remaining) {
        Write-Host "WARNING: policy still present, delete manually: kubectl delete -f cnp-fault.yaml" -ForegroundColor Red
    } else {
        Write-Host "Confirmed: no fault policy active." -ForegroundColor Green
    }
    Log-Transition "TEST STOPPED (completed $cycle full cycles)"
    Write-Host "Full log saved to $logFile" -ForegroundColor Green
    Stop-Transcript | Out-Null
}
