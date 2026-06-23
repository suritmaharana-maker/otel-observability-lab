"""
API Gateway - Phase 7 - MELT + LLM recommendations + AIOps diagnosis

Phase 7 change: /diagnose now forwards the absolute time-window params
(start, end) and the backend selector through to llm-svc, in addition to
window and service. Previously only window+service were forwarded, so
?start=...&end=...&backend=... were silently dropped and llm-svc fell back
to a relative 5m window.
"""
import os
import logging
import json
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
    "service.version": "0.5.0",
    "deployment.environment": "lab",
    "cloud.provider": "aws",
    "cloud.region": "us-east-2",
})

provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True)))
trace.set_tracer_provider(provider)
set_global_textmap(TraceContextTextMapPropagator())

logger_provider = LoggerProvider(resource=resource)
logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=OTEL_ENDPOINT, insecure=True)))
set_logger_provider(logger_provider)
otel_handler = LoggingHandler(level=logging.DEBUG, logger_provider=logger_provider)
logging.getLogger().addHandler(otel_handler)
logging.getLogger().setLevel(logging.INFO)
LoggingInstrumentor().instrument(set_logging_format=True)

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

class OTelJSONFormatter(logging.Formatter):
    def format(self, record):
        current_span = trace.get_current_span()
        ctx = current_span.get_span_context()
        log_data = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname.lower(),
            "event": record.getMessage(),
            "service": "gateway",
            "logger": record.name,
        }
        if ctx.is_valid:
            log_data["trace_id"] = format(ctx.trace_id, "032x")
            log_data["span_id"] = format(ctx.span_id, "016x")
        return json.dumps(log_data)

stdout_handler = logging.StreamHandler()
stdout_handler.setFormatter(OTelJSONFormatter())
logging.getLogger().addHandler(stdout_handler)

HTTPXClientInstrumentor().instrument()
app = FastAPI(title="OTel Lab - API Gateway", version="0.5.0")
FastAPIInstrumentor.instrument_app(app)

logger = logging.getLogger("gateway")
PRODUCT_SVC_URL = os.getenv("PRODUCT_SVC_URL", "http://product-svc:8001")
LLM_SVC_URL = os.getenv("LLM_SVC_URL", "http://llm-svc:8002")

@app.get("/health")
async def health():
    logger.info("health_check status=ok")
    return {"status": "ok", "service": "gateway", "version": "0.5.0"}

@app.get("/products")
async def list_products():
    logger.info("listing_products")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{PRODUCT_SVC_URL}/products", timeout=5.0)
            response.raise_for_status()
            data = response.json()
            logger.info(f"products_returned count={len(data)}")
            return data
        except httpx.HTTPError as e:
            logger.error(f"product_svc_error error={str(e)}")
            raise HTTPException(status_code=502, detail=f"product-svc error: {str(e)}")

@app.get("/products/{product_id}")
async def get_product(product_id: int):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{PRODUCT_SVC_URL}/products/{product_id}", timeout=5.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"product-svc error: {str(e)}")

@app.get("/recommendations")
async def get_recommendations(query: str = "best product for developers"):
    logger.info(f"recommendation_request query={query}")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{LLM_SVC_URL}/recommendations",
                params={"query": query},
                timeout=30.0
            )
            response.raise_for_status()
            result = response.json()
            logger.info(
                f"recommendation_complete model={result.get('model')} "
                f"input_tokens={result.get('tokens', {}).get('input')} "
                f"cost_usd={result.get('cost_usd')}"
            )
            return result
        except httpx.HTTPError as e:
            logger.error(f"llm_svc_error error={str(e)}")
            raise HTTPException(status_code=502, detail=f"llm-svc error: {str(e)}")

@app.get("/diagnose")
async def diagnose(
    window: str = "5m",
    start: str | None = None,
    end: str | None = None,
    service: str = "gateway",
    backend: str = "dash0",
):
    logger.info(
        f"diagnose_request window={window} start={start} end={end} "
        f"service={service} backend={backend}"
    )
    # Forward window+service+backend always; forward start/end only when both
    # are supplied, so we never pass empty strings that llm-svc would treat as
    # a (zero-length, invalid) absolute window.
    params = {"window": window, "service": service, "backend": backend}
    if start and end:
        params["start"] = start
        params["end"] = end

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{LLM_SVC_URL}/diagnose",
                params=params,
                timeout=30.0
            )
            response.raise_for_status()
            result = response.json()
            logger.info(
                f"diagnose_complete root_cause={result.get('diagnosis', {}).get('root_cause')} "
                f"confidence={result.get('diagnosis', {}).get('confidence')} "
                f"severity={result.get('diagnosis', {}).get('severity')}"
            )
            return result
        except httpx.HTTPError as e:
            logger.error(f"diagnose_error error={str(e)}")
            raise HTTPException(status_code=502, detail=f"diagnose error: {str(e)}")
