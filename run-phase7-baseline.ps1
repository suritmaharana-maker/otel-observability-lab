# ============================================================
# Phase 7 Baseline Replication Test
# Replicates the exact 20-minute structured fault-injection test
# from CLAUDE_CONTEXT.md / Full_OTEL_network_metrics.pdf
#
# Timings (seconds): P1=180  P2=300  P3=300  P4=360  P5=360
# Fault mechanism:   kubectl apply/delete -f cnp-fault.yaml
# Traffic:           Invoke-WebRequest /products every 3s
# ============================================================

$elb = "a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com"
$faultFile = ".\cnp-fault.yaml"

# --- pre-flight checks (do not skip) ---
if (-not (Test-Path $faultFile)) {
    Write-Host "ABORT: $faultFile not found in current directory." -ForegroundColor Red
    return
}
Write-Host "Pre-flight: confirming stack is healthy before baseline..." -ForegroundColor Gray
try {
    $pre = Invoke-WebRequest -Uri "http://$elb/products" -UseBasicParsing -TimeoutSec 10
    if ($pre.StatusCode -ne 200) {
        Write-Host "ABORT: ELB returned $($pre.StatusCode), expected 200." -ForegroundColor Red
        return
    }
    Write-Host "Pre-flight OK: ELB returned 200." -ForegroundColor Green
} catch {
    Write-Host "ABORT: ELB not reachable: $($_.Exception.Message)" -ForegroundColor Red
    return
}

# --- traffic generator (identical to documented run) ---
function Send-Traffic($seconds, $label) {
    $end = (Get-Date).AddSeconds($seconds)
    $count = 0; $errors = 0
    while ((Get-Date) -lt $end) {
        try {
            Invoke-WebRequest -Uri "http://$elb/products" -UseBasicParsing -TimeoutSec 5 | Out-Null
            $count++
        } catch { $errors++ }
        Start-Sleep -Seconds 3
    }
    Write-Host "[$label] OK:$count ERR:$errors ended $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor Cyan
}

$testStart = Get-Date
Write-Host "==== PHASE 7 BASELINE TEST START $(Get-Date -Format 'HH:mm:ss') ====" -ForegroundColor Yellow

# --- Phase 1: Normal 3 min ---
Write-Host "PHASE 1 NORMAL START $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor Green
Send-Traffic 180 "P1-NORMAL"

# --- Phase 2: Fault 1, 5 min ---
Write-Host "PHASE 2 FAULT-1 START $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor Red
kubectl apply -f $faultFile
Send-Traffic 300 "P2-FAULT1"

# --- Phase 3: Normal 5 min ---
Write-Host "PHASE 3 NORMAL START $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor Green
kubectl delete -f $faultFile
Send-Traffic 300 "P3-NORMAL"

# --- Phase 4: Fault 2, 6 min ---
Write-Host "PHASE 4 FAULT-2 START $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor Red
kubectl apply -f $faultFile
Send-Traffic 360 "P4-FAULT2"

# --- Phase 5: Normal 6 min ---
Write-Host "PHASE 5 NORMAL START $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor Green
kubectl delete -f $faultFile
Send-Traffic 360 "P5-NORMAL"

$testEnd = Get-Date
Write-Host "==== TEST COMPLETE $(Get-Date -Format 'HH:mm:ss') ====" -ForegroundColor Yellow
Write-Host "Dash0 query window: $($testStart.ToString('yyyy-MM-dd HH:mm:ss')) to $($testEnd.ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor Magenta
Write-Host "(Original run focused 13:55-14:10; use your actual window above for the dashboards.)" -ForegroundColor Gray
