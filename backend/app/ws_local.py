# backend/app/routes/websocket.py

import json
import logging
import asyncio
import anyio
import base64
from typing import Dict, List, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

# --- Persistencia de conversación ---
from ulid import ULID
from app.utils import get_current_time
from app.repositories.conversation import store_conversation
from app.repositories.models.conversation import ContentModel, MessageModel
# --- Fin persistencia ---

from app.auth import verify_token
from app.routes.schemas.conversation import ChatInput
from app.usecases.chat import prepare_conversation, trace_to_root
from app.bedrock import compose_args_for_converse_api
from app.stream import ConverseApiStreamHandler

router = APIRouter()
log = logging.getLogger(__name__)

_sessions: Dict[int, List[str]] = {}
_user_ids: Dict[int, str] = {}


def _infer_format(mime: str) -> str:
    mime = (mime or "").lower()
    if "pdf" in mime: return "pdf"
    if "csv" in mime: return "csv"
    if "excel" in mime or "spreadsheet" in mime or mime.endswith("sheet"): return "xlsx"
    if "word" in mime or "document" in mime: return "docx"
    if mime.startswith("text/"): return "txt"
    return "binary"


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    cid = id(ws)
    _sessions[cid] = []
    # log.info("[WS-LOCAL] connected cid=%s", cid)

    try:
        while True:
            raw = await ws.receive_text()
            if raw in ("", "Message sent."):
                continue

            try:
                data = json.loads(raw)
            except Exception:
                continue

            step = data.get("step")

            if step == "START":
                token = data.get("token")
                try:
                    if token:
                        decoded = verify_token(token)
                        _user_ids[cid] = decoded["sub"]
                    else:
                        _user_ids[cid] = "local-user"
                        # log.warning("[WS-LOCAL] Sin token; usando usuario local")
                except Exception as e:
                    _user_ids[cid] = "local-user"
                    # log.warning("[WS-LOCAL] Token inválido (%s); usando usuario local", e)
                await ws.send_text("Session started.")
                # log.info("[WS-LOCAL] START ok cid=%s user=%s", cid, _user_ids[cid])

            elif step == "CHUNK":
                _sessions[cid].append(data.get("part", ""))
                await ws.send_text("Message part received.")

            elif step == "END":
                full_message = "".join(_sessions.get(cid, []))
                # log.info("[WS-LOCAL] END len=%s", len(full_message))

                # ---------- NUEVO: extraer adjuntos raíz y de content ----------
                uploaded_files: List[Dict[str, Any]] = []
                try:
                    parsed = json.loads(full_message)

                    # 1) Adjuntos en el payload raíz (lo que envía el FE en payload.attachments)
                    root_atts = parsed.get("attachments") or []
                    for a in root_atts:
                        if not a:
                            continue
                        name = (a.get("name") or "archivo.pdf").strip() or "archivo.pdf"
                        mime = a.get("mimeType") or "application/pdf"
                        b64  = a.get("base64") or ""
                        if b64:
                            uploaded_files.append({
                                "name": name,
                                "mimeType": mime,
                                "base64": b64,
                            })

                    # 2) Compatibilidad: adjuntos en message.content como textAttachment
                    msg = parsed.get("message", {}) or {}
                    contents = msg.get("content", []) or []

                    by_type: Dict[str, int] = {}
                    for c in contents:
                        t = c.get("contentType")
                        by_type[t] = by_type.get(t, 0) + 1
                    # log.info("[WS-LOCAL] contentType breakdown: %s", by_type)

                    pdfs = [c for c in contents if c.get("contentType") == "textAttachment"]
                    for i, a in enumerate(pdfs, 1):
                        b64 = a.get("body") or ""
                        fname = a.get("fileName") or "archivo.pdf"
                        mime = a.get("mimeType") or a.get("mediaType") or "application/pdf"
                        # log.info("[WS-LOCAL] PDF[%d] fileName=%s mime=%s b64_len=%s",
                        #          i, fname, mime, (len(b64) if isinstance(b64, str) else "bytes"))

                        # evitar duplicado simple por (name, mime)
                        key = (fname, mime)
                        exists = any((f["name"], f["mimeType"]) == key for f in uploaded_files)
                        if (not exists) and b64:
                            uploaded_files.append({
                                "name": fname,
                                "mimeType": mime,
                                "base64": b64,
                            })

                    # log.info("[WS-LOCAL] attachments(root+content)=%d", len(uploaded_files))
                except Exception:
                    # log.exception("[WS-LOCAL] No se pudo inspeccionar el payload JSON")
                    pass
                # ---------- FIN NUEVO ----------

                # Parse a ChatInput (tu modelo pydantic)
                chat_input = ChatInput(**json.loads(full_message))
                user_id = _user_ids.get(cid, "local-user")

                # Estas variables serán "capturadas" por _on_stop gracias a `nonlocal`
                user_msg_id, conversation, bot = prepare_conversation(user_id, chat_input)

                # Guardar ya la conversación con el mensaje del usuario
                store_conversation(user_id, conversation)
                # log.info("[WS-LOCAL] Conversación %s guardada inicial (para proposed-title)", conversation.id)

                message_map = conversation.message_map
                messages = trace_to_root(node_id=user_msg_id, message_map=message_map)

                # Convertir uploaded_files al formato que espera Bedrock
                attachments = []
                for f in uploaded_files:
                    b64 = f.get("base64") or ""
                    if not b64:
                        continue
                    try:
                        attachments.append({
                            "format": _infer_format(f.get("mimeType")),
                            "source": {"bytes": base64.b64decode(b64)},
                        })
                    except Exception as e:
                        # log.warning("[WS-LOCAL] base64 inválido para %s: %s", f.get("name"), e)
                        pass

                # 🔎 LOG #1: verificar lo que realmente le vamos a pasar a Bedrock
                try:
                    sizes = [len(a["source"]["bytes"]) for a in attachments]
                    fmts  = [a["format"] for a in attachments]
                    # log.info("[WS-LOCAL] Enviando a Bedrock con %d attachments. tamaños=%s formatos=%s",
                    #          len(attachments), sizes, fmts)
                except Exception:
                    # log.exception("[WS-LOCAL] No pude inspeccionar attachments")
                    pass

                args = compose_args_for_converse_api(
                    messages=messages,
                    model=chat_input.message.model,
                    instruction=(
                        message_map["instruction"].content[0].body
                        if "instruction" in message_map else None
                    ),
                    generation_params=(bot.generation_params if bot else None),
                    grounding_source=None,
                    guardrail=(bot.bedrock_guardrails if bot else None),
                    attachments=attachments,  # <-- ahora en el formato correcto
                )

                # 🔎 LOG #2: confirmar que compose_args_for_converse_api realmente incluyó los attachments
                try:
                    if isinstance(args, dict):
                        has_atts = bool(args.get("attachments"))
                        count    = len(args.get("attachments") or [])
                        sizes2   = [len(a["source"]["bytes"]) for a in (args.get("attachments") or [])]
                        # log.info("[WS-LOCAL] Args para Converse: keys=%s  has_attachments=%s  count=%d  sizes=%s",
                        #          list(args.keys()), has_atts, count, sizes2)
                    else:
                        # por si args es un objeto/TypedDict: intenta acceder con getattr
                        atts = getattr(args, "attachments", None)
                        has_atts = bool(atts)
                        count    = len(atts or [])
                        sizes2   = [len(a["source"]["bytes"]) for a in (atts or [])]
                        # log.info("[WS-LOCAL] Args(Objeto) para Converse: has_attachments=%s  count=%d  sizes=%s",
                        #          has_atts, count, sizes2)
                except Exception:
                    # log.exception("[WS-LOCAL] No pude inspeccionar args devueltos")
                    pass

                def _on_stream(token: str):
                    payload = json.dumps({"status":"STREAMING","completion": token or ""})
                    anyio.from_thread.run(ws.send_text, payload)

                def _on_stop(arg):
                    # arg.full_token: texto completo generado
                    # arg.price: costo; arg.stop_reason: "max_tokens" | "end_turn" ...
                    nonlocal conversation, user_msg_id  # usamos los de fuera

                    # Si no es "continue", agregamos un nuevo mensaje de asistente
                    if not chat_input.continue_generate:
                        assistant_msg_id = str(ULID())
                        message = MessageModel(
                            role="assistant",
                            content=[ContentModel(
                                content_type="text",
                                body=arg.full_token,
                                media_type=None,
                                file_name=None,
                            )],
                            model=chat_input.message.model,
                            children=[],
                            parent=user_msg_id,
                            create_time=get_current_time(),
                            feedback=None,
                            used_chunks=None,
                            thinking_log=None,
                        )
                        conversation.message_map[assistant_msg_id] = message
                        conversation.message_map[user_msg_id].children.append(assistant_msg_id)
                        conversation.last_message_id = assistant_msg_id
                    else:
                        # “Continue generate”: concatenar al último mensaje
                        conversation.message_map[conversation.last_message_id].content[0].body += arg.full_token  # type: ignore

                    conversation.total_price += arg.price
                    conversation.should_continue = (arg.stop_reason == "max_tokens")

                    # 🚀 ¡Persistir!
                    store_conversation(user_id, conversation)

                    # Notificar fin al front
                    payload = json.dumps({
                        "status": "STREAMING_END",
                        "completion": "",
                        "stop_reason": arg.stop_reason
                    })
                    anyio.from_thread.run(ws.send_text, payload)

                def _runner():
                    handler = ConverseApiStreamHandler(
                        model=chat_input.message.model,
                        on_stream=_on_stream,
                        on_stop=_on_stop,
                    )
                    # --- CAMBIO: Añadido log antes y después de la llamada a Bedrock ---
                    # log.info("[WS-LOCAL] Llamando a handler.run() para Bedrock stream...")
                    for _ in handler.run(args):
                        pass
                    # log.info("[WS-LOCAL] handler.run() completado OK.")

                await anyio.to_thread.run_sync(_runner)

            else:
                ...

    except WebSocketDisconnect:
        # log.info("[WS-LOCAL] disconnected cid=%s", cid)
        pass
    finally:
        _sessions.pop(cid, None)
        _user_ids.pop(cid, None)