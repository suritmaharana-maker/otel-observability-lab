"""
llm-svc Phase 6 — Multi-backend /diagnose
Supports: ?backend=dash0 (default) | dynatrace | datadog (stub)
"""
import os, json, logging, asyncio, time
import boto3
import httpx
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

log = logging.getLogger("llm-svc")
logging.basicConfig(level=logging.INFO)

OTEL_ENDPOINT   = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otelcol.observability.svc.cluster.local:4317")
DASH0_AUTH_TOKEN = os.getenv("DASH0_AUTH_TOKEN", "")
DASH0_PROM_URL  = os.getenv("DASH0_PROMETHEUS_URL", "https://api.us-west-2.aws.dash0.com/api/prometheus")
DT_ENV_ID       = os.getenv("DT_ENVIRONMENT_ID", "yta61562")
DT_API_TOKEN    = os.getenv("DT_API_TOKEN", "")
BEDROCK_MODEL   = os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-micro-v1:0")
BEDROCK_REGION  = os.getenv("AWS_DEFAULT_REGION", "us-east-2")

resource = Resource.create({
    "service.name": "llm-svc",
    "service.version": "0.6.0",
    "deployment.environment": "lab",
})
provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True)))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("llm-svc")
HTTPXClientInstrumentor().instrument()
app = FastAPI(title="OTel Lab — LLM Service", version="0.6.0")
FastAPIInstrumentor.instrument_app(app)

PRODUCT_SVC_URL = os.getenv("PRODUCT_SVC_URL", "http://product-svc:8001")
bedrock = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)


# ─────────────────────────────────────────────
# SIGNAL BACKENDS
# ─────────────────────────────────────────────

async def query_dash0(promql: str, window: str = "5m") -> list:
    """Query Dash0 Prometheus API."""
    url = f"{DASH0_PROM_URL}/api/v1/query"
    headers = {"Authorization": f"Bearer {DASH0_AUTH_TOKEN}"}
    params = {"query": promql}
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


async def collect_dash0_signals(window: str, service: str) -> dict:
    """Collect signals from Dash0 Prometheus API."""
    signals = {}

    # Hubble policy drops
    drops = await query_dash0(f"increase(hubble_drop_total[{window}])")
    policy_deny = 0.0
    for d in drops:
        m = d.get("metric", {})
        if isinstance(m, dict) and m.get("reason") == "POLICY_DENY":
            try:
                v = d.get("value", [0, "0"])
                policy_deny += float(v[1]) if isinstance(v, list) else 0.0
            except Exception:
                pass
    signals["hubble_drop_total_policy_deny"] = round(policy_deny, 2)

    # HTTP 5xx errors
    err = await query_dash0(
        f'sum(increase(http_server_request_duration_seconds_count{{http_response_status_code=~"5.."}}[{window}]))'
    )
    signals["http_5xx_count"] = round(float(err[0]["value"][1]), 2) if err else 0.0

    # HTTP total
    total = await query_dash0(
        f"sum(increase(http_server_request_duration_seconds_count[{window}]))"
    )
    http_total = round(float(total[0]["value"][1]), 2) if total else 0.0
    signals["http_total_count"] = http_total
    signals["http_error_rate_pct"] = round(
        (signals["http_5xx_count"] / http_total * 100) if http_total > 0 else 0.0, 1
    )

    # Network flow bytes
    flow = await query_dash0(
        f'sum(increase(beyla_network_flow_bytes{{k8s_src_owner_name="{service}"}}[{window}]))'
    )
    signals["network_flow_bytes"] = round(float(flow[0]["value"][1]), 2) if flow else 0.0

    signals["backend"] = "dash0"
    signals["window"] = window
    return signals


async def collect_dynatrace_signals(window: str, service: str) -> dict:
    """Collect signals from Dynatrace Problems API v2 + entity health."""
    signals = {}
    headers = {"Authorization": f"Api-Token {DT_API_TOKEN}"}
    base_url = f"https://{DT_ENV_ID}.live.dynatrace.com"

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
                    "from": f"now-{window}",
                    
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
    signals["window"] = window
    return signals


# ─────────────────────────────────────────────
# LLM RCA ENGINE
# ─────────────────────────────────────────────

def build_prompt(signals: dict, service: str, backend: str) -> str:
    backend_context = ""

    if backend == "dash0":
        backend_context = f"""
SIGNALS FROM DASH0 PROMETHEUS API (last {signals.get('window','5m')}):
- hubble_drop_total (POLICY_DENY): {signals.get('hubble_drop_total_policy_deny', 0)} drops
- HTTP 5xx errors: {signals.get('http_5xx_count', 0)}
- HTTP total requests: {signals.get('http_total_count', 0)}
- HTTP error rate: {signals.get('http_error_rate_pct', 0)}%
- Network flow bytes from {service}: {signals.get('network_flow_bytes', 0)} bytes
"""

    elif backend == "dynatrace":
        backend_context = f"""
SIGNALS FROM DYNATRACE DAVIS AI + PROBLEMS API v2 (last {signals.get('window','5m')}):
- Davis AI active problems: {signals.get('davis_active_problems', 0)}
- Davis AI root cause: {signals.get('davis_root_cause', 'None detected')}
- Davis AI severity: {signals.get('davis_severity', 'UNKNOWN')}
- Davis AI impact level: {signals.get('davis_impact', 'UNKNOWN')}
- Davis AI root cause entity: {signals.get('davis_root_cause_entity', 'unknown')}
- Davis AI evidence: {', '.join(signals.get('davis_evidence', [])) or 'none'}
- Davis AI problem ID: {signals.get('davis_problem_id', 'none')}
"""

    return f"""You are an expert SRE analyzing a Kubernetes microservices incident.

ARCHITECTURE:
- gateway (port 8000) → product-svc (port 8001) → postgres (port 5432)
- gateway (port 8000) → llm-svc (port 8002) → AWS Bedrock
- Cilium CNI enforces CiliumNetworkPolicy — TCP POLICY_DENY means a policy is blocking traffic
- All services run on AWS EKS with Hubble network visibility
- Monitoring backend: {backend.upper()}

{backend_context}

Based on these signals, provide a root cause analysis in this exact JSON format:
{{
  "root_cause": "one sentence describing the root cause",
  "confidence": "high|medium|low",
  "evidence": ["evidence item 1", "evidence item 2", "evidence item 3"],
  "recommendation": "specific kubectl or operational command to fix",
  "severity": "critical|high|medium|low",
  "explanation": "2-3 sentences explaining the causal chain from root cause to symptoms",
  "backend_used": "{backend}"
}}

Return ONLY the JSON object, no other text."""


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
        "version": "0.6.0",
        "backends": ["dash0", "dynatrace"],
        "dash0_configured": bool(DASH0_AUTH_TOKEN),
        "dynatrace_configured": bool(DT_API_TOKEN),
    }


@app.get("/recommendations")
async def recommendations(query: str = "best product for developers"):
    with tracer.start_as_current_span("llm.recommendations") as span:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{PRODUCT_SVC_URL}/products", timeout=10.0)
            products = r.json()

        span.set_attribute("products.count", len(products))
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

        span.set_attribute("gen_ai.system", "aws.bedrock")
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.request.model", BEDROCK_MODEL)
        span.set_attribute("gen_ai.request.temperature", 0.3)
        span.set_attribute("gen_ai.usage.input_tokens", usage.get("inputTokens", 0))
        span.set_attribute("gen_ai.usage.output_tokens", usage.get("outputTokens", 0))
        span.set_attribute("llm.latency_ms", latency_ms)
        span.set_attribute("llm.cost_usd", cost_usd)

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
    window: str = "5m",
    service: str = "gateway",
    backend: str = "dash0"
):
    """
    Multi-backend AIOps diagnosis endpoint.
    ?backend=dash0     → queries Dash0 Prometheus API (default)
    ?backend=dynatrace → queries Dynatrace Problems API v2 + Davis AI
    """
    with tracer.start_as_current_span("diagnose.rca") as span:
        span.set_attribute("diagnose.backend", backend)
        span.set_attribute("diagnose.window", window)
        span.set_attribute("diagnose.service", service)

        t0 = time.time()

        # Collect signals from selected backend
        if backend == "dynatrace":
            if not DT_API_TOKEN:
                raise HTTPException(status_code=400, detail="DT_API_TOKEN not configured")
            signals = await collect_dynatrace_signals(window, service)
        elif backend == "dash0":
            if not DASH0_AUTH_TOKEN:
                raise HTTPException(status_code=400, detail="DASH0_AUTH_TOKEN not configured")
            signals = await collect_dash0_signals(window, service)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown backend: {backend}. Use dash0 or dynatrace")

        # Build prompt and call Bedrock
        prompt = build_prompt(signals, service, backend)
        result = call_bedrock(prompt)

        total_ms = round((time.time() - t0) * 1000, 1)

        # OTel attributes
        span.set_attribute("diagnose.root_cause", result["diagnosis"].get("root_cause", ""))
        span.set_attribute("diagnose.confidence", result["diagnosis"].get("confidence", ""))
        span.set_attribute("diagnose.severity", result["diagnosis"].get("severity", ""))
        span.set_attribute("diagnose.total_ms", total_ms)

        if backend == "dash0":
            span.set_attribute("diagnose.hubble_drop_total_policy_deny", signals.get("hubble_drop_total_policy_deny", 0))
            span.set_attribute("diagnose.http_error_rate_pct", signals.get("http_error_rate_pct", 0))
        elif backend == "dynatrace":
            span.set_attribute("diagnose.davis_active_problems", signals.get("davis_active_problems", 0))
            span.set_attribute("diagnose.davis_severity", signals.get("davis_severity", "") or "")

        log.info(
            f"diagnose_complete backend={backend} "
            f"root_cause={result['diagnosis'].get('root_cause','')} "
            f"confidence={result['diagnosis'].get('confidence','')} "
            f"total_ms={total_ms}"
        )

        return {
            "backend": backend,
            "window": window,
            "service": service,
            "signals": signals,
            "diagnosis": result["diagnosis"],
            "model": result["model"],
            "llm_latency_ms": result["llm_latency_ms"],
            "total_ms": total_ms,
            "tokens": result["tokens"],
            "cost_usd": result["cost_usd"],
        }
