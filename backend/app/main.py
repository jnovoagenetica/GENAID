# --- INICIO DEL ARCHIVO ---

# 1) Cargar .env ANTES de todo
from dotenv import load_dotenv
load_dotenv(dotenv_path=".env.local")

# 2) Imports
import logging
import os
import traceback
from typing import Callable

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
# --- Router local de WebSocket ---
from app.ws_local import router as ws_local_router
from app.user import User
from app.utils import is_running_on_lambda

from fastapi import FastAPI, Request, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials

from starlette.responses import Response
from pydantic import ValidationError  # <-- import necesario

# ------------------ Config básica ------------------

CORS_ALLOW_ORIGINS = os.environ.get("CORS_ALLOW_ORIGINS", "*")
PUBLISHED_API_ID = os.environ.get("PUBLISHED_API_ID", None)

is_published_api = PUBLISHED_API_ID is not None

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s - %(message)s")
logger = logging.getLogger(__name__)

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

app = FastAPI(
    openapi_tags=openapi_tags,
    title=title,
)

# --- Endpoint de salud para el ALB (200 OK siempre) ---
@app.get("/health", tags=["admin"])
def health():
    return {"status": "ok"}

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Middleware #1: asegurar usuario anónimo SOLO si NO hay token ----------
# Lo ponemos ANTES de include_router(...) y ANTES del middleware de auth real.
# Si llega Authorization, NO seteamos nada aquí; dejamos que el middleware de auth lo maneje.
@app.middleware("http")
async def ensure_current_user_anon(request: Request, call_next):
    # Si viene un token, no tocar; que lo procese el middleware de auth real
    if request.headers.get("authorization"):
        return await call_next(request)

    # Si no hay token y nadie puso usuario aún, usa 'anon'
    if not hasattr(request.state, "current_user"):
        request.state.current_user = User(id="anon", name="Anonymous", groups=[])
    return await call_next(request)

# ------------------ Routers ------------------

if not is_published_api:
    app.include_router(conversation_router)
    app.include_router(bot_router)
    app.include_router(api_publication_router)
    app.include_router(admin_router)
    app.include_router(ws_local_router)  # WebSocket local
else:
    app.include_router(published_api_router)

# (Opcional) Router de depuración para verificar el usuario actual
debug_router = APIRouter()

@debug_router.get("/whoami")
def whoami(request: Request):
    u = getattr(request.state, "current_user", None)
    return {
        "id": getattr(u, "id", "anon"),
        "name": getattr(u, "name", "Anonymous"),
        "groups": getattr(u, "groups", []),
    }

app.include_router(debug_router)

# ------------------ Manejo de errores ------------------

def error_handler_factory(status_code: int) -> Callable[[Request, Exception], Response]:
    def error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.error(exc)
        logger.error("".join(traceback.format_tb(exc.__traceback__)))
        return JSONResponse({"errors": [str(exc)]}, status_code=status_code)
    return error_handler  # type: ignore

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

# ---------- Middleware #2: auth real cuando haya token ----------
# Este puede sobrescribir al 'anon' si llega Authorization.
@app.middleware("http")
async def add_current_user_to_request(request: Request, call_next):
    if is_running_on_lambda():
        # Producción en Lambda / ECS detrás de ALB
        if not is_published_api:
            authorization = request.headers.get("Authorization")
            if authorization:
                try:
                    token_str = authorization.split(" ")[1]
                    token = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token_str)
                    request.state.current_user = get_current_user(token)
                except Exception:
                    # Si hay problema con el token, mantenemos lo que haya (anon del middleware #1)
                    pass
        else:
            request.state.current_user = User(
                id=f"PUBLISHED_API#{PUBLISHED_API_ID}",
                name=PUBLISHED_API_ID,  # type: ignore
                groups=[],
            )
    else:
        # Desarrollo local con/ sin token
        authorization = request.headers.get("Authorization")
        if authorization:
            try:
                token_str = authorization.split(" ")[1]
                token = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token_str)
                request.state.current_user = get_current_user(token)
            except Exception:
                request.state.current_user = User(id="test_user", name="test_user", groups=[])
        else:
            # Sin token: usuario de prueba en local
            request.state.current_user = User(id="test_user", name="test_user", groups=[])

    response = await call_next(request)
    return response

# ---------- Middleware #3: logging ----------
@app.middleware("http")
async def add_log_requests(request: Request, call_next):
    logger.info(f"Request path: {request.url.path}")
    logger.info(f"Request method: {request.method}")
    logger.info(f"Request headers: {request.headers}")

    try:
        body = await request.body()
        logger.info(f"Request body: {body.decode('utf-8')[:1000]}...")
    except Exception:
        logger.info("Request body: <no-decodable>")

    response = await call_next(request)
    return response
# --- FIN DEL ARCHIVO ---
