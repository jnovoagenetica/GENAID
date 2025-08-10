import json
import logging
import asyncio
import anyio
from typing import Dict, List
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

# --- AÑADIDO: Nuevas importaciones para persistir la conversación ---
from ulid import ULID
from app.utils import get_current_time
from app.repositories.conversation import store_conversation
from app.repositories.models.conversation import ContentModel, MessageModel
# --- FIN DE AÑADIDOS ---

from app.auth import verify_token
from app.routes.schemas.conversation import ChatInput
from app.usecases.chat import prepare_conversation, trace_to_root
from app.bedrock import compose_args_for_converse_api
from app.stream import ConverseApiStreamHandler

router = APIRouter()
log = logging.getLogger(__name__)

_sessions: Dict[int, List[str]] = {}
_user_ids: Dict[int, str] = {}

@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    cid = id(ws)
    _sessions[cid] = []
    log.info("[WS-LOCAL] connected cid=%s", cid)

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
                    decoded = verify_token(token)
                    _user_ids[cid] = decoded["sub"]
                except Exception:
                    await ws.send_text(json.dumps({"status":"ERROR","reason":"invalid_token"}))
                    continue
                await ws.send_text("Session started.")
                log.info("[WS-LOCAL] START ok cid=%s user=%s", cid, _user_ids[cid])

            elif step == "CHUNK":
                _sessions[cid].append(data.get("part", ""))
                await ws.send_text("Message part received.")

            elif step == "END":
                full_message = "".join(_sessions.get(cid, []))
                log.info("[WS-LOCAL] END len=%s", len(full_message))

                # logs de inspección del payload
                try:
                    parsed = json.loads(full_message)
                    msg = parsed.get("message", {})
                    contents = msg.get("content", [])
                    by_type = {}
                    for c in contents:
                        t = c.get("contentType")
                        by_type[t] = by_type.get(t, 0) + 1
                    log.info("[WS-LOCAL] contentType breakdown: %s", by_type)
                    pdfs = [c for c in contents if c.get("contentType") == "textAttachment"]
                    for i, a in enumerate(pdfs, 1):
                        b64 = a.get("body") or ""
                        log.info("[WS-LOCAL] PDF[%d] fileName=%s mime=%s b64_len=%s",
                                 i, a.get("fileName"), a.get("mediaType"), len(b64))
                except Exception:
                    log.exception("[WS-LOCAL] No se pudo inspeccionar el payload JSON")

                chat_input = ChatInput(**json.loads(full_message))
                user_id = _user_ids.get(cid, "local-user")

                # Estas variables serán "capturadas" por _on_stop gracias a `nonlocal`
                user_msg_id, conversation, bot = prepare_conversation(user_id, chat_input)

                # --- INICIO DE LA MODIFICACIÓN ---
                # 👉 NUEVO: guarda ya la conversación con el mensaje del usuario
                store_conversation(user_id, conversation)
                log.info("[WS-LOCAL] Conversación %s guardada inicial (para proposed-title)", conversation.id)
                # --- FIN DE LA MODIFICACIÓN ---

                message_map = conversation.message_map
                messages = trace_to_root(node_id=user_msg_id, message_map=message_map)

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
                )

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
                    for _ in handler.run(args):
                        pass

                await anyio.to_thread.run_sync(_runner)

            else:
                ...

    except WebSocketDisconnect:
        log.info("[WS-LOCAL] disconnected cid=%s", cid)
    finally:
        _sessions.pop(cid, None)
        _user_ids.pop(cid, None)