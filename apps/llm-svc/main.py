"""
LLM Service — Phase 1 skeleton
Calls AWS Bedrock (Claude) for product recommendations
Structured for Phase 4 OpenLLMetry instrumentation

PHASE 4 NOTE: TracerProvider must be configured BEFORE Traceloop.init()
The init order is pre-planned here — do not change without reading PREFLIGHT_RISKS.md
"""
import os
import json
import boto3
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

app = FastAPI(
    title="OTel Lab — LLM Service",
    version="0.1.0",
    description="LLM service using AWS Bedrock for the OTel Observability Lab",
)

AWS_REGION = os.getenv("AWS_REGION", "us-east-2")
BEDROCK_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID",
    "anthropic.claude-3-5-sonnet-20241022-v2:0"
)

# Bedrock client — uses IAM role attached to EKS node group
# AmazonBedrockFullAccess policy is attached in terraform/eks/main.tf
bedrock = boto3.client(
    service_name="bedrock-runtime",
    region_name=AWS_REGION,
)


class RecommendRequest(BaseModel):
    product_name: str
    category: Optional[str] = None
    price_range: Optional[str] = None


class RecommendResponse(BaseModel):
    recommendation: str
    model_id: str
    # Phase 4 will add: token_count, latency_ms, trace_id


@app.get("/health")
async def health():
    return {"status": "ok", "service": "llm-svc", "version": "0.1.0"}


@app.post("/recommend", response_model=RecommendResponse)
async def recommend(request: RecommendRequest):
    """
    Get AI-powered product recommendation from AWS Bedrock.
    
    Phase 4 will wrap this with OpenLLMetry to capture:
    - Token consumption (gen_ai.usage.input_tokens, gen_ai.usage.output_tokens)
    - Model latency (span duration)
    - Prompt/response correlation
    - Cost attribution
    All as child spans of the parent HTTP trace from the gateway.
    """
    prompt = f"""You are a helpful product recommendation assistant.
    
A customer is looking at: {request.product_name}
Category: {request.category or 'Not specified'}
Price range: {request.price_range or 'Any'}

Provide a concise 2-3 sentence recommendation about this product and suggest one complementary product they might also like."""

    try:
        response = bedrock.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 256,
                "messages": [{"role": "user", "content": prompt}],
            }),
        )
        result = json.loads(response["body"].read())
        recommendation = result["content"][0]["text"]

        return RecommendResponse(
            recommendation=recommendation,
            model_id=BEDROCK_MODEL_ID,
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Bedrock invocation failed: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
