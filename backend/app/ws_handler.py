# app/ws_handler.py
import json, base64, logging, traceback
import boto3
from typing import Dict, List, Any
from ulid import ULID

from app.auth import verify_token
from app.utils import get_current_time
from app.repositories.conversation import store_conversation
from app.repositories.models.conversation import ContentModel, MessageModel
from app.routes.schemas.conversation import ChatInput
from app.usecases.chat import prepare_conversation, trace_to_root
from app.bedrock import compose_args_for_converse_api
from app.stream import ConverseApiStreamHandler

log = logging.getLogger(__name__)
_sessions: Dict[str, List[str]] = {}
_user_ids: Dict[str, str] = {}

def _mgmt_client(event):
    domain = event["requestContext"]["domainName"]
    stage  = event["requestContext"]["stage"]
    return boto3.client("apigatewaymanagementapi", endpoint_url=f"https://{domain}/{stage}")

def _reply(event, payload: Any):
    """Responde en JSON."""
    data = payload if isinstance(payload, (bytes, bytearray)) else json.dumps(payload).encode("utf-8")
    _mgmt_client(event).post_to_connection(ConnectionId=event["requestContext"]["connectionId"], Data=data)

def _reply_text(event, text: str):
    """Responde texto plano (lo que espera el front para START/CHUNK)."""
    _mgmt_client(event).post_to_connection(ConnectionId=event["requestContext"]["connectionId"], Data=text.encode("utf-8"))

def _infer_format(mime: str) -> str:
    mime = (mime or "").lower()
    if "pdf" in mime: return "pdf"
    if "csv" in mime: return "csv"
    if "excel" in mime or "spreadsheet" in mime or mime.endswith("sheet"): return "xlsx"
    if "word" in mime or "document" in mime: return "docx"
    if mime.startswith("text/"): return "txt"
    return "binary"

def handler(event, context):
    route = event["requestContext"]["routeKey"]   # "$connect" | "$disconnect" | START | CHUNK | END | "$default"
    cid   = event["requestContext"]["connectionId"]

    if route == "$connect":
        _sessions[cid] = []
        _user_ids[cid] = "ws-user"
        return {"statusCode": 200}

    if route == "$disconnect":
        _sessions.pop(cid, None)
        _user_ids.pop(cid, None)
        return {"statusCode": 200}

    body = {}
    if event.get("body"):
        try:
            body = json.loads(event["body"])
        except Exception:
            body = {}

    step = route if route not in ("$default",) else (body.get("step") or "MESSAGE")

    # --- START ---
    if step == "START":
        token = body.get("token")
        try:
            _user_ids[cid] = verify_token(token)["sub"] if token else "ws-user"
        except Exception:
            _user_ids[cid] = "ws-user"
        _reply_text(event, "Session started.")
        return {"statusCode": 200}

    # --- CHUNK ---
    if step == "CHUNK":
        _sessions.setdefault(cid, []).append(body.get("part", ""))
        _reply_text(event, "Message part received.")
        return {"statusCode": 200}

    # --- END ---
    if step == "END":
        try:
            full_message = "".join(_sessions.get(cid, []))
            _sessions[cid] = []

            try:
                parsed = json.loads(full_message)
            except Exception as e:
                log.exception("BAD_PAYLOAD en END")
                _reply(event, {"status": "ERROR", "message": f"BAD_PAYLOAD: {str(e)}"})
                return {"statusCode": 200}

            # -------- Normalizaciones obligatorias --------
            msg = parsed.setdefault("message", {})
            if not msg.get("parentMessageId"):
                msg["parentMessageId"] = "system"   # requerido por ChatInput
            if not parsed.get("conversationId"):
                parsed["conversationId"] = str(ULID())

            # --- Adjuntos desde raíz y desde message.content (compat) ---
            uploaded_files: List[Dict[str, Any]] = []
            try:
                for a in (parsed.get("attachments") or []):
                    if a and a.get("base64"):
                        uploaded_files.append({
                            "name": a.get("name") or "archivo.pdf",
                            "mimeType": a.get("mimeType") or "application/pdf",
                            "base64": a["base64"],
                        })

                for c in (msg.get("content") or []):
                    if c.get("contentType") == "textAttachment" and c.get("body"):
                        uploaded_files.append({
                            "name": c.get("fileName") or "archivo.pdf",
                            "mimeType": c.get("mimeType") or c.get("mediaType") or "application/pdf",
                            "base64": c["body"],
                        })
            except Exception:
                log.exception("Error recolectando adjuntos")

            attachments = []
            for f in uploaded_files:
                try:
                    attachments.append({
                        "format": _infer_format(f.get("mimeType")),
                        "source": {"bytes": base64.b64decode(f["base64"])},
                    })
                except Exception:
                    log.exception("Adjunto corrupto, ignorado")

            # ---- ChatInput y preparación de conversación ----
            try:
                chat_input = ChatInput(**parsed)
            except Exception as e:
                log.exception("CHAT_INPUT_VALIDATION")
                _reply(event, {"status": "ERROR", "message": f"CHAT_INPUT_VALIDATION: {str(e)}"})
                return {"statusCode": 200}

            user_id = _user_ids.get(cid, "ws-user")

            try:
                user_msg_id, conversation, bot = prepare_conversation(user_id, chat_input)
            except Exception as e:
                log.exception("PREPARE_CONVERSATION")
                _reply(event, {"status": "ERROR", "message": f"PREPARE_CONVERSATION: {str(e)}"})
                return {"statusCode": 200}

            try:
                store_conversation(user_id, conversation)  # best effort
            except Exception:
                log.exception("store_conversation inicial falló (continuo)")

            message_map = conversation.message_map
            messages = trace_to_root(node_id=user_msg_id, message_map=message_map)

            try:
                args = compose_args_for_converse_api(
                    messages=messages,
                    model=chat_input.message.model,
                    instruction=(message_map["instruction"].content[0].body if "instruction" in message_map else None),
                    generation_params=(bot.generation_params if bot else None),
                    grounding_source=None,
                    guardrail=(bot.bedrock_guardrails if bot else None),
                    attachments=attachments,
                )
                # Forzar streaming real desde Bedrock Converse
                args["stream"] = True
            except Exception as e:
                log.exception("COMPOSE_ARGS")
                _reply(event, {"status": "ERROR", "message": f"COMPOSE_ARGS: {str(e)}"})
                return {"statusCode": 200}

            # Señal de prefetch/conocimiento
            _reply(event, {"status": "FETCHING_KNOWLEDGE"})

            # --- Callbacks de streaming ---
            def _on_stream(token: str):
                _reply(event, {"status": "STREAMING", "completion": token or ""})

            def _on_stop(arg):
                nonlocal conversation, user_msg_id
                try:
                    if not chat_input.continue_generate:
                        assistant_msg_id = str(ULID())
                        message = MessageModel(
                            role="assistant",
                            content=[ContentModel(content_type="text", body=arg.full_token, media_type=None, file_name=None)],
                            model=chat_input.message.model,
                            children=[], parent=user_msg_id, create_time=get_current_time(),
                            feedback=None, used_chunks=None, thinking_log=None,
                        )
                        conversation.message_map[assistant_msg_id] = message
                        conversation.message_map[user_msg_id].children.append(assistant_msg_id)
                        conversation.last_message_id = assistant_msg_id
                    else:
                        conversation.message_map[conversation.last_message_id].content[0].body += arg.full_token  # type: ignore

                    conversation.total_price += arg.price
                    conversation.should_continue = (arg.stop_reason == "max_tokens")
                    try:
                        store_conversation(user_id, conversation)
                    except Exception:
                        log.exception("store_conversation final falló")
                finally:
                    _reply(event, {
                        "status": "STREAMING_END",
                        "stop_reason": getattr(arg, "stop_reason", None),
                        "conversationId": conversation.id,
                        "messageId": conversation.last_message_id,
                    })

            handler = ConverseApiStreamHandler(
                model=chat_input.message.model,
                on_stream=_on_stream,
                on_stop=_on_stop,
            )

            try:
                for _ in handler.run(args):
                    pass
            except Exception as e:
                log.exception("BEDROCK_STREAM")
                _reply(event, {"status": "ERROR", "message": f"BEDROCK_STREAM: {str(e)}"})
                return {"statusCode": 200}

            return {"statusCode": 200}

        except Exception as e:
            log.error("UNEXPECTED en END: %s", e)
            log.error(traceback.format_exc())
            _reply(event, {"status": "ERROR", "message": f"UNEXPECTED: {str(e)}"})
            return {"statusCode": 200}

    # $default u otra cosa (eco de diagnóstico)
    _reply(event, {"ok": True, "echo": body})
    return {"statusCode": 200}
