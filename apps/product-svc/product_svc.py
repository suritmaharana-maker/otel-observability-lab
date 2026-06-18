import logging
import os

import psycopg2
import structlog
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

resource = Resource.create({"service.name": "product-svc", "service.version": "1.0.0"})
provider = TracerProvider(resource=resource)
otlp = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otelcol.observability.svc.cluster.local:4317")
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp, insecure=True)))
trace.set_tracer_provider(provider)
Psycopg2Instrumentor().instrument()

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

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "products")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")

app = FastAPI(title="product-svc")
FastAPIInstrumentor.instrument_app(app)


def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS,
    )


@app.on_event("startup")
def seed():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            price NUMERIC(10,2) NOT NULL,
            description TEXT
        )
    """)
    cur.execute("SELECT COUNT(*) FROM products")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO products (name, price, description) VALUES (%s, %s, %s)",
            [
                ("OTel Starter Kit", 49.99, "Everything you need to instrument your first service"),
                ("eBPF Deep Dive Book", 89.99, "Comprehensive guide to eBPF and kernel observability"),
                ("Cilium Enterprise License", 999.00, "Enterprise Cilium with Hubble UI and support"),
                ("Beyla Pro Bundle", 199.99, "Beyla with extended dashboards and alert templates"),
                ("OTel Collector Config Pack", 29.99, "50 production-ready Collector configurations"),
            ],
        )
    conn.commit()
    cur.close()
    conn.close()
    log.info("database_seeded")


@app.get("/products")
def get_products():
    log.info("fetching_products")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, price, description FROM products ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    products = [
        {"id": r[0], "name": r[1], "price": float(r[2]), "description": r[3]}
        for r in rows
    ]
    log.info("products_fetched", count=len(products))
    return products


@app.get("/products/{product_id}")
def get_product(product_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, price, description FROM products WHERE id = %s", (product_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(404, f"Product {product_id} not found")
    return {"id": row[0], "name": row[1], "price": float(row[2]), "description": row[3]}


@app.get("/health")
def health():
    return {"status": "ok", "service": "product-svc"}
