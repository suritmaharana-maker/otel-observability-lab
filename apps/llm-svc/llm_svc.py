"""
llm-svc Phase 5 - LLM-powered Root Cause Analysis
Extends Phase 4 with /diagnose endpoint that:
1. Queries Dash0 Prometheus API for real signal data
2. Sends signals to Bedrock for root cause analysis
3. Returns structured diagnosis with evidence and recommendation
"""
import json
import logging
import os
import time
from datetime import datetime, timezone

import boto3
import httpx
import structlog
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode

# ── OTel setup ────────────────────────────────────────────────────────────────
resource = Resource.create({"service.name": "llm-svc", "service.version": "2.0.0"})
provider = TracerProvider(resource=resource)
otlp = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otelcol.observability.svc.cluster.local:4317")
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp, insecure=True)))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("llm-svc")

logging.basicConfig(level=logging.INFO)
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
log = structlog.get_logger()

# ── Config ────────────────────────────────────────────────────────────────────
PRODUCT_SVC      = os.getenv("PRODUCT_SVC_URL",       "http://product-svc:8001")
AWS_REGION       = os.getenv("AWS_REGION",             "us-east-2")
MODEL_ID         = os.getenv("BEDROCK_MODEL_ID",       "us.amazon.nova-micro-v1:0")
TEMPERATURE      = float(os.getenv("LLM_TEMPERATURE",  "0.3"))
MAX_TOKENS       = int(os.getenv("LLM_MAX_TOKENS",     "512"))
DASH0_TOKEN      = os.getenv("DASH0_AUTH_TOKEN",       "")
DASH0_PROM_URL   = os.getenv("DASH0_PROMETHEUS_URL",   "https://api.us-west-2.aws.dash0.com/api/prometheus")

COST_MAP = {
    "us.amazon.nova-micro-v1:0": (0.000035, 0.00014),
    "us.anthropic.claude-3-haiku-20240307-v1:0": (0.00025, 0.00125),
}

bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
app = FastAPI(title="llm-svc", version="2.0.0")
FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()


# ── Bedrock helper ────────────────────────────────────────────────────────────
def call_bedrock(prompt: str, max_tokens: int = None) -> dict:
    t0 = time.time()
    response = bedrock.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": max_tokens or MAX_TOKENS, "temperature": TEMPERATURE},
    )
    latency_ms = round((time.time() - t0) * 1000, 1)
    text = response["output"]["message"]["content"][0]["text"]
    usage = response.get("usage", {})
    return {
        "text":          text,
        "input_tokens":  usage.get("inputTokens",  0),
        "output_tokens": usage.get("outputTokens", 0),
        "stop_reason":   response.get("stopReason", "end_turn"),
        "latency_ms":    latency_ms,
    }


def calc_cost(input_tokens: int, output_tokens: int) -> float:
    in_rate, out_rate = COST_MAP.get(MODEL_ID, (0.0001, 0.0003))
    return round((input_tokens * in_rate + output_tokens * out_rate) / 1000, 8)


# ── Dash0 Prometheus helper ───────────────────────────────────────────────────
async def query_dash0(promql: str, window: str = "5m") -> list:
    """Query Dash0 Prometheus API. Returns list of {metric, value} dicts."""
    if not DASH0_TOKEN:
        return []
    url = f"{DASH0_PROM_URL}/api/v1/query"
    headers = {"Authorization": f"Bearer {DASH0_TOKEN}"}
    params = {"query": promql}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(url, headers=headers, params=params)
            if r.status_code != 200:
                log.warning("dash0_query_failed", status=r.status_code, query=promql)
                return []
            data = r.json()
            return data.get("data", {}).get("result", [])
        except Exception as e:
            log.warning("dash0_query_error", error=str(e), query=promql)
            return []


# ── /recommendations endpoint (Phase 4) ──────────────────────────────────────
@app.get("/recommendations")
async def get_recommendations(query: str = "best product"):
    log.info("recommendation_request", query=query)

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{PRODUCT_SVC}/products")
        if r.status_code != 200:
            raise HTTPException(502, "product-svc unavailable")
    products = r.json()

    catalog = "\n".join(
        f"- {p['name']} (${p['price']:.2f}): {p.get('description', '')}"
        for p in products
    )
    prompt = (
        f"You are a product advisor. A customer asks: '{query}'\n\n"
        f"Available products:\n{catalog}\n\n"
        f"Recommend the single best product and explain why in 2-3 sentences."
    )

    with tracer.start_as_current_span("bedrock.converse", kind=SpanKind.CLIENT) as span:
        span.set_attribute("gen_ai.system",              "aws.bedrock")
        span.set_attribute("gen_ai.operation.name",      "chat")
        span.set_attribute("gen_ai.request.model",       MODEL_ID)
        span.set_attribute("gen_ai.request.temperature", TEMPERATURE)
        span.set_attribute("gen_ai.request.max_tokens",  MAX_TOKENS)
        span.set_attribute("llm.customer_query",         query)
        span.set_attribute("llm.products_in_catalog",    len(products))
        try:
            result = call_bedrock(prompt)
            cost_usd = calc_cost(result["input_tokens"], result["output_tokens"])
            span.set_attribute("gen_ai.usage.input_tokens",     result["input_tokens"])
            span.set_attribute("gen_ai.usage.output_tokens",    result["output_tokens"])
            span.set_attribute("gen_ai.response.finish_reason", result["stop_reason"])
            span.set_attribute("llm.latency_ms",                result["latency_ms"])
            span.set_attribute("llm.cost_usd",                  cost_usd)
            span.set_status(Status(StatusCode.OK))
            log.info("llm_call_complete", model=MODEL_ID,
                     input_tokens=result["input_tokens"],
                     output_tokens=result["output_tokens"],
                     cost_usd=cost_usd)
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            log.error("llm_call_failed", error=str(exc))
            raise HTTPException(502, f"Bedrock error: {exc}")

    return {
        "query": query, "recommendation": result["text"],
        "model": MODEL_ID, "temperature": TEMPERATURE,
        "tokens": {"input": result["input_tokens"], "output": result["output_tokens"],
                   "total": result["input_tokens"] + result["output_tokens"]},
        "cost_usd": cost_usd, "llm_latency_ms": result["latency_ms"],
        "products_considered": len(products),
    }


# ── /diagnose endpoint (Phase 5) ─────────────────────────────────────────────
@app.get("/diagnose")
async def diagnose(window: str = "5m", service: str = "gateway"):
    """
    LLM-powered root cause analysis.
    Queries Dash0 Prometheus API for real signal data,
    then asks Bedrock to identify root cause and recommend action.
    """
    log.info("diagnose_request", window=window, service=service)
    diagnosis_start = time.time()

    with tracer.start_as_current_span("diagnose.rca", kind=SpanKind.SERVER) as span:
        span.set_attribute("diagnose.window",  window)
        span.set_attribute("diagnose.service", service)
        span.set_attribute("gen_ai.system",    "aws.bedrock")
        span.set_attribute("gen_ai.request.model", MODEL_ID)

        # ── Step 1: Gather signals from Dash0 ────────────────────────────────
        signals = {}

        # Network drops (Hubble)
        drops = await query_dash0(f"increase(hubble_drop_total[{window}])")
        policy_deny = 0.0
        for d in drops:
            m = d.get("metric", {})
            if isinstance(m, dict) and m.get("reason") == "POLICY_DENY":
                try:
                    policy_deny = float(d["value"][1]) if isinstance(d["value"], list) else float(str(d["value"]).split()[-1])
                except Exception:
                    pass
        signals["hubble_policy_deny_drops"] = round(policy_deny, 2)

        # HTTP error rate (Beyla RED metrics)
        err_results = await query_dash0(
            f'sum(increase(http_server_request_duration_seconds_count{{http_response_status_code=~"5.."}}[{window}]))'
        )
        error_count = 0.0
        if err_results:
            try:
                v = err_results[0].get("value", [0, "0"])
                error_count = float(v[1] if isinstance(v, list) else str(v).split()[-1])
            except Exception:
                pass
        signals["http_5xx_count"] = round(error_count, 2)

        # Total request count
        total_results = await query_dash0(
            f'sum(increase(http_server_request_duration_seconds_count[{window}]))'
        )
        total_count = 0.0
        if total_results:
            try:
                v = total_results[0].get("value", [0, "0"])
                total_count = float(v[1] if isinstance(v, list) else str(v).split()[-1])
            except Exception:
                pass
        signals["http_total_count"] = round(total_count, 2)
        signals["http_error_rate_pct"] = round(
            (error_count / total_count * 100) if total_count > 0 else 0.0, 1
        )

        # Network flow bytes
        flow_results = await query_dash0(
            f'sum(increase(beyla_network_flow_bytes{{k8s_src_owner_name="{service}"}}[{window}]))'
        )
        flow_bytes = 0.0
        if flow_results:
            try:
                v = flow_results[0].get("value", [0, "0"])
                flow_bytes = float(v[1] if isinstance(v, list) else str(v).split()[-1])
            except Exception:
                pass
        signals["network_flow_bytes"] = round(flow_bytes, 0)

        span.set_attribute("diagnose.policy_deny_drops", signals["hubble_policy_deny_drops"])
        span.set_attribute("diagnose.http_error_rate_pct", signals["http_error_rate_pct"])
        span.set_attribute("diagnose.http_5xx_count", signals["http_5xx_count"])

        log.info("signals_gathered", **signals)

        # ── Step 2: Build diagnosis prompt ───────────────────────────────────
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        prompt = f"""You are an expert SRE diagnosing a production incident in a Kubernetes microservices environment.

Current time: {now_utc}
Analysis window: last {window}
Target service: {service}

OBSERVED SIGNALS:
- Hubble network drops (TCP POLICY_DENY): {signals['hubble_policy_deny_drops']} drops
- HTTP 5xx error count: {signals['http_5xx_count']} errors
- HTTP total requests: {signals['http_total_count']}
- HTTP error rate: {signals['http_error_rate_pct']}%
- Network flow bytes from {service}: {signals['network_flow_bytes']} bytes

SYSTEM CONTEXT:
- gateway (node C) calls product-svc:8001 (node B) via HTTP — cross-node
- product-svc calls postgres:5432 (node C)
- gateway calls llm-svc:8002 (node B) for recommendations
- Cilium CNI enforces CiliumNetworkPolicy — TCP POLICY_DENY means a policy is blocking traffic
- Normal error rate is < 1%, normal latency is 70-150ms

Based on the signals above, provide a structured diagnosis:
1. ROOT_CAUSE: What is most likely causing this? (one sentence)
2. CONFIDENCE: high/medium/low — based on signal clarity
3. EVIDENCE: List 2-3 specific signals that support your diagnosis
4. RECOMMENDATION: Exact kubectl command or action to fix it
5. SEVERITY: critical/high/medium/low

Respond in this exact JSON format:
{{
  "root_cause": "...",
  "confidence": "high|medium|low",
  "evidence": ["signal 1", "signal 2", "signal 3"],
  "recommendation": "kubectl or other exact command",
  "severity": "critical|high|medium|low",
  "explanation": "2-3 sentence technical explanation"
}}"""

        # ── Step 3: Call Bedrock ──────────────────────────────────────────────
        try:
            result = call_bedrock(prompt, max_tokens=512)
            cost_usd = calc_cost(result["input_tokens"], result["output_tokens"])

            span.set_attribute("gen_ai.usage.input_tokens",     result["input_tokens"])
            span.set_attribute("gen_ai.usage.output_tokens",    result["output_tokens"])
            span.set_attribute("llm.latency_ms",                result["latency_ms"])
            span.set_attribute("llm.cost_usd",                  cost_usd)

            # Parse JSON response from LLM
            text = result["text"].strip()
            # Strip markdown code blocks if present
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            try:
                diagnosis = json.loads(text.strip())
            except json.JSONDecodeError:
                diagnosis = {
                    "root_cause": text,
                    "confidence": "low",
                    "evidence": [],
                    "recommendation": "Manual investigation required",
                    "severity": "unknown",
                    "explanation": "LLM response was not in expected JSON format",
                }

            span.set_attribute("diagnose.root_cause",  diagnosis.get("root_cause", ""))
            span.set_attribute("diagnose.confidence",  diagnosis.get("confidence", ""))
            span.set_attribute("diagnose.severity",    diagnosis.get("severity", ""))
            span.set_status(Status(StatusCode.OK))

            log.info("diagnosis_complete",
                     root_cause=diagnosis.get("root_cause"),
                     confidence=diagnosis.get("confidence"),
                     severity=diagnosis.get("severity"),
                     input_tokens=result["input_tokens"],
                     cost_usd=cost_usd)

        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            log.error("diagnosis_failed", error=str(exc))
            raise HTTPException(502, f"Diagnosis error: {exc}")

        total_ms = round((time.time() - diagnosis_start) * 1000, 1)

        return {
            "diagnosis":      diagnosis,
            "signals":        signals,
            "window":         window,
            "service":        service,
            "model":          MODEL_ID,
            "analysis_time_ms": total_ms,
            "tokens": {
                "input":  result["input_tokens"],
                "output": result["output_tokens"],
            },
            "cost_usd": cost_usd,
            "timestamp": now_utc,
        }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "llm-svc", "version": "2.0.0",
            "dash0_connected": bool(DASH0_TOKEN)}
