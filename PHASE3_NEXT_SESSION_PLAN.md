# Phase 3 — Next Session Execution Plan
# The Network Blindspot Demo — Definitive Smoking Gun

## The Money Shot We Are Building

**Three windows. One story. Undeniable evidence.**

```
Window 1 — OTel SDK (APM layer):
  GET /products → 5,016ms → ERROR 502
  └── GET /products → 5,005ms (waiting...)
       └── [NOTHING — product-svc never called]
  
  APM verdict: "Something is slow. I don't know why."

Window 2 — Hubble (eBPF network layer):
  10.0.3.216:52314 -> 10.0.2.146:8001 TCP DROPPED
  10.0.3.216:52318 -> 10.0.2.146:8001 TCP DROPPED
  10.0.3.216:52322 -> 10.0.2.146:8001 TCP DROPPED
  
  eBPF verdict: "Packets from gateway:ephemeral → product-svc:8001 are being DROPPED."

Window 3 — Beyla L7 (application network timing):
  GET /products duration=4,987ms [anomaly vs p99 baseline 66ms]
  
  eBPF verdict: "This request took 75x longer than normal."
```

**The story:** APM sees symptoms. eBPF sees cause. OTel is the pipeline that carries both.

---

## Pre-Session Checklist (do BEFORE anything else)

```powershell
# 1. Run startup script
.\startup.ps1

# 2. Verify all pods healthy
kubectl get pods -n otel-lab -o wide
kubectl get pods -n observability -o wide
kubectl get pods -n kube-system | Select-String "cilium|hubble|coredns"

# 3. Verify Beyla DNS working (no lookup errors)
kubectl logs -n otel-lab -l app.kubernetes.io/name=beyla --tail=5

# 4. Verify otelcol exporting cleanly
kubectl logs -n observability -l app=otelcol --tail=5

# 5. Verify product-svc connecting to otelcol
kubectl exec -n otel-lab deployment/product-svc -- env | Select-String "OTEL"

# 6. Deploy netshoot on gateway's node
$gwNode = kubectl get pod -n otel-lab -l app=gateway -o jsonpath='{.items[0].spec.nodeName}'
(Get-Content netshoot-pod.yaml) -replace 'nodeName:.*', "  nodeName: $gwNode" | Set-Content netshoot-pod.yaml
kubectl apply -f netshoot-pod.yaml
kubectl wait --for=condition=Ready pod/netshoot -n otel-lab --timeout=60s

# 7. Find gateway PID
$gwIP = kubectl get pod -n otel-lab -l app=gateway -o jsonpath='{.items[0].status.podIP}'
(Get-Content findgw.sh) -replace '10\.0\.\d+\.\d+', $gwIP | Set-Content findgw.sh
kubectl cp findgw.sh otel-lab/netshoot:/tmp/findgw.sh
kubectl exec -n otel-lab netshoot -- bash /tmp/findgw.sh
# NOTE THE PID — you need it for fault injection

# 8. Sanity check — 5 clean requests
$elb = "a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com"
for ($i = 1; $i -le 5; $i++) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $r = Invoke-WebRequest -Uri "http://$elb/products" -UseBasicParsing -TimeoutSec 10
    $sw.Stop()
    Write-Host "[$i] $($r.StatusCode) - $($sw.ElapsedMilliseconds)ms"
    Start-Sleep -Milliseconds 500
}
# All 200, 70-150ms = ready to go
```

---

## The Demo — Four Windows

### Window 1 — Hubble live flow observer (START FIRST)
```powershell
# Get cilium pod on gateway's node
$gwNode = kubectl get pod -n otel-lab -l app=gateway -o jsonpath='{.items[0].spec.nodeName}'
$ciliumPod = kubectl get pod -n kube-system -l k8s-app=cilium --field-selector spec.nodeName=$gwNode -o jsonpath='{.items[0].metadata.name}'
Write-Host "Cilium pod: $ciliumPod"

# Watch live drops between gateway and product-svc
kubectl exec -n kube-system $ciliumPod -c cilium-agent -- \
  hubble observe --from-namespace otel-lab --to-namespace otel-lab \
  --protocol tcp -f
```
**This streams every TCP flow tuple in real time.**
**During fault you will see DROPPED verdicts on port 8001.**

### Window 2 — Continuous traffic (5 minutes)
```powershell
$elb = "a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com"
$start = Get-Date
while (((Get-Date) - $start).TotalSeconds -lt 300) {
    $elapsed = [int]((Get-Date) - $start).TotalSeconds
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $r = Invoke-WebRequest -Uri "http://$elb/products" -UseBasicParsing -TimeoutSec 15
        $sw.Stop()
        Write-Host "[${elapsed}s] $($r.StatusCode) - $($sw.ElapsedMilliseconds)ms"
    } catch {
        $sw.Stop()
        Write-Host "[${elapsed}s] ERROR - $($sw.ElapsedMilliseconds)ms"
    }
    Start-Sleep -Milliseconds 500
}
```

### Window 3 — Fault control (wait 3 min then inject)
```powershell
# REPLACE GATEWAY_PID with actual PID from pre-session checklist
$GW_PID = "GATEWAY_PID_HERE"

Write-Host "Waiting 3 minutes for clean baseline at $(Get-Date -Format 'HH:mm:ss')..."
Start-Sleep -Seconds 180

Write-Host "=== INJECTING FAULT at $(Get-Date -Format 'HH:mm:ss') ===" -ForegroundColor Red
kubectl exec -n otel-lab netshoot -- bash -c "nsenter --net=/proc/$GW_PID/ns/net -- tc qdisc add dev eth0 root netem delay 200ms loss 10%"
kubectl exec -n otel-lab netshoot -- bash -c "nsenter --net=/proc/$GW_PID/ns/net -- tc qdisc show dev eth0"

Write-Host "Fault active. Waiting 60 seconds..." -ForegroundColor Red
Start-Sleep -Seconds 60

Write-Host "=== REMOVING FAULT at $(Get-Date -Format 'HH:mm:ss') ===" -ForegroundColor Green
kubectl exec -n otel-lab netshoot -- bash -c "nsenter --net=/proc/$GW_PID/ns/net -- tc qdisc del dev eth0 root"
Write-Host "=== FAULT REMOVED - recovery phase ===" -ForegroundColor Green
```

### Window 4 — Dash0 (browser)
- Open Dash0 before starting
- Set time range to last 10 minutes, auto-refresh on
- Have these four tabs ready:
  - **Tracing → All traces** sorted by duration descending
  - **Metrics → beyla.network.flow.bytes** filtered by src=gateway
  - **Tracing → Database queries** (to confirm SQL disappears during fault)
  - **Metrics → hubble_drop_total** (Cilium policy drops)

---

## Screenshots to Capture (in order)

### Screenshot 1 — BEFORE fault (baseline)
- Dash0 Tracing: open any GET /products trace
- Show full 6-span waterfall: gateway → product-svc → SELECT products → 2ms SQL
- Caption: "Healthy baseline: 6 spans, full visibility, SQL query 2ms"

### Screenshot 2 — DURING fault (APM view)
- Dash0 Tracing: open a 5,016ms ERROR trace
- Show truncated waterfall: gateway → [nothing] — no product-svc, no SQL
- Caption: "APM during fault: 5 seconds, 502 error, zero root cause visibility"

### Screenshot 3 — DURING fault (Hubble view)
- Window 1 terminal showing:
  ```
  10.0.3.X:NNNNN -> 10.0.2.X:8001 tcp DROPPED
  10.0.3.X:NNNNN -> 10.0.2.X:8001 tcp DROPPED
  ```
- Caption: "eBPF sees what APM cannot: exact dropped TCP tuples, src/dst/port"

### Screenshot 4 — Side by side
- Left: the 5,016ms APM trace (no root cause)
- Right: Hubble showing DROPPED on port 8001
- Caption: "Same incident. Two lenses. Only eBPF tells you why."

### Screenshot 5 — AFTER fault (recovery)
- Dash0 Tracing: clean trace back to 70-130ms with SQL span
- Beyla flow bytes recovered
- Caption: "One command removed the fault. Full visibility restored instantly."

---

## The LinkedIn Post Draft (write after screenshots)

**Title:** "APM told me my app was slow. eBPF told me why. This is the gap nobody is talking about."

**Hook:** I injected a network fault between two microservices on Kubernetes.
My APM dashboard showed a 5-second timeout and a 502 error.
It had no idea why.

**The story:** [Screenshot 2] This is what your APM sees.
[Screenshot 3] This is what eBPF sees.
[Screenshot 4] Same incident. One tells you something is wrong. The other tells you exactly which packet stream is being dropped, on which port, between which endpoints.

**The insight:** The gap between these two views is costing enterprises millions in MTTR.
I spent 15 years at JPMorgan Chase watching teams spend hours in bridge calls debugging
latency that turned out to be a single misconfigured network policy.
With eBPF + OTel in the same pipeline, that call ends in minutes.

**The tech:** OpenTelemetry SDK + Grafana Beyla 3.20.0 + Cilium Hubble 1.19.4
All signals — traces, metrics, logs, network flows — in one OTel pipeline to Dash0.
All code public on GitHub.

**The thesis:** App observability tells you something is broken.
Network observability tells you why.
The OTel pipeline is the missing bridge. At enterprise scale, this changes everything.

**CTA:** Full write-up on Substack. Link in comments.
Star the GitHub repo if you want to see Phase 4: GenAI observability.

---

## If Hubble observe does not show DROPPED verdicts

Fallback approach — tcpdump inside gateway netns:
```powershell
kubectl exec -n otel-lab netshoot -- bash -c "
  nsenter --net=/proc/GATEWAY_PID/ns/net -- \
  tcpdump -i eth0 -n 'dst port 8001' -c 50
"
```
During fault you will see TCP retransmits:
```
10.0.3.216.52314 > 10.0.2.146.8001: Flags [S], seq 123456, [retransmit]
10.0.3.216.52314 > 10.0.2.146.8001: Flags [S], seq 123456, [retransmit]
```
Retransmits on port 8001 from gateway = exact tuple, exact evidence.

---

## Post-Demo — Commit to GitHub

```powershell
git add -A
git commit -m "phase3: network blindspot demo complete — Hubble exact tuples, netem fault injection, screenshots"
git push origin main
```

---

## What This Proves at Enterprise Scale (JPMC narrative)

| Traditional approach | This approach |
|---|---|
| Riverbed AppResponse (on-prem) | Cilium Hubble (Kubernetes) |
| NetFlow 120M FPM | beyla.network.flow.bytes |
| CA APM Wily Introscope | OTel SDK + Beyla L7 spans |
| Separate tools, separate teams | One OTel pipeline, unified signal |
| Hours in bridge calls | Minutes to root cause |

**The enterprise pitch:** The same OTel Collector that receives your application traces
can also receive your network flow telemetry. One pipeline. One backend. One view.
This is what JPMorgan Chase, Goldman Sachs, and every large bank needs
but nobody has built yet — at least not in the open.

This lab is the proof of concept. Phase 6 extends it to on-prem + multi-cloud.
Phase 7 proves it works with Dynatrace and Datadog.
Phase 8 packages it for enterprise adoption.

