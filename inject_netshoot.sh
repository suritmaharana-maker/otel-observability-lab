#!/bin/bash
set -e

# Find gateway pod netns PID - has eth0 + 10.0.3.189
GW_PID=$(grep -l "10.0.3.189" /proc/*/net/fib_trie 2>/dev/null | while read f; do
  pid=$(echo $f | cut -d/ -f3)
  if grep -q " eth0:" /proc/$pid/net/dev 2>/dev/null; then
    echo $pid
    break
  fi
done)

echo "Gateway PID: $GW_PID"

# Verify tc and nsenter are netshoot's own binaries
echo "tc: $(which tc) - $(tc -Version 2>&1 | head -1)"
echo "nsenter: $(which nsenter)"

# Enter gateway netns and inject fault using netshoot's own tc
nsenter --net=/proc/$GW_PID/ns/net -- tc qdisc add dev eth0 root handle 1: prio priomap 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
nsenter --net=/proc/$GW_PID/ns/net -- tc qdisc add dev eth0 parent 1:3 handle 30: netem delay 200ms loss 10%
nsenter --net=/proc/$GW_PID/ns/net -- tc filter add dev eth0 protocol ip parent 1:0 prio 3 u32 match ip dst 10.0.3.178/32 flowid 1:3

echo "=== Qdiscs ==="
nsenter --net=/proc/$GW_PID/ns/net -- tc qdisc show dev eth0

echo "=== Filters ==="
nsenter --net=/proc/$GW_PID/ns/net -- tc -s filter show dev eth0