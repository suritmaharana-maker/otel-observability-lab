#!/bin/bash
GW_IF=$(ip route | grep 10.0.3.189 | awk '{print $3}')
echo "Gateway veth interface: $GW_IF"
tc qdisc add dev $GW_IF root handle 1: prio priomap 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
tc qdisc add dev $GW_IF parent 1:3 handle 30: netem delay 200ms loss 10%
tc filter add dev $GW_IF protocol ip parent 1:0 prio 3 u32 match ip dst 10.0.3.178/32 flowid 1:3
echo "Fault injected. Qdiscs:"
tc qdisc show dev $GW_IF