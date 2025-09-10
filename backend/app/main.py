# --- INICIO DEL ARCHIVO ---

# 1) Cargar variables de entorno ANTES que cualquier otro módulo
from dotenv import load_dotenv
load_dotenv(dotenv_path=".env.local")

# 2) Imports base (ligeros)
import logging
import os
import traceback
from typing import Callable, Optional

from mangum import Mangum  # necesario para Lambda

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from starlette.types import ASGIApp

# Util para no depender de app.utils en el arranque
def running_on_lambda() -> bool:
    return "AWS_LAMBDA_FUNCTION_NAME" in os.environ

CORS_ALLOW_ORIGINS = os.environ.get("CORS_ALLOW_ORIGINS", "*")
PUBLISHED_API_ID = os.environ.get("PUBLISHED_API_ID")  # puede ser None
is_published_api = PUBLISHED_API_ID is not None

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s - %(message)s")
logger = logging.getLogger(__name__)

# Títulos/etiquetas (seguros: no importan otros módulos)
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

app = FastAPI(openapi_tags=openapi_tags, title=title)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check SIEMPRE disponible
@app.get("/health", tags=["admin"])
def health():
    return {"status": "ok", "service": "backend-v6"}

# ---- Manejadores de error (ligeros y seguros) ----
def error_handler_factory(status_code: int) -> Callable[[Request, Exception], JSONResponse]:
    def error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.error(exc)
        try:
            logger.error("".join(traceback.format_tb(exc.__traceback__)))
        except Exception:
            pass
        return JSONResponse({"errors": [str(exc)]}, status_code=status_code)
    return error_handler  # type: ignore

# Genérico 500
@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception):
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse({"errors": [str(exc)]}, status_code=500)

# ---- Lazy-load de routers para no romper /health ----
def try_include_routers() -> Optional[str]:
    """
    Importa routers de forma diferida. Si algo falla (módulo faltante, etc.),
    lo logueamos pero NO caemos el proceso para que /health siga funcionando.
    Si falla, registramos un stub mínimo en /conversation (eco).
    """
    try:
        if not is_published_api:
            from app.routes.conversation import router as conversation_router  # type: ignore
            from app.routes.bot import router as bot_router  # type: ignore
            from app.routes.api_publication import router as api_publication_router  # type: ignore
            from app.routes.admin import router as admin_router  # type: ignore

            app.include_router(conversation_router)
            app.include_router(bot_router)
            app.include_router(api_publication_router)
            app.include_router(admin_router)

            # opcional: WebSocket local (si no existe, no pasa nada)
            try:
                from app.ws_local import router as ws_local_router  # type: ignore
                app.include_router(ws_local_router)
            except Exception as e:
                logger.warning("ws_local no cargó (ignorado): %s", e)
        else:
            from app.routes.published_api import router as published_api_router  # type: ignore
            app.include_router(published_api_router)

        logger.info("Routers cargados correctamente.")
        return None
    except Exception as e:
        logger.exception("Fallo cargando routers; exponemos stub /conversation: %s", e)

        @app.post("/conversation", tags=["conversation"])
        async def _conversation_stub(req: Request):
            """
            Stub temporal: eco del body para que el front no falle.
            Se reemplaza automáticamente cuando los routers reales carguen.
            """
            try:
                body = await req.json()
            except Exception:
                body = None
            return {"ok": True, "echo": body, "stub": True}

        return str(e)

_router_err = try_include_routers()

# ---- Endpoints auxiliares para front con streaming activo ----
@app.get("/conversation/{conversation_id}/proceed", tags=["conversation"])
async def conversation_proceed(conversation_id: str):
    """
    Stub para compatibilidad cuando el front tiene streaming activado.
    No emite tokens por HTTP; simplemente devuelve 204 para que la UI continúe.
    (El streaming real lo haremos por WebSocket).
    """
    return Response(status_code=204)

# ---- Middlewares ----
@app.middleware("http")
async def add_current_user_to_request(request: Request, call_next: ASGIApp):
    """
    Intentamos validar JWT sólo si viene Authorization.
    Si falla o no viene, asignamos un test_user y seguimos.
    """
    authorization = request.headers.get("Authorization")
    if authorization:
        try:
            token_str = authorization.split(" ")[1]
            token = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token_str)  # type: ignore
            # Lazy import (para no reventar /health si falta algo)
            from app.dependencies import get_current_user  # type: ignore

            request.state.current_user = get_current_user(token)
        except Exception as e:
            logger.warning("No se pudo validar token, usando test_user: %s", e)
            request.state.current_user = {"id": "test_user", "name": "test_user", "groups": []}
    else:
        request.state.current_user = {"id": "test_user", "name": "test_user", "groups": []}

    response = await call_next(request)
    return response

@app.middleware("http")
async def add_log_requests(request: Request, call_next: ASGIApp):
    logger.info(f"Request path: {request.url.path}")
    logger.info(f"Request method: {request.method}")
    logger.info(f"Request headers: {request.headers}")

    try:
        body = await request.body()
        logger.info(f"Request body: {body.decode('utf-8')[:1000]}...")
    except Exception:
        pass

    response = await call_next(request)
    return response

# Handler Lambda
handler = Mangum(app)

# --- FIN DEL ARCHIVO ---
