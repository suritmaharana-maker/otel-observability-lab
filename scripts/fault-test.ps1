# ============================================================
# Fault Injection Test: 3m normal / 4m error / 3m normal / 4m error / 2m normal
# Uses cnp-fault.yaml (CiliumNetworkPolicy, blocks gateway->product-svc:8001)
# Logs precise UTC timestamps at every transition for Dash0 PromQL correlation.
# ============================================================
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$ts = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force -Path logs | Out-Null
$logFile = "logs\fault-test-$ts.log"
Start-Transcript -Path $logFile -Append | Out-Null

function Log-Transition($label) {
    $utc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss") + " UTC"
    Write-Host "[$utc] $label" -ForegroundColor Cyan
}

Write-Host "=== Fault Injection Test ===" -ForegroundColor Green
Write-Host "Sequence: 3m normal -> 4m error -> 3m normal -> 4m error -> 2m normal (16 min total)"
Write-Host "Full log: $logFile`n"

# --- Segment 1: normal (3 min) ---
Log-Transition "SEGMENT 1/5 START: normal baseline (3 min)"
Start-Sleep -Seconds 180

# --- Segment 2: error (4 min) ---
kubectl apply -f cnp-fault.yaml
Log-Transition "SEGMENT 2/5 START: FAULT INJECTED (policy-deny, gateway->product-svc:8001) (4 min)"
Start-Sleep -Seconds 240

# --- Segment 3: normal (3 min) ---
kubectl delete -f cnp-fault.yaml
Log-Transition "SEGMENT 3/5 START: fault cleared, normal (3 min)"
Start-Sleep -Seconds 180

# --- Segment 4: error (4 min) ---
kubectl apply -f cnp-fault.yaml
Log-Transition "SEGMENT 4/5 START: FAULT INJECTED again (4 min)"
Start-Sleep -Seconds 240

# --- Segment 5: normal (2 min) ---
kubectl delete -f cnp-fault.yaml
Log-Transition "SEGMENT 5/5 START: fault cleared, normal (2 min)"
Start-Sleep -Seconds 120

Log-Transition "TEST COMPLETE"
Write-Host "`nFull log saved to $logFile" -ForegroundColor Green
Stop-Transcript | Out-Null
