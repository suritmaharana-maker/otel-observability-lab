"""
API Gateway - Phase 2 - OTel SDK instrumented
"""
import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
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

provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True)))
trace.set_tracer_provider(provider)
set_global_textmap(TraceContextTextMapPropagator())
HTTPXClientInstrumentor().instrument()

app = FastAPI(title="OTel Lab - API Gateway", version="0.2.0")
FastAPIInstrumentor.instrument_app(app)

PRODUCT_SVC_URL = os.getenv("PRODUCT_SVC_URL", "http://product-svc:8001")
LLM_SVC_URL = os.getenv("LLM_SVC_URL", "http://llm-svc:8002")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "gateway", "version": "0.2.0"}

@app.get("/products")
async def list_products():
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{PRODUCT_SVC_URL}/products", timeout=5.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
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