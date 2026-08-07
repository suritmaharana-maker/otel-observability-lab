"""
API Gateway - Phase 8 - network-team-only scope

No OpenTelemetry SDK instrumentation. This is deliberate: the network
observability design this app feeds into (Hubble + OBI eBPF, /diagnose)
is scoped to work with ZERO app-code cooperation - that's the whole
point of a network team's tooling. SDK instrumentation now belongs to
a separate, unrelated app-team effort, not this one. OBI's own eBPF
traces (re-enabled in k8s/obi-values.yaml) are the only trace source
for this system now; OBI has its own eBPF-level context propagation,
independent of any app-level traceparent header handling, so
cross-service request linking still works without this app doing
anything.
"""
import os
import logging
import json
import structlog
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname.lower(),
            "event": record.getMessage(),
            "service": "gateway",
            "logger": record.name,
        }
        return json.dumps(log_data)

stdout_handler = logging.StreamHandler()
stdout_handler.setFormatter(JSONFormatter())
logging.getLogger().addHandler(stdout_handler)
logging.getLogger().setLevel(logging.INFO)

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

app = FastAPI(title="OTel Lab - API Gateway", version="0.5.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

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
