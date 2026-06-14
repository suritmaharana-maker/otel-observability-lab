"""
Product Service - Phase 2 - OTel SDK instrumented
"""
import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional

OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otelcol.observability.svc.cluster.local:4317")

resource = Resource.create({
    "service.name": "product-svc",
    "service.version": "0.2.0",
    "deployment.environment": "lab",
    "cloud.provider": "aws",
    "cloud.region": "us-east-2",
})

provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True)))
trace.set_tracer_provider(provider)
set_global_textmap(TraceContextTextMapPropagator())
Psycopg2Instrumentor().instrument()

app = FastAPI(title="OTel Lab - Product Service", version="0.2.0")
FastAPIInstrumentor.instrument_app(app)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://otellab:otellab@postgres:5432/otellab")

@app.on_event("startup")
async def startup():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            price DECIMAL(10,2) NOT NULL,
            category VARCHAR(100),
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("SELECT COUNT(*) FROM products")
    count = cur.fetchone()[0]
    if count == 0:
        sample_products = [
            ("Laptop Pro X1", "High-performance laptop", 1299.99, "Electronics"),
            ("Wireless Headphones", "Noise-cancelling headphones", 299.99, "Electronics"),
            ("Standing Desk", "Adjustable height desk", 599.99, "Furniture"),
            ("Mechanical Keyboard", "RGB mechanical keyboard", 149.99, "Electronics"),
            ("Monitor 4K", "27-inch 4K display", 499.99, "Electronics"),
        ]
        cur.executemany(
            "INSERT INTO products (name, description, price, category) VALUES (%s, %s, %s, %s)",
            sample_products
        )
    conn.commit()
    cur.close()
    conn.close()

class Product(BaseModel):
    id: Optional[int] = None
    name: str
    description: str
    price: float
    category: str

@app.get("/health")
async def health():
    return {"status": "ok", "service": "product-svc", "version": "0.2.0"}

@app.get("/products", response_model=List[Product])
async def list_products():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT id, name, description, price, category FROM products ORDER BY id")
        products = cur.fetchall()
        return [dict(p) for p in products]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

@app.get("/products/{product_id}", response_model=Product)
async def get_product(product_id: int):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute(
            "SELECT id, name, description, price, category FROM products WHERE id = %s",
            (product_id,)
        )
        product = cur.fetchone()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        return dict(product)
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)