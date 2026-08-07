"""
Product Service - Phase 8 - network-team-only scope

No OpenTelemetry SDK instrumentation. See apps/gateway/main.py for the
full rationale: this system is scoped to network-team observability
with zero app-code cooperation, so app-level SDK tracing is deliberately
out of scope here. OBI's own eBPF traces are the sole trace source.
"""
import os
import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI(title="OTel Lab - Product Service", version="0.2.0")

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
        query = "SELECT id, name, description, price, category FROM products ORDER BY id"
        cur.execute(query)
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
