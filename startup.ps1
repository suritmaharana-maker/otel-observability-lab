# OTel Lab Startup Script - run after starting EC2 instances
Write-Host "=== OTel Lab Startup ===" -ForegroundColor Cyan
Write-Host "Waiting for nodes Ready..." -ForegroundColor Yellow
kubectl wait --for=condition=Ready node --all --timeout=300s
Write-Host "Restarting CoreDNS..." -ForegroundColor Yellow
kubectl rollout restart deployment/coredns -n kube-system
kubectl rollout status deployment/coredns -n kube-system --timeout=120s
Start-Sleep -Seconds 30
Write-Host "Restarting otelcol..." -ForegroundColor Yellow
kubectl rollout restart daemonset/otelcol -n observability
kubectl rollout status daemonset/otelcol -n observability --timeout=120s
Write-Host "Restarting Beyla..." -ForegroundColor Yellow
kubectl rollout restart daemonset/beyla -n otel-lab
kubectl rollout status daemonset/beyla -n otel-lab --timeout=120s
Write-Host "Scaling up app workloads..." -ForegroundColor Yellow
kubectl scale deployment gateway -n otel-lab --replicas=1
kubectl scale deployment product-svc -n otel-lab --replicas=1
kubectl rollout status deployment/gateway -n otel-lab --timeout=90s
kubectl rollout status deployment/product-svc -n otel-lab --timeout=90s
$nodeC = (kubectl get nodes -o jsonpath='{.items[2].metadata.name}')
$nodeB = (kubectl get nodes -o jsonpath='{.items[1].metadata.name}')
Write-Host "Pinning: gateway to $nodeC, product-svc to $nodeB" -ForegroundColor Yellow
kubectl patch deployment gateway -n otel-lab -p "{`"spec`":{`"template`":{`"spec`":{`"nodeSelector`":{`"kubernetes.io/hostname`":`"$nodeC`"}}}}}"
kubectl patch deployment product-svc -n otel-lab -p "{`"spec`":{`"template`":{`"spec`":{`"nodeSelector`":{`"kubernetes.io/hostname`":`"$nodeB`"}}}}}"
kubectl rollout status deployment/gateway -n otel-lab --timeout=90s
kubectl rollout status deployment/product-svc -n otel-lab --timeout=90s
Write-Host "`n=== Final state ===" -ForegroundColor Cyan
kubectl get pods -n otel-lab -o wide
kubectl get pods -n observability -o wide
Write-Host "`nStartup complete. Deploy netshoot and run findgw.sh for gateway PID." -ForegroundColor Green