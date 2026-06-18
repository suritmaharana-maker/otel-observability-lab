FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY product_svc.py .
EXPOSE 8001
CMD ["uvicorn", "product_svc:app", "--host", "0.0.0.0", "--port", "8001"]
