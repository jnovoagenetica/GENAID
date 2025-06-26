import logging
import os
import traceback
from typing import Callable

# 👇 Carga variables de entorno desde .env.local
from dotenv import load_dotenv
load_dotenv(dotenv_path=".env.local")

from app.dependencies import get_current_user
from app.repositories.common import (
    RecordAccessNotAllowedError,
    RecordNotFoundError,
    ResourceConflictError,
)
from app.routes.admin import router as admin_router
from app.routes.api_publication import router as api_publication_router
from app.routes.bot import router as bot_router
from app.routes.conversation import router as conversation_router
from app.routes.published_api import router as published_api_router
from app.user import User
from app.utils import is_running_on_lambda
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from starlette.types import ASGIApp

# Configuración CORS
CORS_ALLOW_ORIGINS = os.environ.get("CORS_ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
PUBLISHED_API_ID = os.environ.get("PUBLISHED_API_ID", None)
is_published_api = PUBLISHED_API_ID is not None

# Logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s - %(message)s")
logger = logging.getLogger(__name__)

# OpenAPI tags
if not is_published_api:
    openapi_tags = [
        {"name": "conversation", "description": "Conversation API"},
        {"name": "bot", "description": "Bot API"},
        {"name": "api_publication", "description": "API Publication API"},
        {"name": "admin", "description": "Admin API"},
    ]
    title = "Bedrock Claude Chat"
else:
    openapi_tags = [{"name": "published_api", "description": "Published API"}]
    title = "Bedrock Claude Chat Published API"

# App
app = FastAPI(
    openapi_tags=openapi_tags,
    title=title,
)

# Routers
if not is_published_api:
    app.include_router(conversation_router)
    app.include_router(bot_router)
    app.include_router(api_publication_router)
    app.include_router(admin_router)
else:
    app.include_router(published_api_router)

# Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Error Handlers
def error_handler_factory(status_code: int) -> Callable[[Request, Exception], JSONResponse]:
    def error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.error(exc)
        logger.error("".join(traceback.format_tb(exc.__traceback__)))
        return JSONResponse({"errors": [str(exc)]}, status_code=status_code)

    return error_handler

app.add_exception_handler(RecordNotFoundError, error_handler_factory(404))
app.add_exception_handler(FileNotFoundError, error_handler_factory(404))
app.add_exception_handler(RecordAccessNotAllowedError, error_handler_factory(403))
app.add_exception_handler(ValueError, error_handler_factory(400))
app.add_exception_handler(TypeError, error_handler_factory(400))
app.add_exception_handler(AssertionError, error_handler_factory(400))
app.add_exception_handler(PermissionError, error_handler_factory(403))
app.add_exception_handler(ValidationError, error_handler_factory(422))
app.add_exception_handler(ResourceConflictError, error_handler_factory(409))
app.add_exception_handler(Exception, error_handler_factory(500))

# Middleware: Añade usuario actual
@app.middleware("http")
async def add_current_user_to_request(request: Request, call_next: ASGIApp):
    if request.method == "OPTIONS":
        # No procesar usuario en preflight CORS
        response = await call_next(request)
        return response

    authorization = request.headers.get("Authorization")

    if is_running_on_lambda():
        if not is_published_api:
            if authorization:
                token_str = authorization.split(" ")[1]
                token = HTTPAuthorizationCredentials(
                    scheme="Bearer", credentials=token_str
                )
                request.state.current_user = get_current_user(token)
        else:
            request.state.current_user = User(
                id=f"PUBLISHED_API#{PUBLISHED_API_ID}",
                name=PUBLISHED_API_ID,
                groups=[],
            )
    else:
        # LOCAL
        if authorization:
            # Si hay token, validar token real de Cognito
            token_str = authorization.split(" ")[1]
            token = HTTPAuthorizationCredentials(
                scheme="Bearer", credentials=token_str
            )
            request.state.current_user = get_current_user(token)
        else:
            # Si no hay token, usar test_user
            request.state.current_user = User(id="test_user", name="test_user", groups=[])

    response = await call_next(request)
    return response

# Middleware: Logging requests
@app.middleware("http")
async def add_log_requests(request: Request, call_next: ASGIApp):
    logger.info(f"Request path: {request.url.path}")
    logger.info(f"Request method: {request.method}")
    logger.info(f"Request headers: {request.headers}")

    body = await request.body()
    logger.info(f"Request body: {body.decode('utf-8')[:100]}...")

    response = await call_next(request)
    return response
