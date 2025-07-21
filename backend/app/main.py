# --- INICIO DEL ARCHIVO: main.py (VERSIÓN FINAL CORREGIDA) ---

# 1. Cargar las variables de entorno
from dotenv import load_dotenv
load_dotenv(dotenv_path=".env.local")

# 2. Importaciones
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
from app.user import User
from app.utils import is_running_on_lambda
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message

# --- CONFIGURACIÓN ---
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s - %(message)s")
logger = logging.getLogger(__name__)
print("--- MAIN.PY VERSIÓN FINAL CARGADA CORRECTAMENTE ---") # Marcador

PUBLISHED_API_ID = os.environ.get("PUBLISHED_API_ID", None)
is_published_api = PUBLISHED_API_ID is not None

# ... (código de openapi_tags y title) ...
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

# /---------------------------------------\
# |    INICIO DE LA CORRECCIÓN DE CORS    |
# \---------------------------------------/
# Se leen los orígenes permitidos desde las variables de entorno
CORS_ALLOW_ORIGINS = os.environ.get("CORS_ALLOW_ORIGINS")
allowed_origins = []
if CORS_ALLOW_ORIGINS:
    allowed_origins.extend(CORS_ALLOW_ORIGINS.split(','))
else:
    # Si no se especifica, se usan valores por defecto para desarrollo local
    # Tu frontend corre en localhost:5173 (lo vemos en los errores)
    allowed_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    logger.warning(f"CORS_ALLOW_ORIGINS no está definida. Usando valores por defecto para desarrollo: {allowed_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins, # Usamos la lista que acabamos de crear
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# /---------------------------------------\
# |      FIN DE LA CORRECCIÓN DE CORS     |
# \---------------------------------------/


# --- INCLUSIÓN DE ROUTERS ---
if not is_published_api:
    app.include_router(conversation_router)
    app.include_router(bot_router)
    app.include_router(api_publication_router)
    app.include_router(admin_router)
else:
    app.include_router(published_api_router)

# --- MANEJADORES DE EXCEPCIONES (Sin cambios) ---
# ... (todo tu código de app.add_exception_handler) ...
def error_handler_factory(status_code: int) -> Callable[[Request, Exception], Response]:
    def error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.error(exc); logger.error("".join(traceback.format_tb(exc.__traceback__)))
        return JSONResponse({"errors": [str(exc)]}, status_code=status_code)
    return error_handler
app.add_exception_handler(RecordNotFoundError, error_handler_factory(404)); app.add_exception_handler(FileNotFoundError, error_handler_factory(404)); app.add_exception_handler(RecordAccessNotAllowedError, error_handler_factory(403)); app.add_exception_handler(ValueError, error_handler_factory(400)); app.add_exception_handler(TypeError, error_handler_factory(400)); app.add_exception_handler(AssertionError, error_handler_factory(400)); app.add_exception_handler(PermissionError, error_handler_factory(403)); app.add_exception_handler(ValidationError, error_handler_factory(422)); app.add_exception_handler(ResourceConflictError, error_handler_factory(409)); app.add_exception_handler(Exception, error_handler_factory(500));


# --- MIDDLEWARES DE AUTENTICACIÓN Y LOGGING (Sin cambios, pero con la corrección anterior) ---
# ... (tu middleware add_current_user_to_request) ...
@app.middleware("http")
def add_current_user_to_request(request: Request, call_next: ASGIApp):
    if is_running_on_lambda():
        if not is_published_api:
            authorization=request.headers.get("Authorization"); token_str=authorization.split(" ")[1] if authorization else ""; token=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token_str); request.state.current_user=get_current_user(token)
        else:
            request.state.current_user = User(id=f"PUBLISHED_API#{PUBLISHED_API_ID}", name=PUBLISHED_API_ID, groups=[])
    else:
        authorization=request.headers.get("Authorization")
        if authorization:
            try: token_str=authorization.split(" ")[1]; token=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token_str); request.state.current_user=get_current_user(token)
            except IndexError: request.state.current_user=User(id="test_user_invalid_token", name="test_user_invalid_token", groups=[])
        else:
            request.state.current_user=User(id="test_user", name="test_user", groups=[])
    response=call_next(request); return response

# ... (tu middleware add_log_requests corregido) ...
@app.middleware("http")
async def add_log_requests(request: Request, call_next: ASGIApp):
    logger.info(f"Request path: {request.url.path}"); logger.info(f"Request method: {request.method}"); logger.info(f"Request headers: {request.headers}")
    content_type=request.headers.get("content-type", "")
    if "multipart/form-data" in content_type: logger.info("Request body: [multipart/form-data stream - omitido del log para evitar errores]")
    else:
        try: body=await request.body(); logger.info(f"Request body: {body.decode('utf-8', errors='ignore')[:1000]}..."); request._body=body
        except Exception as e: logger.warning(f"No se pudo leer el request body para el log: {e}")
    response=await call_next(request); return response

# --- FIN DEL ARCHIVO ---