"""
API Gateway - Phase 2 - OTel SDK instrumented — MELT: Traces + Logs
"""
import os
import logging
import structlog
from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

import httpx
from fastapi import FastAPI, HTTPException

OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otelcol.observability.svc.cluster.local:4317")

resource = Resource.create({
    "service.name": "gateway",
    "service.version": "0.2.0",
    "deployment.environment": "lab",
    "cloud.provider": "aws",
    "cloud.region": "us-east-2",
})

# ── Traces ────────────────────────────────────────────────────────────────────
provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True)))
trace.set_tracer_provider(provider)
set_global_textmap(TraceContextTextMapPropagator())

# ── Logs ──────────────────────────────────────────────────────────────────────
logger_provider = LoggerProvider(resource=resource)
logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=OTEL_ENDPOINT, insecure=True)))
set_logger_provider(logger_provider)

# Attach OTel handler to root logger — injects trace_id into every log record
otel_handler = LoggingHandler(level=logging.DEBUG, logger_provider=logger_provider)
logging.getLogger().addHandler(otel_handler)
logging.getLogger().setLevel(logging.INFO)

# Inject trace_id/span_id into Python log records automatically
LoggingInstrumentor().instrument(set_logging_format=True)

# structlog configured to emit JSON with trace context
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

# ── Instrumentation ───────────────────────────────────────────────────────────
HTTPXClientInstrumentor().instrument()

app = FastAPI(title="OTel Lab - API Gateway", version="0.2.0")
FastAPIInstrumentor.instrument_app(app)

logger = structlog.get_logger("gateway")

PRODUCT_SVC_URL = os.getenv("PRODUCT_SVC_URL", "http://product-svc:8001")
LLM_SVC_URL = os.getenv("LLM_SVC_URL", "http://llm-svc:8002")

@app.get("/health")
async def health():
    logger.info("health_check", status="ok")
    return {"status": "ok", "service": "gateway", "version": "0.2.0"}

@app.get("/products")
async def list_products():
    logger.info("listing_products")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{PRODUCT_SVC_URL}/products", timeout=5.0)
            response.raise_for_status()
            data = response.json()
            logger.info("products_returned", count=len(data))
            return data
        except httpx.HTTPError as e:
            logger.error("product_svc_error", error=str(e))
            raise HTTPException(status_code=502, detail=f"product-svc error: {str(e)}")

@app.get("/products/{product_id}")
async def get_product(product_id: int):
    logger.info("get_product", product_id=product_id)
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{PRODUCT_SVC_URL}/products/{product_id}", timeout=5.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error("product_svc_error", product_id=product_id, error=str(e))
            raise HTTPException(status_code=502, detail=f"product-svc error: {str(e)}")

@app.post("/recommend")
async def recommend(payload: dict):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(f"{LLM_SVC_URL}/recommend", json=payload, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"llm-svc error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)