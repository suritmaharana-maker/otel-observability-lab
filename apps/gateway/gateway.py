import logging
import os

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

resource = Resource.create({"service.name": "gateway", "service.version": "1.0.0"})
provider = TracerProvider(resource=resource)
otlp = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otelcol.observability.svc.cluster.local:4317")
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp, insecure=True)))
trace.set_tracer_provider(provider)

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

PRODUCT_SVC = os.getenv("PRODUCT_SVC_URL", "http://product-svc:8001")
LLM_SVC = os.getenv("LLM_SVC_URL", "http://llm-svc:8002")

app = FastAPI(title="gateway")
FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()


@app.get("/products")
async def get_products():
    log.info("listing_products")
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{PRODUCT_SVC}/products")
        if r.status_code != 200:
            raise HTTPException(502, "product-svc error")
    products = r.json()
    log.info("products_returned", count=len(products))
    return products


@app.get("/recommendations")
async def get_recommendations(query: str = "best product for developers"):
    log.info("recommendation_request", query=query)
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{LLM_SVC}/recommendations", params={"query": query})
        if r.status_code != 200:
            raise HTTPException(502, "llm-svc error")
    result = r.json()
    log.info(
        "recommendation_complete",
        model=result.get("model"),
        input_tokens=result.get("tokens", {}).get("input"),
        output_tokens=result.get("tokens", {}).get("output"),
        cost_usd=result.get("cost_usd"),
    )
    return result


@app.get("/health")
async def health():
    return {"status": "ok", "service": "gateway"}
