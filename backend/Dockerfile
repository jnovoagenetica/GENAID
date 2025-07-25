FROM public.ecr.aws/docker/library/python:3.11.6-slim-bookworm

# --- Tesseract OCR y dependencias ---
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-spa \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Lambda Web Adapter (opcional)
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.7.0 /lambda-adapter /opt/extensions/lambda-adapter

WORKDIR /backend

COPY ./pyproject.toml ./poetry.lock ./

ENV POETRY_REQUESTS_TIMEOUT=10800
RUN python -m pip install --upgrade pip && \
    pip install poetry --no-cache-dir && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --only main && \
    poetry cache clear --all pypi

COPY ./app ./app

ENV PORT=8000
EXPOSE ${PORT}
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
