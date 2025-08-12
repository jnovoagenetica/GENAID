FROM public.ecr.aws/docker/library/python:3.11.6-slim-bookworm

# (Quitar la línea del lambda-adapter)

WORKDIR /app  # opcional, más estándar; si prefieres, puedes dejar /backend
COPY ./pyproject.toml ./poetry.lock ./

ENV POETRY_REQUESTS_TIMEOUT=10800
RUN python -m pip install --upgrade pip && \
    pip install poetry --no-cache-dir && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi && \
    poetry cache clear --all pypi

# Copia tu código
COPY . .

ENV PORT=8000
EXPOSE ${PORT}
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]