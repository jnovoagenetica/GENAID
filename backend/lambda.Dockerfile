FROM public.ecr.aws/lambda/python:3.11

COPY ./pyproject.toml ./poetry.lock ./

ENV POETRY_REQUESTS_TIMEOUT=10800
RUN python -m pip install --upgrade pip && \
    pip install poetry --no-cache-dir && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --only main && \
    # >>> instala wheel precompilado, evita compilar MuPDF
    pip install --no-cache-dir "PyMuPDF==1.24.9" && \
    poetry cache clear --all pypi

# Tu código
COPY ./app ./app
COPY ./embedding_statemachine ./embedding_statemachine

# Handler FastAPI via Mangum (módulo.función)
CMD ["app.main.handler"]
