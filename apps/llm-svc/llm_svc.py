"""
llm-svc Phase 7 — Multi-backend /diagnose
Supports: ?backend=dash0 (default) | dynatrace | datadog (stub)

Phase 7 changes:
- Absolute time-window querying via ?start=<RFC3339>&end=<RFC3339> (Option A:
  instant query + PromQL @ anchor). Relative ?window=<dur> still supported as
  a fallback when start/end are not supplied.
- Three additional Dash0 signals: obi.network.flow.bytes,
  obi.stat.tcp.failed.connections, dash0.spans (product-svc).
- Prompt reframed to walk the proven causal chain across all signals.
"""
import os, json, logging, asyncio, time, statistics
from datetime import datetime, timezone
import boto3
import httpx
from fastapi import FastAPI, HTTPException

log = logging.getLogger("llm-svc")
logging.basicConfig(level=logging.INFO)

OTEL_ENDPOINT   = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otelcol.observability.svc.cluster.local:4317")
DASH0_AUTH_TOKEN = os.getenv("DASH0_AUTH_TOKEN", "")
DASH0_PROM_URL  = os.getenv("DASH0_PROMETHEUS_URL", "https://api.us-west-2.aws.dash0.com/api/prometheus")
DT_ENV_ID       = os.getenv("DT_ENVIRONMENT_ID", "yta61562")
DT_API_TOKEN    = os.getenv("DT_API_TOKEN", "")
BEDROCK_MODEL   = os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-micro-v1:0")
BEDROCK_REGION  = os.getenv("AWS_DEFAULT_REGION", "us-east-2")

# No OpenTelemetry SDK instrumentation for llm-svc's own HTTP/FastAPI layer.
# Network-team-only scope: this service's own self-tracing was never the
# point, and OBI's eBPF traces now cover it without any code here. All of
# llm-svc's actual RCA logic below (signal collection, change-point
# detection, Bedrock calls) is completely independent of this and is
# untouched.
app = FastAPI(title="OTel Lab — LLM Service", version="0.7.0")

PRODUCT_SVC_URL = os.getenv("PRODUCT_SVC_URL", "http://product-svc:8001")
bedrock = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)


# ─────────────────────────────────────────────
# TIME-WINDOW RESOLUTION  (Phase 7)
# ─────────────────────────────────────────────

def _parse_rfc3339(ts: str) -> datetime:
    """Parse an RFC3339 / ISO-8601 timestamp into an aware UTC datetime.
    Accepts a trailing 'Z' or an explicit offset."""
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def resolve_window(start: str | None, end: str | None) -> dict:
    """Resolve the query window. `start` is REQUIRED - there is no
    relative-duration fallback anymore.

    This is deliberate, not an oversight: the input-contract design
    established this session is that a diagnosis without a real incident
    start time is a guess, not a finding - "prescriptive, not a shot in
    the dark." A caller (APM) that can't supply a real start shouldn't
    get a confident-looking answer built from an arbitrary relative
    window like the old default "last 5m".

    `end` is optional and defaults to now - this is what lets a caller
    diagnose an incident that's STILL ONGOING, rather than being forced
    to supply an artificial end time before the incident has resolved.
    """
    if not start:
        raise HTTPException(
            status_code=400,
            detail=(
                "start is required (RFC3339, e.g. 2026-08-07T04:00:00Z). "
                "There is no relative-window fallback - a diagnosis without "
                "a real incident start time is a guess, not a finding. "
                "end is optional and defaults to now, for an incident that "
                "is still ongoing."
            ),
        )
    t_start = _parse_rfc3339(start)
    t_end = _parse_rfc3339(end) if end else datetime.now(timezone.utc)
    span_s = int((t_end - t_start).total_seconds())
    if span_s <= 0:
        raise HTTPException(
            status_code=400,
            detail=f"end ({end or 'now'}) must be after start ({start})",
        )
    end_label = end or "now"
    return {
        "range": f"{span_s}s",
        "anchor_epoch": t_end.timestamp(),
        "label": f"{start} -> {end_label} ({span_s}s)",
    }


# ─────────────────────────────────────────────
# SIGNAL BACKENDS
# ─────────────────────────────────────────────

async def query_dash0(metric_expr: str, win: dict) -> list:
    """Query Dash0 Prometheus instant-query API.

    `metric_expr` is a PromQL expression containing a single `[RANGE]` placeholder
    that this function fills from `win["range"]`. When `win["anchor_epoch"]` is set,
    the PromQL @ modifier pins evaluation to that absolute time and the instant
    query is sent with a matching `time=` param, so the result reflects the exact
    historical window rather than "now".
    """
    promql = metric_expr.replace("[RANGE]", f'[{win["range"]}]')
    anchor = win.get("anchor_epoch")
    if anchor is not None:
        # @ <epoch> anchors the range-vector evaluation to the window end.
        promql = promql.replace("[RANGE_END]", f" @ {anchor:.3f}")
    else:
        promql = promql.replace("[RANGE_END]", "")

    url = f"{DASH0_PROM_URL}/api/v1/query"
    headers = {"Authorization": f"Bearer {DASH0_AUTH_TOKEN}"}
    params = {"query": promql}
    if anchor is not None:
        params["time"] = f"{anchor:.3f}"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers, params=params, timeout=10.0)
            if r.status_code == 200:
                data = r.json()
                return data.get("data", {}).get("result", [])
            log.warning("dash0_query_failed", extra={"status": r.status_code, "query": promql})
    except Exception as e:
        log.warning("dash0_query_error", extra={"error": str(e)})
    return []


async def validate_topology_edge(source: str, destination: str) -> bool:
    """Check whether source->destination is a genuine, currently-known edge
    in the topology, before spending any further effort on a diagnosis.

    Without this, a typo'd or fabricated source/destination pair would
    silently produce empty-data PromQL results throughout the whole
    pipeline, which healthy_path_check would then read as "no anomaly" -
    a confidently wrong answer for "this pair doesn't exist" rather than
    an honest rejection. This closes that gap.

    Uses the SAME query as the topology-discovery recording rule
    (k8s/topology-recording-rule.yaml: 2h rolling window of real
    obi_network_flow_bytes traffic), run live rather than through the
    precomputed metric. The recording rule itself is registered and
    enabled in Dash0 but has never actually evaluated (confirmed:
    first-evaluation-at is empty despite ~2h of registration on a 10m
    interval) - an apparent platform-side issue, not a config problem on
    our end (the identical query run directly returns real data, 75
    edges, confirmed live). Logged as a separate open item. This
    live-query fallback is fully correct today; it just can't benefit
    from the "precomputed once, queried cheaply many times" optimization
    the recording rule was meant to provide.

    Fails OPEN on a query/network error (a transient Dash0 hiccup
    shouldn't block a legitimate diagnosis) but fails CLOSED - genuinely
    rejects - when the query succeeds cleanly and simply finds no
    traffic for this pair, which is the real "this edge doesn't exist"
    case this function exists to catch.
    """
    now = time.time()
    q = (
        f'sum(rate(obi_network_flow_bytes{{k8s_src_owner_name="{source}",'
        f'k8s_dst_owner_name="{destination}"}}[2h]))'
    )
    url = f"{DASH0_PROM_URL}/api/v1/query"
    headers = {"Authorization": f"Bearer {DASH0_AUTH_TOKEN}"}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                url, headers=headers,
                params={"query": q, "time": f"{now:.3f}"},
                timeout=15.0,
            )
            if r.status_code != 200:
                log.warning("topology_validation_query_failed", extra={"status": r.status_code})
                return True  # fail open on a query error
            result = r.json().get("data", {}).get("result", [])
            if not result:
                return False
            val = float(result[0]["value"][1])
            return val > 0
    except Exception as e:
        log.warning("topology_validation_error", extra={"error": str(e)})
        return True  # fail open on a query error


async def query_dash0_range(metric_expr: str, win: dict, step: str = "15s") -> list:
    """Query Dash0's Prometheus range-query API, returning a genuine time
    series (not a single scalar). `metric_expr` should be a complete PromQL
    expression with its own small lookback window baked in (e.g.
    "sum(increase(x[30s]))") - that 30s is independent of the overall
    diagnose window (win["range"]), which only controls how far back the
    range query itself starts.

    v1 of the redesign described to Surit: feed real time series to the
    change-point detector below instead of a single aggregated number, so
    /diagnose can tell a brief spike from sustained elevation within the
    window - which a scalar increase() can never distinguish.
    """
    end_epoch = win.get("anchor_epoch") or time.time()
    range_s = int(win["range"].rstrip("s")) if win["range"].endswith("s") else 300
    start_epoch = end_epoch - range_s

    url = f"{DASH0_PROM_URL}/api/v1/query_range"
    headers = {"Authorization": f"Bearer {DASH0_AUTH_TOKEN}"}
    params = {
        "query": metric_expr,
        "start": f"{start_epoch:.3f}",
        "end": f"{end_epoch:.3f}",
        "step": step,
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers, params=params, timeout=15.0)
            if r.status_code == 200:
                data = r.json()
                return data.get("data", {}).get("result", [])
            log.warning("dash0_range_query_failed", extra={"status": r.status_code, "query": metric_expr})
    except Exception as e:
        log.warning("dash0_range_query_error", extra={"error": str(e)})
    return []


def detect_change_point(points: list, baseline_fraction: float = 0.3, z_threshold: float = 3.5) -> dict | None:
    """Lightweight change-point detector using a MAD-based modified z-score
    (Iglewicz & Hoaglin) against a rolling baseline.

    This is a simplified, explainable v1 of the change-point detection
    family used in production multivariate RCA research (e.g. multivariate
    Bayesian Online Change Point Detection in BARO, ACM 2024) - not full
    BOCPD, but the same underlying idea: find WHEN a series' behavior
    shifts and by how much, rather than collapsing the whole window into
    one number.

    Uses MEDIAN + MEDIAN ABSOLUTE DEVIATION for the baseline, not mean/
    stdev. This matters in practice: with a fixed baseline_fraction, if the
    incident starts early in the window, a plain mean/stdev baseline can
    absorb a minority of already-shifted points and get dragged toward
    them, masking the very shift it's supposed to detect (found via a real
    test: 5-point baseline of [0,0,0,65,90] gives mean~31, hiding a real
    0->65+ shift). Median is robust to that contamination as long as the
    majority of the baseline window is still pre-incident.

    `points`: list of [timestamp, value] pairs as returned by Prometheus'
    range-query API (already time-ordered). Returns None if there aren't
    enough points or no crossing is found.
    """
    if not points or len(points) < 4:
        return None

    parsed = []
    for p in points:
        try:
            parsed.append((float(p[0]), float(p[1])))
        except (ValueError, IndexError, TypeError):
            continue
    if len(parsed) < 4:
        return None

    n_baseline = max(2, int(len(parsed) * baseline_fraction))
    baseline_vals = [v for _, v in parsed[:n_baseline]]
    baseline_median = statistics.median(baseline_vals)
    mad = statistics.median([abs(v - baseline_median) for v in baseline_vals])
    # 1.4826 scales MAD to be comparable to a standard deviation for
    # normally-distributed data - the standard constant for this method.
    threshold_delta = max(mad * 1.4826 * z_threshold, 0.01)

    for ts, val in parsed[n_baseline:]:
        delta = val - baseline_median
        if abs(delta) >= threshold_delta:
            pct = (delta / baseline_median * 100) if baseline_median != 0 else None
            return {
                "change_detected": True,
                "change_point_epoch": ts,
                "baseline_mean": round(baseline_median, 3),
                "shifted_value": round(val, 3),
                "direction": "increase" if delta > 0 else "decrease",
                "magnitude_pct": round(pct, 1) if pct is not None else None,
            }
    return None


def correlate_change_points(findings: dict, tolerance_s: float = 20.0) -> list:
    """Group signals whose change points landed within `tolerance_s` seconds
    of at least one other detected change point.

    Each signal is already scoped to a specific service edge via its own
    PromQL query (e.g. gateway->product-svc), so this is the topology-aware
    part of the design: rather than blindly correlating every metric against
    every other metric, we only ask whether signals we ALREADY know are on
    the same architectural edge also moved at the same TIME. A signal that
    shifts far from the rest (or never shifts at all, like
    UNSUPPORTED_L3_PROTOCOL in prior testing) is evidence it's unrelated
    background noise, not part of the incident.
    """
    detected = {
        name: f["change_point_epoch"]
        for name, f in findings.items()
        if isinstance(f, dict) and f.get("change_detected")
    }
    if len(detected) < 2:
        return list(detected.keys())

    times = list(detected.values())
    correlated = [
        name for name, t in detected.items()
        if any(abs(t - other_t) <= tolerance_s for other_name, other_t in detected.items() if other_name != name)
    ]
    return correlated


async def collect_dash0_timeseries_signals(win: dict, source: str, destination: str) -> dict:
    """Collect genuine time-series signals and run change-point detection on
    each. Called ONLY on the fault-diagnosis path, after the (cheap, scalar)
    deterministic gate has already decided something needs investigating -
    this is more expensive (query_range + per-signal detection) so it's
    reserved for windows the gate has flagged as non-healthy.

    Each query uses a fixed 30s sub-window for increase(), independent of
    the overall diagnose window, so change-point resolution stays
    consistent whether the incident window is 1 minute or 15.

    `source`/`destination` are the topology hint from the caller (e.g. APM
    naming which edge it suspects) - no longer hardcoded to gateway/
    product-svc, per the input-contract redesign.
    """
    metric_queries = {
        "hubble_drop_policy_deny": (
            'sum(increase(hubble_drop_total{reason=~"POLICY_DENY|POLICY_DENIED"}[30s]))'
        ),
        "hubble_drop_unsupported_l3": (
            'sum(increase(hubble_drop_total{reason="UNSUPPORTED_L3_PROTOCOL"}[30s]))'
        ),
        "obi_network_flow_bytes": (
            f'sum(increase(obi_network_flow_bytes{{k8s_src_owner_name="{source}",'
            f'k8s_dst_owner_name="{destination}"}}[30s]))'
        ),
        "obi_tcp_failed_connections": (
            f'sum(increase(obi_stat_tcp_failed_connections{{k8s_src_owner_name="{source}"}}[30s]))'
        ),
        "destination_spans": (
            # telemetry_distro_name, not telemetry_sdk_name: confirmed live
            # that OBI's own eBPF spans ALSO report telemetry_sdk_name=
            # "opentelemetry" (mimicking the standard SDK's naming), so that
            # field never actually distinguished OBI from app-SDK spans -
            # it happened to work only because both existed simultaneously
            # before SDK removal. telemetry_distro_name=
            # "opentelemetry-ebpf-instrumentation" is OBI-specific.
            f'sum(increase(dash0_spans_total{{service_name="{destination}",'
            'telemetry_distro_name="opentelemetry-ebpf-instrumentation"}[30s]))'
        ),
        "http_5xx_count": (
            'sum(increase(http_server_request_duration_seconds_count'
            '{http_response_status_code=~"5.."}[30s]))'
        ),
        "cilium_policy_change_event": (
            'sum(increase(dash0_logs_total{service_name="cilium-policy-events"}[30s]))'
        ),
    }

    findings = {}
    for name, expr in metric_queries.items():
        series = await query_dash0_range(expr, win, step="15s")
        points = series[0].get("values", []) if series else []
        cp = detect_change_point(points)
        findings[name] = cp if cp else {"change_detected": False}

    findings["_correlated_signals"] = correlate_change_points(findings)
    findings["backend"] = "dash0"
    findings["window"] = win["label"]
    return findings


async def collect_dash0_signals(win: dict, source: str, destination: str) -> dict:
    """Collect signals from Dash0 Prometheus API.

    `win` is the dict returned by resolve_window(): {range, anchor_epoch, label}.
    Every PromQL expression below carries a `[RANGE]` placeholder (filled with the
    range duration) immediately followed by `[RANGE_END]` (filled with the
    ` @ <epoch>` anchor, or empty in relative mode).

    `source`/`destination` are the topology hint from the caller - no longer
    hardcoded to gateway/product-svc, per the input-contract redesign.
    """
    signals = {}

    # Hubble policy drops. Cilium emits POLICY-based drops under two distinct
    # reason strings depending on enforcement layer (confirmed live in this
    # cluster: POLICY_DENY=6535, POLICY_DENIED=14, occurring simultaneously) -
    # both mean "a policy blocked this packet" so both count toward this signal.
    # UNSUPPORTED_L3_PROTOCOL is tracked separately: it's a datapath protocol
    # support gap, not a policy decision, so it must not be merged into the
    # policy-deny bucket or it would misattribute root cause.
    drops = await query_dash0("increase(hubble_drop_total[RANGE][RANGE_END])", win)
    policy_deny = 0.0
    unsupported_l3 = 0.0
    for d in drops:
        m = d.get("metric", {})
        if not isinstance(m, dict):
            continue
        reason = m.get("reason")
        try:
            v = d.get("value", [0, "0"])
            val = float(v[1]) if isinstance(v, list) else 0.0
        except Exception:
            val = 0.0
        if reason in ("POLICY_DENY", "POLICY_DENIED"):
            policy_deny += val
        elif reason == "UNSUPPORTED_L3_PROTOCOL":
            unsupported_l3 += val
    signals["hubble_drop_total_policy_deny"] = round(policy_deny, 2)
    signals["hubble_drop_total_unsupported_l3_protocol"] = round(unsupported_l3, 2)

    # HTTP 5xx errors
    err = await query_dash0(
        'sum(increase(http_server_request_duration_seconds_count{http_response_status_code=~"5.."}[RANGE][RANGE_END]))',
        win,
    )
    signals["http_5xx_count"] = round(float(err[0]["value"][1]), 2) if err else 0.0

    # HTTP total
    total = await query_dash0(
        "sum(increase(http_server_request_duration_seconds_count[RANGE][RANGE_END]))",
        win,
    )
    http_total = round(float(total[0]["value"][1]), 2) if total else 0.0
    signals["http_total_count"] = http_total
    signals["http_error_rate_pct"] = round(
        (signals["http_5xx_count"] / http_total * 100) if http_total > 0 else 0.0, 1
    )

    # ── Phase 7 additions ───────────────────────────────────────────────

    # OBI NetO11y — network flow bytes (source → destination)
    obi_flow = await query_dash0(
        f'sum(increase(obi_network_flow_bytes{{k8s_src_owner_name="{source}",'
        f'k8s_dst_owner_name="{destination}"}}[RANGE][RANGE_END]))',
        win,
    )
    signals["obi_network_flow_bytes"] = round(float(obi_flow[0]["value"][1]), 2) if obi_flow else 0.0

    # OBI StatsO11y — TCP failed connections from the source
    obi_tcp_failed = await query_dash0(
        f'sum(increase(obi_stat_tcp_failed_connections{{k8s_src_owner_name="{source}"}}[RANGE][RANGE_END]))',
        win,
    )
    signals["obi_tcp_failed_connections"] = round(float(obi_tcp_failed[0]["value"][1]), 2) if obi_tcp_failed else 0.0

    # AppO11y — destination spans (drops to zero during fault). Sourced from
    # OBI's own eBPF traces now (telemetry_distro_name, not telemetry_sdk_name
    # - the latter never actually distinguished OBI spans from app-SDK ones,
    # see collect_dash0_timeseries_signals for detail). Also fixes a stale
    # metric name (dash0_spans -> dash0_spans_total, confirmed empirically
    # earlier this session that the former doesn't exist).
    spans = await query_dash0(
        f'sum(increase(dash0_spans_total{{service_name="{destination}",'
        'telemetry_distro_name="opentelemetry-ebpf-instrumentation"}[RANGE][RANGE_END]))',
        win,
    )
    signals["destination_spans"] = round(float(spans[0]["value"][1]), 2) if spans else 0.0

    signals["backend"] = "dash0"
    signals["window"] = win["label"]
    return signals


async def collect_dynatrace_signals(win: dict, service: str) -> dict:
    """Collect signals from Dynatrace Problems API v2 + entity health.

    Dynatrace Problems API takes absolute `from`/`to` as epoch milliseconds, or a
    relative `from=now-<dur>`. When resolve_window() produced an absolute anchor we
    pass explicit from/to epochs; otherwise we fall back to the Phase 6 relative
    form. (DT backend is out of scope this session — kept wired for parity.)
    """
    signals = {}
    headers = {"Authorization": f"Api-Token {DT_API_TOKEN}"}
    base_url = f"https://{DT_ENV_ID}.live.dynatrace.com"

    anchor = win.get("anchor_epoch")
    if anchor is not None:
        # absolute: derive from/to in epoch milliseconds from the resolved range
        range_s = int(win["range"].rstrip("s")) if win["range"].endswith("s") else 0
        to_ms = int(anchor * 1000)
        from_ms = int((anchor - range_s) * 1000)
        time_params = {"from": str(from_ms), "to": str(to_ms)}
    else:
        time_params = {"from": f"now-{win['range']}"}

    # Query active problems
    problems = []
    davis_root_cause = None
    davis_impact = None
    davis_severity = None
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{base_url}/api/v2/problems",
                headers=headers,
                params={
                    **time_params,
                    "fields": "+evidenceDetails,+impactAnalysis,+rootCauseEntity",
                },
                timeout=10.0
            )
            if r.status_code == 200:
                data = r.json()
                problems = data.get("problems", [])
                signals["davis_active_problems"] = len(problems)

                if problems:
                    # Use the most severe problem
                    p = problems[0]
                    davis_root_cause = p.get("title", "Unknown")
                    davis_severity = p.get("severityLevel", "UNKNOWN")
                    davis_impact = p.get("impactLevel", "UNKNOWN")

                    # Extract evidence
                    evidence = p.get("evidenceDetails", {}).get("details", [])
                    signals["davis_evidence"] = [
                        e.get("displayName", "") for e in evidence[:5]
                    ]
                    signals["davis_root_cause_entity"] = (p.get(
                        "rootCauseEntity") or {}).get("name", "unknown")
                    signals["davis_problem_id"] = p.get("problemId", "")
                    signals["davis_status"] = p.get("status", "")
                else:
                    signals["davis_active_problems"] = 0
                    signals["davis_evidence"] = []
            else:
                log.warning(f"dt_problems_api_failed status={r.status_code}")
                signals["davis_active_problems"] = -1
    except Exception as e:
        log.warning(f"dt_problems_error error={str(e)}")
        signals["davis_active_problems"] = -1

    signals["davis_root_cause"] = davis_root_cause
    signals["davis_severity"] = davis_severity
    signals["davis_impact"] = davis_impact
    signals["backend"] = "dynatrace"
    signals["window"] = win["label"]
    return signals


# ─────────────────────────────────────────────
# LLM RCA ENGINE
# ─────────────────────────────────────────────

SIGNAL_DESCRIPTIONS = {
    "hubble_drop_policy_deny": "packets dropped by a Cilium network policy (L3/L4 access control decision) - SCOPED to this source/destination pair only",
    "hubble_drop_unsupported_l3": "packets dropped because the datapath doesn't support that L3 protocol (e.g. stray IPv6/multicast) - NOT a policy decision, and this signal is CLUSTER-WIDE/unscoped, not specific to this pair. It can be triggered by unrelated traffic anywhere in the cluster, so a correlated-in-time shift here is weaker evidence than a shift in a signal that's actually scoped to this source/destination pair.",
    "obi_network_flow_bytes": "bytes on the wire from source toward destination (eBPF-observed) - SCOPED to this pair only",
    "obi_tcp_failed_connections": "TCP handshakes from the source that failed to complete (eBPF-observed) - SCOPED to this pair only",
    "destination_spans": "application spans emitted by the destination's own eBPF-observed traces - reflects whether requests actually reached and were processed by the destination - SCOPED to this pair only",
    "http_5xx_count": "HTTP 5xx server error responses returned by the source",
    "cilium_policy_change_event": "CHANGE RECORD, not a symptom: a count of Cilium's own audit-trail log lines ('Imported CiliumNetworkPolicy' / 'Deleted CiliumNetworkPolicy'), captured directly from cilium-agent's logs. Every other signal in this analysis is a symptom - a downstream metric shift. This one is the actual event that could have CAUSED those shifts. A change point here landing at the same time as the symptom signals is direct evidence of causation, not just correlation - weight it much more heavily than any symptom-only correlation.",
}



def _format_finding(name: str, f: dict) -> str:
    desc = SIGNAL_DESCRIPTIONS.get(name, name)
    if not f.get("change_detected"):
        return f"- {name} ({desc}): no significant change detected in this window"
    direction = f["direction"]
    mag = f.get("magnitude_pct")
    mag_str = f"{mag:+.0f}%" if mag is not None else "from a zero baseline"
    offset = f.get("_offset_s")
    when = f" at ~t+{offset:.0f}s" if offset is not None else ""
    return (
        f"- {name} ({desc}): shifted from baseline {f['baseline_mean']} to "
        f"{f['shifted_value']} ({direction}, {mag_str}){when}"
    )


def build_prompt(signals: dict, source: str, destination: str, backend: str, findings: dict | None = None) -> str:
    backend_context = ""

    if backend == "dash0" and findings:
        # Compute each change point's offset from the window start, for a
        # human-readable timeline instead of raw epoch seconds.
        window_start = min(
            (f["change_point_epoch"] for f in findings.values()
             if isinstance(f, dict) and f.get("change_detected")),
            default=None,
        )
        lines = []
        for name, f in findings.items():
            if name.startswith("_") or name in ("backend", "window"):
                continue
            if isinstance(f, dict) and f.get("change_detected") and window_start is not None:
                f = dict(f)
                f["_offset_s"] = f["change_point_epoch"] - window_start
            lines.append(_format_finding(name, f))

        correlated = findings.get("_correlated_signals", [])
        correlation_note = (
            f"Signals whose change points landed within ~20s of each other "
            f"(evidence they may share a root cause): {', '.join(correlated) if correlated else 'none - no two signals shifted at the same time'}"
        )

        backend_context = f"""
TIME-SERIES CHANGE-POINT ANALYSIS ({findings.get('window','last 5m')}):
Each signal below was analyzed as a real time series (not a single aggregated
number): a baseline was computed from the early part of the window, and each
series was checked for a statistically significant shift away from that
baseline (3-sigma threshold crossing).

IMPORTANT: one of these signals (cilium_policy_change_event) is a CHANGE
RECORD, not a symptom - it's Cilium's own audit log of policy objects being
created or deleted. Every other signal is a downstream metric that reacts
to something happening; this one IS the something. If its change point lines
up with the symptom signals, that's actual causal evidence, not inference
from correlated symptoms - prefer it over any conclusion built only from
symptoms shifting together.

{chr(10).join(lines)}

{correlation_note}

Signals with NO detected change are evidence AGAINST that layer being
involved. A signal shifting alone, uncorrelated with any other signal, is
weaker evidence than a cluster of signals shifting together.
"""

    elif backend == "dash0":
        # Fallback: no findings supplied, use the plain scalar signals.
        backend_context = f"""
SIGNALS FROM DASH0 PROMETHEUS API ({signals.get('window','last 5m')}), aggregated
over the whole window (no per-signal timing available):
- hubble_drop_total (POLICY_DENY + POLICY_DENIED): {signals.get('hubble_drop_total_policy_deny', 0)}
- hubble_drop_total (UNSUPPORTED_L3_PROTOCOL): {signals.get('hubble_drop_total_unsupported_l3_protocol', 0)}
- HTTP 5xx errors: {signals.get('http_5xx_count', 0)}
- OBI network flow bytes {source}→{destination}: {signals.get('obi_network_flow_bytes', 0)} bytes
- OBI TCP failed connections from {source}: {signals.get('obi_tcp_failed_connections', 0)}
- {destination} spans emitted: {signals.get('destination_spans', 0)}
"""

    elif backend == "dynatrace":
        backend_context = f"""
SIGNALS FROM DYNATRACE DAVIS AI + PROBLEMS API v2 ({signals.get('window','last 5m')}):
- Davis AI active problems: {signals.get('davis_active_problems', 0)}
- Davis AI root cause: {signals.get('davis_root_cause', 'None detected')}
- Davis AI severity: {signals.get('davis_severity', 'UNKNOWN')}
- Davis AI impact level: {signals.get('davis_impact', 'UNKNOWN')}
- Davis AI root cause entity: {signals.get('davis_root_cause_entity', 'unknown')}
- Davis AI evidence: {', '.join(signals.get('davis_evidence', [])) or 'none'}
- Davis AI problem ID: {signals.get('davis_problem_id', 'none')}
"""

    return f"""You are an expert SRE performing differential diagnosis on a Kubernetes
microservices incident. Do not assume the cause in advance - reason from the
evidence to a conclusion, the way a human on-call engineer would.

INCIDENT SCOPE:
- Suspected edge: {source} → {destination} (the topology hint supplied by
  the caller - not assumed, this is the specific pair reported as affected)
- Cilium CNI enforces network policy on this cluster; Hubble provides network
  visibility; eBPF instrumentation (OBI) provides TCP/network metrics and
  traces independent of any application code
- Monitoring backend: {backend.upper()}

{backend_context}

CANDIDATE CATEGORIES TO CONSIDER (not exhaustive, not ranked - weigh each
against the evidence above before concluding):
- Network policy blocking traffic between {source} and {destination}
- A datapath/protocol-level issue unrelated to policy (e.g. unsupported L3 protocol)
- Application-level failure in {source} or {destination} itself (crash, exception, bad deploy) -
  NOTE: this system has no visibility into application code or logic by design
  (network-team scope, zero app-code cooperation) - it can only say whether
  network-observable symptoms of this are present (e.g. destination stops
  producing spans), not confirm an app-level cause directly
- Destination unavailability or slowness
- Resource exhaustion (CPU/memory throttling, connection pool exhaustion)
- DNS or service-discovery failure
- Something not in this list, if the evidence points elsewhere

Provide a root cause analysis in this exact JSON format:
{{
  "root_cause": "one sentence describing the root cause",
  "confidence": "high|medium|low",
  "evidence": ["evidence item 1", "evidence item 2", "evidence item 3"],
  "ruled_out": ["candidate you considered and rejected, with a one-clause reason"],
  "recommendation": "specific kubectl or operational command to fix",
  "severity": "critical|high|medium|low",
  "explanation": "2-3 sentences explaining the causal chain from root cause to symptoms",
  "backend_used": "{backend}"
}}


Return ONLY the JSON object, no other text."""


def healthy_path_check(signals: dict, backend: str) -> dict | None:
    """Deterministic 'no anomaly' gate (Phase 7).

    For the dash0 backend, the two unambiguous fault fingerprints are POLICY_DENY
    drops and OBI TCP failed connections. If BOTH are zero, nothing is being blocked
    and there is no fault to diagnose — so we short-circuit and return a 'healthy'
    result WITHOUT calling Bedrock. This prevents the LLM from pattern-matching a
    confident fault out of all-zero data, and saves the inference round-trip.

    Returns a diagnosis dict if the window is healthy, else None (caller proceeds
    to the LLM). Only gates the dash0 backend; dynatrace relies on Davis problems.
    """
    if backend != "dash0":
        return None

    drops = signals.get("hubble_drop_total_policy_deny", 0) or 0
    tcp_failed = signals.get("obi_tcp_failed_connections", 0) or 0

    if drops == 0 and tcp_failed == 0:
        return {
            "root_cause": "No anomaly detected — network policy enforcement and TCP connections are nominal.",
            "confidence": "high",
            "evidence": [
                f"hubble_drop_total (POLICY_DENY): {drops} — no packets being denied",
                f"OBI TCP failed connections: {tcp_failed} — no failing handshakes",
                f"destination spans emitted: {signals.get('destination_spans', 0)}",
            ],
            "recommendation": "No action required. System is operating normally for this window.",
            "severity": "none",
            "explanation": (
                "Both primary fault fingerprints (Cilium POLICY_DENY drops and OBI TCP "
                "failed connections) are zero for this window, indicating traffic is "
                "flowing without policy blocks. No root-cause analysis is warranted."
            ),
            "backend_used": backend,
        }
    return None


def call_bedrock(prompt: str) -> dict:
    t0 = time.time()
    resp = bedrock.converse(
        modelId=BEDROCK_MODEL,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 512, "temperature": 0.3},
    )
    latency_ms = round((time.time() - t0) * 1000, 1)
    usage = resp.get("usage", {})
    text = resp["output"]["message"]["content"][0]["text"]

    # Parse JSON
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("```")[1]
        if clean.startswith("json"):
            clean = clean[4:]
    diagnosis = json.loads(clean.strip())

    return {
        "diagnosis": diagnosis,
        "model": BEDROCK_MODEL,
        "llm_latency_ms": latency_ms,
        "tokens": {
            "input": usage.get("inputTokens", 0),
            "output": usage.get("outputTokens", 0),
        },
        "cost_usd": round(
            usage.get("inputTokens", 0) * 0.000000035
            + usage.get("outputTokens", 0) * 0.000000140, 8
        ),
    }


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "llm-svc",
        "version": "0.7.0",
        "backends": ["dash0", "dynatrace"],
        "dash0_configured": bool(DASH0_AUTH_TOKEN),
        "dynatrace_configured": bool(DT_API_TOKEN),
    }


@app.get("/recommendations")
async def recommendations(query: str = "best product for developers"):
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{PRODUCT_SVC_URL}/products", timeout=10.0)
        products = r.json()

    log.info(f"recommendations_products_count count={len(products)}")
    product_list = "\n".join(
        [f"- {p['name']} (${p['price']}): {p['description']}" for p in products]
    )
    prompt = f"""You are a product recommendation engine.
Customer query: {query}
Available products:
{product_list}
Recommend the best product and explain why in 2-3 sentences."""

    t0 = time.time()
    resp = bedrock.converse(
        modelId=BEDROCK_MODEL,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 512, "temperature": 0.3},
    )
    latency_ms = round((time.time() - t0) * 1000, 1)
    usage = resp.get("usage", {})
    recommendation_text = resp["output"]["message"]["content"][0]["text"]
    cost_usd = round(
        usage.get("inputTokens", 0) * 0.000000035
        + usage.get("outputTokens", 0) * 0.000000140, 8
    )

    log.info(
        f"recommendations_complete model={BEDROCK_MODEL} "
        f"input_tokens={usage.get('inputTokens', 0)} "
        f"output_tokens={usage.get('outputTokens', 0)} "
        f"latency_ms={latency_ms} cost_usd={cost_usd}"
    )

    return {
        "query": query,
        "recommendation": recommendation_text,
        "model": BEDROCK_MODEL,
        "temperature": 0.3,
        "tokens": {
            "input": usage.get("inputTokens", 0),
            "output": usage.get("outputTokens", 0),
            "total": usage.get("totalTokens", 0),
        },
        "cost_usd": cost_usd,
        "llm_latency_ms": latency_ms,
        "products_considered": len(products),
    }


@app.get("/diagnose")
async def diagnose(
    start: str,
    source: str,
    destination: str,
    end: str | None = None,
    backend: str = "dash0"
):
    """
    Multi-backend AIOps diagnosis endpoint.
    ?backend=dash0     → queries Dash0 Prometheus API (default)
    ?backend=dynatrace → queries Dynatrace Problems API v2 + Davis AI

    Input contract (deliberately prescriptive, not a shot in the dark):
    ?start=2026-08-07T04:00:00Z   → REQUIRED. No relative-window fallback -
                                     a diagnosis without a real incident
                                     start time is a guess, not a finding.
    ?end=2026-08-07T04:05:00Z     → optional, defaults to now (for an
                                     incident that's still ongoing)
    ?source=gateway&destination=product-svc → REQUIRED. The topology hint:
                                     which edge is suspected. No default -
                                     silently defaulting to some assumed
                                     pair is the same "shot in the dark"
                                     problem as a missing start time.
    """
    # Resolve the window first so failures here return 400, not 500
    win = resolve_window(start, end)

    # Topology validation: reject a source/destination pair that has no
    # real, recent traffic between them, rather than silently running the
    # full pipeline on empty data and confidently returning "no anomaly"
    # for what might just be a typo. Only meaningful for dash0 (the check
    # itself queries obi_network_flow_bytes).
    if backend == "dash0":
        edge_exists = await validate_topology_edge(source, destination)
        if not edge_exists:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"No known traffic between source='{source}' and "
                    f"destination='{destination}' in the last 2h. This pair "
                    f"may not be a real edge in the topology, or the names "
                    f"may be misspelled - check exact k8s owner names "
                    f"(e.g. Deployment name), not pod names."
                ),
            )

    t0 = time.time()

    # Collect signals from selected backend
    if backend == "dynatrace":
        if not DT_API_TOKEN:
            raise HTTPException(status_code=400, detail="DT_API_TOKEN not configured")
        signals = await collect_dynatrace_signals(win, source)
    elif backend == "dash0":
        if not DASH0_AUTH_TOKEN:
            raise HTTPException(status_code=400, detail="DASH0_AUTH_TOKEN not configured")
        signals = await collect_dash0_signals(win, source, destination)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown backend: {backend}. Use dash0 or dynatrace")

    # Deterministic healthy-path gate: if no fault fingerprints are present,
    # return a 'no anomaly' result without spending an LLM call (Phase 7).
    healthy = healthy_path_check(signals, backend)
    if healthy is not None:
        total_ms = round((time.time() - t0) * 1000, 1)
        log.info(
            f"diagnose_complete backend={backend} window={win['label']} "
            f"source={source} destination={destination} "
            f"root_cause={healthy['root_cause']} healthy_path=true total_ms={total_ms} "
            f"hubble_drop_total_policy_deny={signals.get('hubble_drop_total_policy_deny', 0)} "
            f"obi_tcp_failed_connections={signals.get('obi_tcp_failed_connections', 0)} "
            f"destination_spans={signals.get('destination_spans', 0)}"
        )
        return {
            "backend": backend,
            "window": win["label"],
            "window_range": win["range"],
            "window_absolute": win["anchor_epoch"] is not None,
            "source": source,
            "destination": destination,
            "signals": signals,
            "diagnosis": healthy,
            "model": "none (deterministic healthy-path)",
            "llm_latency_ms": 0.0,
            "total_ms": total_ms,
            "tokens": {"input": 0, "output": 0},
            "cost_usd": 0.0,
        }

    # Gate has determined this window is non-healthy - now do the more
    # expensive time-series collection + change-point detection, only
    # reached when it's actually needed.
    findings = None
    if backend == "dash0":
        findings = await collect_dash0_timeseries_signals(win, source, destination)
        log.info(f"diagnose_correlated_signals signals={','.join(findings.get('_correlated_signals', []))}")

    # Build prompt and call Bedrock
    prompt = build_prompt(signals, source, destination, backend, findings=findings)
    result = call_bedrock(prompt)

    total_ms = round((time.time() - t0) * 1000, 1)

    if backend == "dash0":
        log.info(
            f"diagnose_signals hubble_drop_total_policy_deny={signals.get('hubble_drop_total_policy_deny', 0)} "
            f"http_error_rate_pct={signals.get('http_error_rate_pct', 0)} "
            f"obi_network_flow_bytes={signals.get('obi_network_flow_bytes', 0)} "
            f"obi_tcp_failed_connections={signals.get('obi_tcp_failed_connections', 0)} "
            f"destination_spans={signals.get('destination_spans', 0)}"
        )
    elif backend == "dynatrace":
        log.info(
            f"diagnose_signals davis_active_problems={signals.get('davis_active_problems', 0)} "
            f"davis_severity={signals.get('davis_severity', '') or ''}"
        )

    log.info(
        f"diagnose_complete backend={backend} window={win['label']} "
        f"source={source} destination={destination} "
        f"root_cause={result['diagnosis'].get('root_cause','')} "
        f"confidence={result['diagnosis'].get('confidence','')} "
        f"total_ms={total_ms}"
    )

    return {
        "backend": backend,
        "window": win["label"],
        "window_range": win["range"],
        "window_absolute": win["anchor_epoch"] is not None,
        "source": source,
        "destination": destination,
        "signals": signals,
        "timeseries_findings": findings,
        "diagnosis": result["diagnosis"],
        "model": result["model"],
        "llm_latency_ms": result["llm_latency_ms"],
        "total_ms": total_ms,
        "tokens": result["tokens"],
        "cost_usd": result["cost_usd"],
    }
