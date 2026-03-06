FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN pip install --no-cache-dir . \
    && mkdir -p /data

VOLUME ["/data"]

EXPOSE 8084

CMD ["uvicorn", "web_app.main:app", "--host", "0.0.0.0", "--port", "8084"]
