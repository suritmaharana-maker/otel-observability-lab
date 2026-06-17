# OTel Lab — Load Generator
# Usage: .\load-generator.ps1 [-DurationSeconds 300] [-IntervalMs 500] [-TimeoutSec 15]
# Default: 5 minutes, 500ms interval, 15s timeout

param(
    [int]$DurationSeconds = 300,
    [int]$IntervalMs = 500,
    [int]$TimeoutSec = 15
)

$elb = "a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com"
$url = "http://$elb/products"
$start = Get-Date
$startStr = $start.ToString("HH:mm:ss")
$i = 0
$errors = 0
$successes = 0

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " OTel Lab Load Generator" -ForegroundColor Cyan
Write-Host " Start:    $startStr" -ForegroundColor Cyan
Write-Host " Duration: ${DurationSeconds}s" -ForegroundColor Cyan
Write-Host " Interval: ${IntervalMs}ms" -ForegroundColor Cyan
Write-Host " Timeout:  ${TimeoutSec}s" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

while (((Get-Date) - $start).TotalSeconds -lt $DurationSeconds) {
    $i++
    $elapsed = [int]((Get-Date) - $start).TotalSeconds
    $timestamp = (Get-Date).ToString("HH:mm:ss.fff")
    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec $TimeoutSec
        $sw.Stop()
        $ms = $sw.ElapsedMilliseconds
        $successes++

        # Color code by latency
        if ($ms -lt 200) {
            Write-Host "[$timestamp +${elapsed}s #$i] $($r.StatusCode) ${ms}ms" -ForegroundColor Green
        } elseif ($ms -lt 1000) {
            Write-Host "[$timestamp +${elapsed}s #$i] $($r.StatusCode) ${ms}ms  ⚠ SLOW" -ForegroundColor Yellow
        } else {
            Write-Host "[$timestamp +${elapsed}s #$i] $($r.StatusCode) ${ms}ms  ⚠⚠ VERY SLOW" -ForegroundColor DarkYellow
        }
    } catch {
        $sw.Stop()
        $ms = $sw.ElapsedMilliseconds
        $errors++
        Write-Host "[$timestamp +${elapsed}s #$i] ERROR ${ms}ms  ✗ $($_.Exception.Message.Split('.')[0])" -ForegroundColor Red
    }

    Start-Sleep -Milliseconds $IntervalMs
}

# Summary
$endStr = (Get-Date).ToString("HH:mm:ss")
$total = $successes + $errors
$errorRate = if ($total -gt 0) { [math]::Round(($errors / $total) * 100, 1) } else { 0 }

Write-Host "" 
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Load Generator Complete" -ForegroundColor Cyan
Write-Host " Start:      $startStr" -ForegroundColor Cyan
Write-Host " End:        $endStr" -ForegroundColor Cyan
Write-Host " Total:      $total requests" -ForegroundColor Cyan
Write-Host " Success:    $successes" -ForegroundColor Green
Write-Host " Errors:     $errors ($errorRate%)" -ForegroundColor $(if ($errors -gt 0) { "Red" } else { "Green" })
Write-Host "========================================" -ForegroundColor Cyan
