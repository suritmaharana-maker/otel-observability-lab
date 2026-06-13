"""
API Gateway — Phase 1 skeleton
Routes requests to product-svc and llm-svc
OTel instrumentation added in Phase 2
"""
import os
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="OTel Lab — API Gateway",
    version="0.1.0",
    description="API Gateway for the OTel Observability Lab",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

PRODUCT_SVC_URL = os.getenv("PRODUCT_SVC_URL", "http://product-svc:8001")
LLM_SVC_URL = os.getenv("LLM_SVC_URL", "http://llm-svc:8002")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "gateway", "version": "0.1.0"}


@app.get("/products")
async def list_products():
    """Proxy to product-svc"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{PRODUCT_SVC_URL}/products", timeout=5.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"product-svc error: {str(e)}")


@app.get("/products/{product_id}")
async def get_product(product_id: int):
    """Proxy to product-svc"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{PRODUCT_SVC_URL}/products/{product_id}", timeout=5.0
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"product-svc error: {str(e)}")


@app.post("/recommend")
async def recommend(payload: dict):
    """Proxy to llm-svc — Phase 4 will add OpenLLMetry tracing here"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{LLM_SVC_URL}/recommend", json=payload, timeout=30.0
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"llm-svc error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
