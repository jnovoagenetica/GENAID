FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# --- Proxies solo durante el build (si los usas) ---
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ENV  http_proxy=${HTTP_PROXY} \
     https_proxy=${HTTPS_PROXY} \
     no_proxy=${NO_PROXY}

# Dependencias de Python
COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Código
COPY . .

EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
