"""
llm-svc Phase 4 - Uses Bedrock Converse API (works with all models)
"""
import json
import logging
import os
import time

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

resource = Resource.create({"service.name": "llm-svc", "service.version": "1.0.0"})
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

PRODUCT_SVC = os.getenv("PRODUCT_SVC_URL",  "http://product-svc:8001")
AWS_REGION   = os.getenv("AWS_REGION",       "us-east-2")
MODEL_ID     = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-micro-v1:0")
TEMPERATURE  = float(os.getenv("LLM_TEMPERATURE", "0.3"))
MAX_TOKENS   = int(os.getenv("LLM_MAX_TOKENS",    "256"))

bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
app = FastAPI(title="llm-svc")
FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()


def call_bedrock_converse(prompt: str) -> dict:
    """Use Bedrock Converse API — works with Nova, Titan, Claude, Llama."""
    t0 = time.time()
    response = bedrock.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={
            "maxTokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
        },
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


# Cost map per 1000 tokens (June 2026 Bedrock pricing)
COST_MAP = {
    "amazon.nova-micro-v1:0":            (0.000035,  0.00014),
    "amazon.nova-lite-v1:0":             (0.00006,   0.00024),
    "us.anthropic.claude-3-haiku-20240307-v1:0": (0.00025, 0.00125),
    "anthropic.claude-3-haiku-20240307-v1:0":    (0.00025, 0.00125),
}


def calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    in_rate, out_rate = COST_MAP.get(model, (0.0001, 0.0003))
    return round((input_tokens * in_rate + output_tokens * out_rate) / 1000, 8)


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
            result = call_bedrock_converse(prompt)
            cost_usd = calc_cost(MODEL_ID, result["input_tokens"], result["output_tokens"])

            span.set_attribute("gen_ai.usage.input_tokens",     result["input_tokens"])
            span.set_attribute("gen_ai.usage.output_tokens",    result["output_tokens"])
            span.set_attribute("gen_ai.response.finish_reason", result["stop_reason"])
            span.set_attribute("llm.latency_ms",                result["latency_ms"])
            span.set_attribute("llm.cost_usd",                  cost_usd)
            span.set_status(Status(StatusCode.OK))

            log.info("llm_call_complete",
                model=MODEL_ID, temperature=TEMPERATURE,
                input_tokens=result["input_tokens"],
                output_tokens=result["output_tokens"],
                latency_ms=result["latency_ms"],
                cost_usd=cost_usd,
            )
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            log.error("llm_call_failed", error=str(exc))
            raise HTTPException(502, f"Bedrock error: {exc}")

    return {
        "query":            query,
        "recommendation":   result["text"],
        "model":            MODEL_ID,
        "temperature":      TEMPERATURE,
        "tokens": {
            "input":  result["input_tokens"],
            "output": result["output_tokens"],
            "total":  result["input_tokens"] + result["output_tokens"],
        },
        "cost_usd":             cost_usd,
        "llm_latency_ms":       result["latency_ms"],
        "products_considered":  len(products),
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "llm-svc"}
