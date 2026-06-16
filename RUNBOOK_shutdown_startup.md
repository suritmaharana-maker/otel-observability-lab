# OTel Lab — Shutdown & Startup Runbook

## Why this matters
AWS EC2 instances get new internal IPs on restart. Pod nodeSelectors pinned to old
hostnames will cause Pending pods. CoreDNS and kube-proxy iptables rules need time
to stabilize before Beyla and product-svc can reach otelcol via DNS.

---

## GRACEFUL SHUTDOWN (before stopping instances)

Run in this exact order from PowerShell:

### Step 1 — Remove fault injection if active
```powershell
# Always clean up netem before shutdown
kubectl exec -n otel-lab netshoot -- bash -c "nsenter --net=/proc/GATEWAY_PID/ns/net -- tc qdisc del dev eth0 root" 2>$null
kubectl delete pod netshoot -n otel-lab --ignore-not-found
```

### Step 2 — Remove nodeSelectors (they pin to hostnames that change on restart)
```powershell
kubectl patch deployment gateway -n otel-lab -p '{\"spec\":{\"template\":{\"spec\":{\"nodeSelector\":{\"kubernetes.io/hostname\":\"PLACEHOLDER\"}}}}}'
kubectl patch deployment product-svc -n otel-lab -p '{\"spec\":{\"template\":{\"spec\":{\"nodeSelector\":{\"kubernetes.io/hostname\":\"PLACEHOLDER\"}}}}}'
```
**IMPORTANT:** Replace with placeholder — actual removal requires knowing the key.
Better approach — scale down before stopping:

```powershell
kubectl scale deployment gateway -n otel-lab --replicas=0
kubectl scale deployment product-svc -n otel-lab --replicas=0
```

### Step 3 — Scale down non-essential workloads
```powershell
kubectl scale deployment gateway -n otel-lab --replicas=0
kubectl scale deployment product-svc -n otel-lab --replicas=0
```

### Step 4 — Verify clean state
```powershell
kubectl get pods -n otel-lab
# Should show only beyla, postgres, and netshoot (if still running)
```

### Step 5 — Stop EC2 instances via AWS Console or CLI
```powershell
aws ec2 stop-instances --region us-east-2 --instance-ids `
  i-0e94796ce751202a9 `
  i-09d84dc38796ba523 `
  i-0d66e999774a4e2b6
```

---

## STARTUP SEQUENCE (after starting instances)

### Step 1 — Start instances
```powershell
aws ec2 start-instances --region us-east-2 --instance-ids `
  i-0e94796ce751202a9 `
  i-09d84dc38796ba523 `
  i-0d66e999774a4e2b6
```

### Step 2 — Wait for nodes to be Ready (2-3 minutes)
```powershell
kubectl get nodes -w
# Wait until all 3 show Ready
```

### Step 3 — Get new node names and IPs
```powershell
kubectl get nodes -o wide
# Note: hostnames change! e.g. ip-10-0-3-236 may become ip-10-0-3-223
```

### Step 4 — Restart CoreDNS first
```powershell
kubectl rollout restart deployment/coredns -n kube-system
kubectl rollout status deployment/coredns -n kube-system --timeout=120s
```

### Step 5 — Wait 30 seconds for DNS to stabilize
```powershell
Start-Sleep -Seconds 30
```

### Step 6 — Restart otelcol
```powershell
kubectl rollout restart daemonset/otelcol -n observability
kubectl rollout status daemonset/otelcol -n observability --timeout=120s
```

### Step 7 — Restart Beyla
```powershell
kubectl rollout restart daemonset/beyla -n otel-lab
kubectl rollout status daemonset/beyla -n otel-lab --timeout=120s
```

### Step 8 — Scale up app workloads
```powershell
kubectl scale deployment gateway -n otel-lab --replicas=1
kubectl scale deployment product-svc -n otel-lab --replicas=1
kubectl rollout status deployment/gateway -n otel-lab --timeout=90s
kubectl rollout status deployment/product-svc -n otel-lab --timeout=90s
```

### Step 9 — Get new node names and re-pin deployments
```powershell
kubectl get nodes -o wide
# Pick node C for gateway, node B for product-svc

# Example (replace with actual new node names):
kubectl patch deployment gateway -n otel-lab -p '{\"spec\":{\"template\":{\"spec\":{\"nodeSelector\":{\"kubernetes.io/hostname\":\"NEW_NODE_C_HOSTNAME\"}}}}}'
kubectl patch deployment product-svc -n otel-lab -p '{\"spec\":{\"template\":{\"spec\":{\"nodeSelector\":{\"kubernetes.io/hostname\":\"NEW_NODE_B_HOSTNAME\"}}}}}'
```

### Step 10 — Verify all pods Running
```powershell
kubectl get pods -A | Select-String "Pending|Error|CrashLoop|Init"
# Should return nothing
kubectl get pods -n otel-lab -o wide
kubectl get pods -n observability -o wide
```

### Step 11 — Verify Beyla DNS working
```powershell
kubectl logs -n otel-lab -l app.kubernetes.io/name=beyla --tail=5
# Should NOT see: dns: A record lookup error
# Should see: Flows agent successfully started
```

### Step 12 — Verify otelcol exporting to Dash0
```powershell
$otelPods = kubectl get pods -n observability -o name
foreach ($pod in $otelPods -split "`n") {
    if ($pod -match "otelcol") {
        kubectl logs -n observability $pod.Replace("pod/","") --tail=3
    }
}
# Should see: Traces {...} spans: N (not connection reset errors)
```

### Step 13 — Sanity check — send 5 requests
```powershell
$elb = "a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com"
for ($i = 1; $i -le 5; $i++) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $r = Invoke-WebRequest -Uri "http://$elb/products" -UseBasicParsing -TimeoutSec 10
    $sw.Stop()
    Write-Host "[$i] $($r.StatusCode) - $($sw.ElapsedMilliseconds)ms"
    Start-Sleep -Milliseconds 500
}
# All should be 200, 70-150ms
```

### Step 14 — Deploy netshoot on gateway's node for fault injection
```powershell
# Get gateway's node
$gwNode = kubectl get pod -n otel-lab -l app=gateway -o jsonpath='{.items[0].spec.nodeName}'
Write-Host "Gateway node: $gwNode"

# Update netshoot-pod.yaml nodeName field and apply
(Get-Content netshoot-pod.yaml) -replace 'nodeName:.*', "nodeName: $gwNode" | Set-Content netshoot-pod.yaml
kubectl apply -f netshoot-pod.yaml
kubectl wait --for=condition=Ready pod/netshoot -n otel-lab --timeout=60s
```

### Step 15 — Find new gateway PID
```powershell
$gwIP = kubectl get pod -n otel-lab -l app=gateway -o jsonpath='{.items[0].status.podIP}'
Write-Host "Gateway IP: $gwIP"

@"
#!/bin/bash
GW_PID=`$(grep -l "$gwIP" /proc/*/net/fib_trie 2>/dev/null | while read f; do
  pid=`$(echo `$f | cut -d/ -f3)
  if grep -q " eth0:" /proc/`$pid/net/dev 2>/dev/null; then
    echo `$pid
    break
  fi
done)
echo "Gateway PID: `$GW_PID"
"@ | Out-File -FilePath findgw.sh -Encoding ascii -NoNewline

kubectl cp findgw.sh otel-lab/netshoot:/tmp/findgw.sh
kubectl exec -n otel-lab netshoot -- bash /tmp/findgw.sh
```

---

## FAULT INJECTION COMMANDS (Phase 3 demo)

### Inject fault (run FIRST, then generate traffic)
```powershell
kubectl exec -n otel-lab netshoot -- bash -c "nsenter --net=/proc/GATEWAY_PID/ns/net -- tc qdisc add dev eth0 root netem delay 200ms loss 10%"
```

### Remove fault
```powershell
kubectl exec -n otel-lab netshoot -- bash -c "nsenter --net=/proc/GATEWAY_PID/ns/net -- tc qdisc del dev eth0 root"
```

### Verify fault active
```powershell
kubectl exec -n otel-lab netshoot -- bash -c "nsenter --net=/proc/GATEWAY_PID/ns/net -- tc qdisc show dev eth0"
# Should show: qdisc netem ... delay 200ms loss 10%
```

---

## QUICK REFERENCE — Fixed values (do not change between restarts)

| Item | Value |
|---|---|
| ELB | a1ebab3cadc314c52a0099b4f51b1871-418152640.us-east-2.elb.amazonaws.com |
| VPC | vpc-00a1138c8d1c4d109 |
| Instance A | i-0e94796ce751202a9 (us-east-2a) |
| Instance B | i-09d84dc38796ba523 (us-east-2b) |
| Instance C | i-0d66e999774a4e2b6 (us-east-2c) |
| Dash0 endpoint | ingress.us-west-2.aws.dash0.com:4317 |
| otelcol service | otelcol.observability.svc.cluster.local:4317 |

## Values that CHANGE on every restart
- Node hostnames (ip-10-0-X-YYY)
- Pod IPs
- Gateway PID inside netshoot
- netshoot nodeName in pod spec

