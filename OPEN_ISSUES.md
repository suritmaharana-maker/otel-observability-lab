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


---

## OPEN ISSUE: hubble_drop_total POLICY_DENY/POLICY_DENIED not being recorded

Status: root cause substantially narrowed (2026-08-08), still
unresolved. Was NOT a Hubble reliability bug as originally framed.
Date found: 2026-08-06. Updated: 2026-08-08.

### UPDATE 2026-08-08 - the real finding

Every earlier test in this issue queried the WRONG cilium-agent pod.
Cilium enforces policy per-node; the DaemonSet's label selector
(`daemonset/cilium` or `-l k8s-app=cilium`) picks whichever pod
happens to be first, which is essentially arbitrary and was never
guaranteed to be the node actually enforcing the specific policy
under test. That single methodology error explains every "nothing
at all, not even at the raw monitor level" result recorded below
from 2026-08-06.

Retested today by first checking which node gateway and product-svc
actually run on, then targeting the CORRECT cilium-agent (the one on
product-svc's node, since our fault is an ingress policy on
product-svc):
- `cilium-dbg monitor --type drop` on the correct node: shows real,
  repeated "drop (Policy denied by denylist)" events immediately.
- `hubble observe --verdict DROPPED` on the correct node: also shows
  the same drops clearly, reason text "Policy denied by denylist".
- So the drops are 100% genuinely happening AND genuinely captured
  by both Cilium's raw eBPF monitor and Hubble's own flow-observation
  layer. Nothing is broken at that level - this directly contradicts
  the original "not an otelcol issue, not a broken fault, the gap is
  in Hubble's flow capture itself" conclusion below, which was based
  on monitoring the wrong node.

BUT: hubble_drop_total (the EXPORTED PROMETHEUS METRIC) still shows
NOTHING for this drop, under any reason string, even seconds after
the confirmed-real drop. Tested two rule types to isolate why:
- fault-block-gateway (ingressDeny, Cilium's explicit deny-rule
  feature): raw reason "Policy denied by denylist" - not counted.
- A second, disposable test policy using a standard allow-list
  `ingress` rule (implicit deny via an unmatched fromEndpoints
  selector): raw reason changes to plain "Policy denied" - ALSO not
  counted in the metric.

This rules out "ingressDeny specifically is unsupported by the
metrics exporter" - the gap is broader: ANY policy-verdict-based drop
(denylist or standard allow-list) fails to reach hubble_drop_total,
while non-policy datapath drops (UNSUPPORTED_L3_PROTOCOL) export
correctly and consistently. The gap is specifically between Hubble's
flow-observation layer (works, confirmed) and its metrics-export
layer (fails, confirmed) - for policy-verdict reasons only.

Also checked and ruled out: cilium-agent's own native metrics
(typically port 9962, would give an independent counter bypassing
Hubble's flow-log path entirely) is not listening/enabled in our
config at all - not an available cross-check without enabling a new
cilium-agent flag, a bigger change than attempted today.

### Original findings below (2026-08-06) - now understood to be
### artifacts of monitoring the wrong node, not evidence of a genuine
### capture failure. Kept for the record.

### Expected behavior
When a CiliumNetworkPolicy blocks traffic (ingressDeny), Hubble should
record a DROPPED-verdict flow with reason=POLICY_DENY or
POLICY_DENIED, exported as hubble_drop_total. This worked reliably
earlier the same day (real values like baseline 0->106, 0->15.1 were
used successfully in /diagnose testing).

### What's confirmed broken
- hubble_drop_total{reason=~"POLICY_DENY|POLICY_DENIED"} returns ZERO
  series/data during multiple genuine, confirmed-active fault windows
  - checked across two full fault cycles from Surit's continuous
  fault-test run (05:26:41-05:31:25 and 05:35:51-05:40:48 UTC), and
  again in a controlled manual test after a full cilium DaemonSet
  restart (06:03:32-06:04:13 UTC).
- Raw `hubble observe --verdict DROPPED` for the gateway pod shows
  NOTHING during an active fault window, even with real traffic
  concurrently hitting the blocked endpoint.
- UNSUPPORTED_L3_PROTOCOL reason continues to record fine throughout
  (confirmed value=402 during the same window POLICY_DENY was
  missing) - so the hubble_drop_total metric pipeline itself works in
  general; this is specific to the POLICY_DENY/POLICY_DENIED reason.

### What's confirmed NOT the cause (ruled out)
- Not a broken fault: verified twice, before and after the cilium
  restart, that gateway->product-svc requests genuinely time out
  while the policy is applied. Enforcement is 100% intact.
- Not an otelcol/export pipeline issue: this is upstream of otelcol -
  Hubble's own live `hubble observe` stream shows nothing, so the gap
  is in Hubble's flow generation/capture itself, not in shipping it
  onward.
- Not a metric-name bug: same query pattern that worked earlier today
  (and still works for UNSUPPORTED_L3_PROTOCOL right now) returns
  nothing specifically for POLICY_DENY/POLICY_DENIED.
- Not buffer pressure / stale daemon state: `cilium-dbg status
  --verbose` showed Hubble's flow buffer at 100% capacity
  (4095/4095) before the restart - a plausible suspect - but a full
  `kubectl rollout restart daemonset cilium -n kube-system` reset the
  buffer to 15.92% (652/4095) and the problem persisted identically
  afterward. Cluster health, all app pods, and fault enforcement were
  all confirmed unaffected by the restart.

### Not yet checked
- cilium-dbg policy trace for the specific gateway->product-svc flow,
  to see Cilium's own internal verdict/reasoning for this exact policy
  evaluation.
- monitor-aggregation settings (a Cilium feature that can suppress
  repeated flow notifications for efficiency) - not yet inspected to
  see if it's set more aggressively than expected, or changed
  recently.
- Whether this correlates with anything else that changed today
  (e.g. the helm/cilium-values.yaml hubble tcp sourceContext change
  from a related session, or the otelcol filelog receiver addition -
  neither obviously touches drop-reason classification, but not
  fully ruled out).
- cilium-agent's own native /metrics (typically port 9962) - attempted
  a port-forward to cross-check against a lower-level counter
  independent of Hubble's flow-log path, but the port wasn't
  listening/exposed as configured; container only declares health
  (9879), peer-service (4244), and hubble-metrics (9965) ports.

### Next step when resumed (updated 2026-08-08)
1. Check hubble.metrics context-option config for `drop` specifically
   - it's currently enabled with zero options (bare `- drop` in
     helm/cilium-values.yaml). Cilium's docs confirm context options
     are supported for all metrics; unclear if there's a relevant one
     for policy-verdict counting specifically, but not yet checked.
2. Check Cilium's own GitHub issues for known bugs/limitations in the
   hubble_drop_total metrics-export path specifically for
   policy-verdict reasons (not yet searched with this precise framing
   - prior searches were framed around monitor-aggregation and buffer
   state, both now ruled out).
3. If no config fix exists, consider enabling cilium-agent's own
   native /metrics (port 9962, not currently listening/enabled) as an
   independent counter, to confirm whether this is genuinely a
   Hubble-specific metrics gap or something deeper in cilium-agent's
   own metrics subsystem.
4. Given /diagnose's Tier 1 (real Cilium policy-change LOG content,
   added 2026-08-07) already gives a reliable, working signal for
   "was a policy applied/removed," hubble_drop_total's policy-deny
   count is now a less critical gap than when this issue was first
   opened - Tier 1 covers the core "did a policy change happen"
   question independently of this metric.


---

## OPEN ISSUE: Dash0 recording rule never evaluates despite being enabled

Status: unresolved, worked around (live query instead of precomputed).
Date found: 2026-08-07

### What's confirmed
- topology-discovery recording rule (k8s/topology-recording-rule.yaml,
  record=topology:edge_bytes:sum_rate2h) has been registered and
  enabled=true in Dash0 for ~2 hours, with a 10m evaluation interval -
  should have evaluated roughly 10+ times by now.
- GET /api/recording-rules shows dash0.com/first-evaluation-at is
  EMPTY for this rule - it has never actually run.
- Querying topology:edge_bytes:sum_rate2h directly returns zero
  results (confirms it's never populated any data).
- The underlying data source is fully healthy: obi_network_flow_bytes
  itself returns real data when queried directly.
- The EXACT SAME PromQL expression the recording rule uses, run as a
  plain instant query (not through the recording-rule mechanism),
  returns 75 real topology edges immediately. This rules out the
  query itself being wrong - it's specifically the recording rule's
  scheduling/execution that isn't running, an apparent platform-side
  issue on Dash0's end, not a config problem on ours.

### Workaround in place
apps/llm-svc/llm_svc.py's validate_topology_edge() runs the identical
query live, per-request, instead of reading the precomputed metric.
This is fully correct today - just forfeits the "computed once every
10 minutes, queried cheaply many times" efficiency the recording rule
was meant to provide. Given /diagnose already runs several other
per-request PromQL queries, this added cost is likely negligible in
practice, but worth revisiting if request volume grows.

### Not yet checked
- Whether other recording rules (if any get created later) have the
  same never-evaluates behavior, which would confirm this is a
  systemic Dash0 platform issue rather than something specific to
  this one rule.
- Dash0 support/docs for any known issue matching this symptom.
- Whether deleting and recreating the rule (as was needed once before,
  for the interval-too-short error) resolves it - not attempted this
  time since the live-query workaround unblocked the actual feature.
