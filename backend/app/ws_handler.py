# app/ws_handler.py
import os, json, base64, logging, traceback, re
import boto3
from typing import Dict, List, Any, Optional, Tuple
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

# === Config ===
S3_BUCKET = os.environ.get("LARGE_PAYLOAD_SUPPORT_BUCKET")
if not S3_BUCKET:
    raise RuntimeError("LARGE_PAYLOAD_SUPPORT_BUCKET no está configurado")

WS_SESSION_PREFIX = os.environ.get("WS_SESSION_PREFIX", "ws-sessions/")  # para mapear connectionId -> sub

s3 = boto3.client("s3")

# Cache en memoria (best-effort). En Lambda puede perderse entre invocaciones.
_user_ids: Dict[str, str] = {}

# --- helpers ---
# Acepta metadatos extra y saltos de línea en la parte de datos
_DATA_URL_RE = re.compile(r'^data:([^,]+),([\s\S]+)$', re.IGNORECASE)
_SAFE_NAME_RE = re.compile(r'[^A-Za-z0-9.\- _()\[\]]+')

def _mgmt_client(event):
    domain = event["requestContext"]["domainName"]
    stage  = event["requestContext"]["stage"]
    return boto3.client("apigatewaymanagementapi", endpoint_url=f"https://{domain}/{stage}")

def _reply(event, payload: Any):
    data = payload if isinstance(payload, (bytes, bytearray)) else json.dumps(payload).encode("utf-8")
    _mgmt_client(event).post_to_connection(ConnectionId=event["requestContext"]["connectionId"], Data=data)

def _reply_text(event, text: str):
    _mgmt_client(event).post_to_connection(ConnectionId=event["requestContext"]["connectionId"], Data=text.encode("utf-8"))

def _infer_format(mime: str) -> str:
    mime = (mime or "").lower()
    if "pdf"  in mime: return "pdf"
    if "csv"  in mime: return "csv"
    if "excel" in mime or "spreadsheet" in mime or mime.endswith("sheet"): return "xlsx"
    if "word" in mime or "document" in mime: return "docx"
    if "png"  in mime: return "png"
    if "jpeg" in mime or "jpg" in mime: return "jpeg"
    if "webp" in mime: return "webp"
    if "gif"  in mime: return "gif"
    if "tiff" in mime or "tif" in mime: return "tiff"
    if mime.startswith("text/"): return "txt"
    return "binary"

def _pick_mime(*candidates: Optional[str]) -> str:
    for c in candidates:
        if c and isinstance(c, str):
            return c
    return "application/octet-stream"

def _strip_data_url(maybe_data_url: Optional[str], mime_hint: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """
    Si es data URL, devuelve (mime, base64_sin_espacios). Si no, devuelve (mime_hint, string_original).
    Acepta meta como: data:application/pdf;base64,... o data:image/png;name=x;base64,...
    """
    if not isinstance(maybe_data_url, str):
        return (mime_hint or "application/octet-stream", maybe_data_url)
    m = _DATA_URL_RE.match(maybe_data_url)
    if m:
        meta = m.group(1) or ""
        data = m.group(2) or ""
        mime = mime_hint or "application/octet-stream"
        is_b64 = False
        for part in meta.split(";"):
            p = part.strip()
            if "/" in p and mime == "application/octet-stream":
                mime = p
            if p.lower() == "base64":
                is_b64 = True
        if is_b64:
            # Quita espacios/saltos de línea que algunos encoders insertan
            data = re.sub(r"\s+", "", data)
            return (mime, data)
        # Si no es base64, no lo usamos aquí
        return (mime, None)
    return (mime_hint or "application/octet-stream", maybe_data_url)

def _safe_name(name: Optional[str]) -> str:
    n = name or "archivo.bin"
    n = _SAFE_NAME_RE.sub("_", n)
    return n[:120]

def _persist_uploads(conv_id: str, msg_id: str, files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Sube bytes a S3 y devuelve referencias livianas para guardar en la conversación.
    Retorna dicts con: contentType, fileName, mediaType, url (s3://bucket/key)
    """
    refs: List[Dict[str, Any]] = []
    for f in files:
        try:
            b64 = f.get("base64") or ""
            if isinstance(b64, str) and b64.startswith("data:"):
                # Normaliza por si llegó de nuevo con header
                mime2, b64n = _strip_data_url(b64, f.get("mimeType"))
                if b64n:
                    b64 = b64n
                    if mime2 and not f.get("mimeType"):
                        f["mimeType"] = mime2
            raw = base64.b64decode(b64)
            mime = _pick_mime(f.get("mimeType"), f.get("mediaType"))
            name = _safe_name(f.get("name"))
            key  = f"uploads/{conv_id}/{msg_id}/{str(ULID())}_{name}"
            s3.put_object(Bucket=S3_BUCKET, Key=key, Body=raw, ContentType=mime)

            kind = _infer_format(mime)
            ct   = "image" if kind in ("png", "jpeg", "webp", "gif", "tiff") else "textAttachment"

            refs.append({
                "contentType": ct,
                "fileName": name,
                "mediaType": mime,
                "url": f"s3://{S3_BUCKET}/{key}",
            })
        except Exception:
            log.exception("No se pudo subir adjunto, se ignora")
    return refs

def _is_data_uri(s: Optional[str]) -> bool:
    return isinstance(s, str) and s.startswith("data:")

# === Persistencia de sesión (connectionId -> sub) en S3 ===
def _sess_key(cid: str) -> str:
    return f"{WS_SESSION_PREFIX}{cid}.json"

def _save_user_for_cid(cid: str, sub: str):
    _user_ids[cid] = sub
    try:
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=_sess_key(cid),
            Body=json.dumps({"sub": sub}).encode("utf-8"),
            ContentType="application/json",
        )
    except Exception:
        log.exception("No se pudo persistir sesión WS en S3")

def _get_user_for_cid(cid: str) -> str:
    u = _user_ids.get(cid)
    if u:
        return u
    try:
        obj  = s3.get_object(Bucket=S3_BUCKET, Key=_sess_key(cid))
        data = json.loads(obj["Body"].read().decode("utf-8"))
        sub  = data.get("sub") or "ws-user"
        _user_ids[cid] = sub
        return sub
    except Exception:
        return "ws-user"

def _delete_user_for_cid(cid: str):
    _user_ids.pop(cid, None)
    try:
        s3.delete_object(Bucket=S3_BUCKET, Key=_sess_key(cid))
    except Exception:
        pass

# === Persistencia de CHUNKs en S3 ===
def _prefix(cid: str) -> str:
    return f"ws-parts/{cid}/current/"

def _key_for_index(cid: str, index: Optional[int]) -> str:
    if index is None:
        return _prefix(cid) + f"seq-{str(ULID())}.part"
    return _prefix(cid) + f"{index:08d}.part"

def _clear_prefix(cid: str):
    pref = _prefix(cid)
    try:
        resp = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=pref)
        if resp.get("KeyCount"):
            to_del = [{"Key": o["Key"]} for o in resp.get("Contents", [])]
            s3.delete_objects(Bucket=S3_BUCKET, Delete={"Objects": to_del})
    except Exception:
        log.exception("No se pudo limpiar prefix %s", pref)

def _store_part(cid: str, index: Optional[int], part: str):
    key = _key_for_index(cid, index)
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=part.encode("utf-8"), ContentType="application/json")

def _reassemble(cid: str) -> str:
    pref = _prefix(cid)
    parts: List[Tuple[int, str, str]] = []  # (sort_key, key, body)
    resp = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=pref)
    for obj in resp.get("Contents", []):
        key = obj["Key"]
        try:
            body = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read().decode("utf-8")
            m = re.search(r"/(\d{8})\.part$", key)
            sort_key = int(m.group(1)) if m else 10**9  # los seq-* al final
            parts.append((sort_key, key, body))
        except Exception:
            log.exception("Error leyendo parte %s", key)
    parts.sort(key=lambda t: t[0])
    full = "".join(p[2] for p in parts)
    if parts:
        try:
            s3.delete_objects(Bucket=S3_BUCKET, Delete={"Objects": [{"Key": p[1]} for p in parts]})
        except Exception:
            log.exception("No se pudo limpiar partes tras ensamblar")
    return full

def handler(event, context):
    route = event["requestContext"]["routeKey"]   # "$connect" | "$disconnect" | START | CHUNK | END | "$default"
    cid   = event["requestContext"]["connectionId"]

    if route == "$connect":
        # Conectar no trae body ni token; se setea por START
        _user_ids[cid] = "ws-user"
        return {"statusCode": 200}

    if route == "$disconnect":
        _delete_user_for_cid(cid)
        _clear_prefix(cid)  # best-effort
        return {"statusCode": 200}

    # Cuerpo del frame
    raw_body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            raw_body = base64.b64decode(raw_body or b"").decode("utf-8", errors="ignore")
        except Exception:
            raw_body = ""

    body: Dict[str, Any] = {}
    if isinstance(raw_body, str) and raw_body:
        try:
            body = json.loads(raw_body)
        except Exception:
            body = {}

    step = route if route not in ("$default",) else (body.get("step") or "MESSAGE")

    # --- START ---
    if step == "START":
        token = body.get("token")
        try:
            sub = verify_token(token)["sub"] if token else "ws-user"
        except Exception:
            sub = "ws-user"
        _save_user_for_cid(cid, sub)   # persistente (S3 + cache)
        _clear_prefix(cid)             # limpia restos previos de CHUNKs
        _reply_text(event, "Session started.")
        return {"statusCode": 200}

    # --- CHUNK ---
    if step == "CHUNK":
        part = body.get("part", "")
        idx  = body.get("index")
        try:
            idx_int = int(idx) if idx is not None else None
        except Exception:
            idx_int = None

        try:
            _store_part(cid, idx_int, part)
            if idx_int is not None:
                log.info(f"[WS] CHUNK idx={idx_int} len={len(part)}")
            else:
                log.info(f"[WS] CHUNK (compat) len={len(part)}")
        except Exception:
            log.exception("No se pudo guardar chunk en S3 (cid=%s, idx=%s)", cid, idx)

        _reply_text(event, "Message part received.")
        return {"statusCode": 200}

    # --- END ---
    if step == "END":
        try:
            full_message = _reassemble(cid).strip()
            log.info(f"[WS] FULL MESSAGE len={len(full_message)}")
            if not full_message:
                _reply(event, {"status": "ERROR", "message": "BAD_PAYLOAD: EMPTY"})
                return {"statusCode": 200}

            try:
                parsed = json.loads(full_message)
            except Exception as e:
                log.exception("BAD_PAYLOAD en END")
                preview = full_message[:120].replace("\n", "\\n")
                _reply(event, {"status": "ERROR", "message": f"BAD_PAYLOAD: {str(e)}", "preview": preview})
                return {"statusCode": 200}

            # -------- Normalizaciones obligatorias --------
            msg = parsed.setdefault("message", {})
            if not msg.get("parentMessageId"):
                msg["parentMessageId"] = "system"
            if not parsed.get("conversationId"):
                parsed["conversationId"] = str(ULID())

            # --- Adjuntos (raíz + content: textAttachment/file/document/image) ---
            uploaded_files: List[Dict[str, Any]] = []
            try:
                # 1) attachments en raíz
                for a in (parsed.get("attachments") or []):
                    if not a:
                        continue
                    name = a.get("name") or "archivo.bin"
                    mime = _pick_mime(a.get("mimeType"), a.get("mediaType"))
                    raw  = a.get("base64") or a.get("body") or a.get("data") or a.get("url") or ""
                    mime, b64 = _strip_data_url(raw, mime)
                    if b64:
                        uploaded_files.append({"name": name, "mimeType": mime, "base64": b64})

                # 2) items en message.content
                for c in (msg.get("content") or []):
                    ct = (c.get("contentType") or "").lower()
                    if ct in ("textattachment", "file", "document"):
                        name = c.get("fileName") or c.get("name") or "archivo.bin"
                        mime = _pick_mime(c.get("mimeType"), c.get("mediaType"))
                        raw  = c.get("body") or c.get("base64") or c.get("data") or c.get("url") or ""
                        mime, b64 = _strip_data_url(raw, mime)
                        if b64:
                            uploaded_files.append({"name": name, "mimeType": mime, "base64": b64})
                    elif ct in ("image", "input_image", "image_file"):
                        name = c.get("fileName") or c.get("name") or "imagen.png"
                        mime = _pick_mime(c.get("mimeType"), c.get("mediaType"))
                        raw  = c.get("body") or c.get("base64") or c.get("data") or c.get("url")
                        mime, b64 = _strip_data_url(raw, mime)
                        if b64:
                            uploaded_files.append({"name": name, "mimeType": mime, "base64": b64})
            except Exception:
                log.exception("Error recolectando adjuntos")

            # Attachments para Bedrock (se usan sólo para la llamada, no se persisten)
            attachments = []
            for f in uploaded_files:
                try:
                    attachments.append({
                        "format": _infer_format(f.get("mimeType")),
                        "source": {"bytes": base64.b64decode(f["base64"])},
                    })
                except Exception:
                    log.exception("Adjunto corrupto, ignorado")
            log.info(f"[WS] Adjuntos recogidos: {len(attachments)}")

            # ---- ChatInput y preparación de conversación (SIN limpiar nada antes) ----
            try:
                chat_input = ChatInput(**parsed)
            except Exception as e:
                log.exception("CHAT_INPUT_VALIDATION")
                _reply(event, {"status": "ERROR", "message": f"CHAT_INPUT_VALIDATION: {str(e)}"})
                return {"statusCode": 200}

            # Resolver user_id de forma robusta (puede haberse perdido la cache del contenedor)
            user_id = _get_user_for_cid(cid)
            if user_id == "ws-user":
                # fallback: intenta token del payload o headers
                tok = (parsed.get("token") if isinstance(parsed, dict) else None) \
                      or (event.get("headers") or {}).get("Authorization") \
                      or (event.get("headers") or {}).get("authorization")
                if isinstance(tok, str) and tok.lower().startswith("bearer "):
                    tok = tok.split(" ", 1)[1]
                if tok:
                    try:
                        user_id = verify_token(tok)["sub"]
                        _save_user_for_cid(cid, user_id)
                    except Exception:
                        log.exception("TOKEN_INVALIDO_EN_END")

            try:
                user_msg_id, conversation, bot = prepare_conversation(user_id, chat_input)
            except Exception as e:
                log.exception("PREPARE_CONVERSATION")
                _reply(event, {"status": "ERROR", "message": f"PREPARE_CONVERSATION: {str(e)}"})
                return {"statusCode": 200}

            # === Aligerar el mensaje del usuario ANTES de guardar en Dynamo ===
            try:
                conv_id = conversation.id or parsed["conversationId"]
                refs = _persist_uploads(conv_id, user_msg_id, uploaded_files)

                # Reescribir el contenido del mensaje del usuario:
                umsg = conversation.message_map[user_msg_id]

                # Conserva textos y adjuntos NO-embebidos; elimina sólo data:
                cleaned_content: List[ContentModel] = []
                for item in umsg.content:
                    try:
                        ct   = getattr(item, "content_type", None)
                        body = getattr(item, "body", None)
                        if ct == "text":
                            cleaned_content.append(item)
                        elif ct in ("image", "textAttachment", "file", "document"):
                            if isinstance(body, str) and body.startswith("data:"):
                                # lo saltamos (pesado), se reemplazará por refs S3
                                continue
                            cleaned_content.append(item)
                        else:
                            cleaned_content.append(item)
                    except Exception:
                        cleaned_content.append(item)

                # Agrega refs nuevas (orden no crítico; van al final)
                for r in refs:
                    cleaned_content.append(
                        ContentModel(
                            content_type=r["contentType"],
                            body=r["url"],                 # s3://..., NO base64
                            media_type=r["mediaType"],
                            file_name=r["fileName"],
                        )
                    )

                umsg.content = cleaned_content
            except Exception:
                log.exception("No se pudieron persistir/adjuntar referencias")

            # Guardado inicial (ya sin base64)
            try:
                store_conversation(user_id, conversation)
            except Exception:
                log.exception("store_conversation inicial falló (continuo)")

            # --- Preparar llamada a Bedrock ---
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
                args["stream"] = True
            except Exception as e:
                log.exception("COMPOSE_ARGS")
                _reply(event, {"status": "ERROR", "message": f"COMPOSE_ARGS: {str(e)}"})
                return {"statusCode": 200}

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
