FROM python:3.11-slim

# --- system deps -----------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
    && rm -rf /var/lib/apt/lists/*

# --- app -------------------------------------------------------------------
WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r requirements.txt

# Engine modules (workload_engine.py, excel_parser.py) must be importable
ENV PYTHONPATH=/app/engine

EXPOSE 8080

# uvicorn --app-dir points it at the web/ package directory so it finds workload_api
CMD ["uvicorn", "workload_api:app", "--app-dir", "/app/web", "--host", "0.0.0.0", "--port", "8080"]
