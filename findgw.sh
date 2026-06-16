#!/bin/bash
GW_PID=$(grep -l "10.0.3.216" /proc/*/net/fib_trie 2>/dev/null | while read f; do
  pid=$(echo $f | cut -d/ -f3)
  if grep -q " eth0:" /proc/$pid/net/dev 2>/dev/null; then
    echo $pid
    break
  fi
done)
echo "Gateway PID: $GW_PID"
echo "Gateway IP: $(nsenter --net=/proc/$GW_PID/ns/net -- ip addr show eth0 2>/dev/null | grep 'inet ')"
echo "Product-svc IP: 10.0.2.146 (node B)"