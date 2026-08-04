# ============================================================
# Hubble UI watchdog - keeps kubectl port-forward alive indefinitely.
# Checks http://localhost:12000 every 15s; if unreachable, kills any
# stale port-forward process and starts a fresh one. Survives pod
# reschedules, node replacements, and Hubble UI pod restarts.
# Run this once in the background; leave it running.
# ============================================================
$ErrorActionPreference = "SilentlyContinue"
$localPort = 12000
$svcPort = 80

function Start-Forward {
    Get-Process kubectl -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -like "*port-forward*hubble-ui*"
    } | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Process -FilePath "kubectl" -ArgumentList "port-forward -n kube-system svc/hubble-ui $localPort`:$svcPort" -WindowStyle Hidden
}

Write-Host "=== Hubble UI watchdog started ===" -ForegroundColor Green
Write-Host "Checking http://localhost:$localPort every 15s. Ctrl+C to stop."

Start-Forward
Start-Sleep -Seconds 3

while ($true) {
    $ok = $false
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$localPort" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $ok = $true }
    } catch { $ok = $false }

    if (-not $ok) {
        $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Write-Host "[$ts] Tunnel down, restarting..." -ForegroundColor Yellow
        Start-Forward
        Start-Sleep -Seconds 3
    }
    Start-Sleep -Seconds 15
}
