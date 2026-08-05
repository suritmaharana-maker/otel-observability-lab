## OPEN ISSUE: hubble_tcp_flags_total SYN-ACK missing for gateway as server

Status: unresolved, deferred by Surit until after /diagnose work.
Date found: 2026-08-05

### Expected behavior
Every successful SYN handshake should produce a corresponding SYN-ACK.
Unsuccessful/degraded connections should show retransmits. Both are
standard TCP semantics, not specific to our stack.

### What's confirmed
- Cilium's own identity for the gateway pod is healthy (ID:992,
  k8s:app=gateway, status=ready) - not an identity resolution problem.
- hubble_tcp_flags_total{flag="SYN-ACK", destination="gateway"} has
  ZERO matches in current data - the panel's exact filter structurally
  matches nothing right now.
- SYN-ACK data DOES exist for other pairs (e.g. product-svc as
  source/destination), so the metric pipeline itself works in general.
- Raw `hubble observe` on gateway's incoming ELB-sourced connections
  shows a repeating pattern: SYN, then ACK, then ACK+FIN - never a
  distinct "SYN, ACK" combined flag event. This pattern repeats every
  ~10s and is almost certainly the Classic ELB's own health check
  probes (no payload), not real HTTP traffic.
- A pod-to-pod test (bypassing the ELB) was attempted to isolate
  whether gateway-as-server ever produces a captured SYN-ACK for real
  traffic, but the test window didn't clearly capture a data point -
  inconclusive, not a real answer either way.

### What's NOT yet confirmed
Whether gateway replying to a REAL client request (not a health check)
ever gets a properly flagged SYN-ACK event in Hubble. This is the
actual open question - need a cleaner, more controlled test:
generate real traffic and immediately hubble-observe filtered to
gateway's pod, watching specifically for the reply direction ("<-")
the way otelcol's connections show both directions cleanly.

### Also relevant, not yet investigated
- Retransmit signal (hubble side) hasn't been checked at all yet for
  this same gateway-as-server gap.
- obi_stat_tcp_retransmits exists and is filterable (confirmed
  separately) but hasn't been cross-checked against this same question.

### Next step when resumed
1. Clean controlled test: single real request to gateway via ELB,
   immediately `hubble observe --pod otel-lab/<gateway-pod> -o compact`
   watching for both directions of the flow.
2. If still missing, check whether Classic ELB's TCP passthrough vs
   termination behavior affects what Hubble can observe (host-network
   sourced connections may have asymmetric capture points vs pure
   pod-to-pod).
3. Cross-check obi_stat_tcp_retransmits for the same gap.
