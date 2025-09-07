# --- INICIO DEL ARCHIVO ---

# 1) Cargar .env ANTES de todo
from mangum import Mangum
import os
from dotenv import load_dotenv
if not os.environ.get("AWS_EXECUTION_ENV"):
    load_dotenv(dotenv_path=".env.local")

# 2) Imports
import logging
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
PUBLISHED_API_ID = (os.getenv("PUBLISHED_API_ID") or "").strip() or None

IS_PUBLISHED_API = bool(PUBLISHED_API_ID)

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s - %(message)s")
logger = logging.getLogger(__name__)

if not IS_PUBLISHED_API:
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
    if request.headers.get("Authorization"):
        return await call_next(request)

    # Si no hay token y nadie puso usuario aún, usa 'anon'
    if not hasattr(request.state, "current_user"):
        request.state.current_user = User(id="anon", name="Anonymous", groups=[])
    return await call_next(request)

# ------------------ Routers ------------------

if not IS_PUBLISHED_API:
    app.include_router(conversation_router)
    app.include_router(bot_router)
    app.include_router(api_publication_router)
    app.include_router(admin_router)
    if not is_running_on_lambda():
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

@debug_router.get("/__routes", tags=["admin"])
def list_routes():
    items = []
    for r in app.router.routes:
        path = getattr(r, "path", None)
        methods = sorted(list(getattr(r, "methods", []) or []))
        if path:
            items.append({"path": path, "methods": methods})
    return {"routes": items}

@debug_router.get("/openapi_raw", tags=["admin"])
def openapi_raw():
    from fastapi.responses import JSONResponse
    return JSONResponse(app.openapi())

app.include_router(debug_router)

# --- Compat layer: /bots -> /bot (real) ---
import httpx
from fastapi import Query
from typing import List, Dict, Optional

# usa el base_path ya calculado abajo; lo exponemos global
# (está definido más abajo; lo referenciamos vía globals() en runtime)
def _make_base(request: Request) -> str:
    # Construye URL pública (con stage /default si aplica)
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    pb = globals().get("PUBLIC_BASE_PATH", "")  # p.ej. "/default/geneaid-backend-v5"
    return f"{scheme}://{host}{pb}"

def _forward_headers(request: Request) -> Dict[str, str]:
    h = {}
    for k in ("authorization", "x-user-id", "x-user-groups"):
        v = request.headers.get(k)
        if v:
            h[k] = v
    return h

@app.get("/bots")
async def bots_compat(
    request: Request,
    kind: Optional[str] = Query(default=None),
    botKind: Optional[str] = Query(default=None),
    limit: int = Query(default=30),
) -> List[Dict]:
    """
    Devuelve bots reales consultando /bot y adaptando al formato esperado.
    Soporta ?kind=metadata|private y ?botKind=... (ambos nombres).
    """
    k = (botKind or kind or "metadata").lower()

    base = _make_base(request)
    headers = _forward_headers(request)

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{base}/bot", headers=headers)
        r.raise_for_status()
        data = r.json()  # lista de bots reales

    # Normaliza y filtra
    norm = []
    for b in (data or [])[: max(0, limit)]:
        # visibilidad: usa visibility o cae a isPublic
        vis = (b.get("visibility") or ("public" if b.get("isPublic") else "private")).lower()

        item = {
            "id": b.get("id") or b.get("botId") or b.get("bot_id"),
            # <-- name puede venir como 'title' en tu API real
            "name": b.get("name") or b.get("title") or b.get("displayName"),
            "description": b.get("description") or b.get("summary"),
            "isFavorite": bool(b.get("isPinned") or b.get("isFavorite")),
            "avatarUrl": b.get("avatarUrl") or b.get("iconUrl") or None,
            "visibility": vis,
        }
        norm.append(item)

    if k == "private":
        norm = [x for x in norm if x.get("visibility") == "private"]

    # Sólo devuelve los campos que usa el front
    return [
        {
            "id": x["id"],
            "name": x["name"],
            "description": x["description"],
            "isFavorite": x["isFavorite"],
            "avatarUrl": x["avatarUrl"],
        }
        for x in norm
    ]

@app.get("/bots/find-and-include-metadata")
async def bots_compat_alias(request: Request, limit: int = Query(default=30)) -> List[Dict]:
    return await bots_compat(request, kind="metadata", limit=limit)

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

# ---------- Middleware #2: auth real + fallback por headers ----------
@app.middleware("http")
async def add_current_user_to_request(request: Request, call_next):
    authorization = request.headers.get("Authorization")
    x_user_id = (request.headers.get("x-user-id") or "").strip()
    x_user_groups = (request.headers.get("x-user-groups") or "")
    groups = [g.strip() for g in x_user_groups.split(",") if g.strip()]

    # Modo Published API: identidad fija
    if IS_PUBLISHED_API:
        request.state.current_user = User(
            id=f"PUBLISHED_API#{PUBLISHED_API_ID}",
            name=PUBLISHED_API_ID,  # type: ignore
            groups=[],
        )
        return await call_next(request)

    # 1) Si viene token, úsalo
    if authorization:
        try:
            token_str = authorization.split(" ", 1)[1]
            token = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token_str)
            request.state.current_user = get_current_user(token)
            # NO hay return aquí, para que el fallback pueda actuar si el token es inválido
            # y get_current_user lanza excepción
        except Exception:
            # Si el token es inválido o malformado, simplemente lo ignoramos.
            # El bloque final garantizará un usuario anónimo.
            pass

    # 2) Fallback: cabeceras simples (útil cuando el front no manda token)
    # Se ejecuta SOLO si no había token o el token era inválido
    if not hasattr(request.state, "current_user") and x_user_id:
        request.state.current_user = User(id=x_user_id, name=x_user_id, groups=groups)

    # 3) Sin token ni x-user-id, o token inválido: garantiza usuario 'anon'
    if not hasattr(request.state, "current_user"):
        request.state.current_user = User(id="anon", name="Anonymous", groups=[])
    return await call_next(request)

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

from mangum import Mangum
import os

raw_base = (os.getenv("API_GATEWAY_BASE_PATH") or "").strip()
# Si viene "/default/geneaid-backend-v5", lo convertimos a "/geneaid-backend-v5"
if raw_base.startswith("/default/"):
    base_path = raw_base[len("/default"):]  # -> "/geneaid-backend-v5"
else:
    base_path = raw_base

PUBLIC_BASE_PATH = raw_base or base_path  # <-- incluye "/default/..." si existe

kwargs = {}
if base_path:
    kwargs["api_gateway_base_path"] = base_path

handler = Mangum(app, **kwargs)
# --- FIN DEL ARCHIVO ---