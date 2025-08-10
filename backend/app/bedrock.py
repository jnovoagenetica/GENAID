# backend/app/bedrock.py

import base64
import io
import json
import logging
import os
import re
from pathlib import Path

import fitz  # PyMuPDF
from app.config import BEDROCK_PRICING, DEFAULT_EMBEDDING_CONFIG
from app.config import DEFAULT_GENERATION_CONFIG as DEFAULT_CLAUDE_GENERATION_CONFIG
from app.config import DEFAULT_MISTRAL_GENERATION_CONFIG
from app.repositories.models.conversation import ContentModel, MessageModel
from app.repositories.models.custom_bot import GenerationParamsModel
from app.repositories.models.custom_bot_guardrails import BedrockGuardrailsModel
from app.routes.schemas.conversation import type_model_name
from app.utils import convert_dict_keys_to_camel_case, get_bedrock_runtime_client
from typing_extensions import NotRequired, TypedDict

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-east-1")
ENABLE_MISTRAL = os.environ.get("ENABLE_MISTRAL", "") == "true"
DEFAULT_GENERATION_CONFIG = (
    DEFAULT_MISTRAL_GENERATION_CONFIG
    if ENABLE_MISTRAL
    else DEFAULT_CLAUDE_GENERATION_CONFIG
)

client = get_bedrock_runtime_client()


class GuardrailConfig(TypedDict):
    # ... (otras definiciones de tipos)
    guardrailIdentifier: str
    guardrailVersion: str
    trace: str
    streamProcessingMode: NotRequired[str]

# --- INICIO DE CAMBIOS EN TIPOS ---
# Actualizamos los tipos para que coincidan con el formato de la API Converse
class ConverseApiSource(TypedDict):
    bytes: bytes

class ConverseApiAttachment(TypedDict):
    name: str
    format: str # ej: "pdf", "jpeg"
    source: ConverseApiSource
# --- FIN DE CAMBIOS EN TIPOS ---

class ConverseApiToolSpec(TypedDict):
    name: str
    description: str
    inputSchema: dict


class ConverseApiToolConfig(TypedDict):
    tools: list[ConverseApiToolSpec]
    toolChoice: dict


class ConverseApiToolResultContent(TypedDict):
    json: NotRequired[dict]
    text: NotRequired[str]


class ConverseApiToolResult(TypedDict):
    toolUseId: str
    content: ConverseApiToolResultContent
    status: NotRequired[str]

class ConverseApiRequest(TypedDict):
    inference_config: dict
    additional_model_request_fields: dict
    model_id: str
    messages: list[dict]
    stream: bool
    system: list[dict]
    attachments: NotRequired[list[ConverseApiAttachment]]
    guardrailConfig: NotRequired[GuardrailConfig]
    tool_config: NotRequired[ConverseApiToolConfig]


class ConverseApiToolUseContent(TypedDict):
    toolUseId: str
    name: str
    input: dict


class ConverseApiResponseMessageContent(TypedDict):
    text: NotRequired[str]
    toolUse: NotRequired[ConverseApiToolUseContent]


class ConverseApiResponseMessage(TypedDict):
    content: list[ConverseApiResponseMessageContent]
    role: str


class ConverseApiResponseOutput(TypedDict):
    message: ConverseApiResponseMessage


class ConverseApiResponseUsage(TypedDict):
    inputTokens: int
    outputTokens: int
    totalTokens: int


class ConverseApiResponse(TypedDict):
    ResponseMetadata: dict
    output: ConverseApiResponseOutput
    stopReason: str
    usage: ConverseApiResponseUsage


def compose_args(
    messages: list[MessageModel],
    model: type_model_name,
    instruction: str | None = None,
    stream: bool = False,
    generation_params: GenerationParamsModel | None = None,
) -> dict:
    # --- CAMBIO: logger.warn -> logger.warning ---
    logger.warning(
        "compose_args is deprecated. Use compose_args_for_converse_api instead."
    )
    return dict(
        compose_args_for_converse_api(
            messages, model, instruction, stream, generation_params
        )
    )


def _get_converse_supported_format(ext: str) -> str:
    supported_formats = {
        "pdf": "pdf", "csv": "csv", "doc": "doc", "docx": "docx",
        "xls": "xls", "xlsx": "xlsx", "html": "html", "txt": "txt", "md": "md",
    }
    return supported_formats.get(ext, "txt")


def _convert_to_valid_file_name(file_name: str) -> str:
    file_name = re.sub(r"[^a-zA-Z0-9\s\-\(\)\[\]\.]", "", file_name)
    file_name = re.sub(r"\s+", " ", file_name)
    file_name = file_name.strip()
    return file_name


# --- NUEVO helper: convertir root attachments {name,mimeType,base64} -> Converse ---
def _guess_format_from_mime(mime: str | None) -> str | None:
    if not mime: 
        return None
    mt = mime.lower()
    # mapeo común
    if mt == "application/pdf": return "pdf"
    if mt in ("text/csv",): return "csv"
    if mt in ("text/html",): return "html"
    if mt in ("text/plain",): return "txt"
    if mt in ("text/markdown", "text/x-markdown"): return "md"
    if mt in ("application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"):
        return "docx"
    if mt in ("application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"):
        return "xlsx"
    return None

def _build_attachments_from_root(uploaded_files: list[dict] | None) -> list[dict]:
    out: list[dict] = []
    for f in uploaded_files or []:
        b64 = f.get("base64") or ""
        if not b64:
            continue
        try:
            raw = base64.b64decode(b64)
        except Exception:
            logger.warning("No se pudo decodificar base64 para %s", f)
            continue

        name = _convert_to_valid_file_name(f.get("name") or "archivo.pdf")
        fmt = _guess_format_from_mime(f.get("mimeType"))
        if not fmt and "." in name:
            fmt = _get_converse_supported_format(name.rsplit(".", 1)[-1].lower())
        if not fmt:
            fmt = "pdf"  # fallback razonable

        out.append({
            "name": name,
            "format": fmt,
            "source": {"bytes": raw},
        })
    return out


def compose_args_for_converse_api(
    messages: list[MessageModel],
    model: type_model_name,
    instruction: str | None = None,
    stream: bool = False,
    generation_params: GenerationParamsModel | None = None,
    grounding_source: dict | None = None,
    guardrail: BedrockGuardrailsModel | None = None,
    # ⬇️ NUEVO: adjuntos raíz enviados por el WS (payload.attachments)
    attachments: list[dict] | None = None,
) -> ConverseApiRequest:
    def process_content(c: ContentModel, role: str):
        # TEXT
        if c.content_type == "text":
            # --- CAMBIO: Añadido 'and grounding_source' ---
            if role == "user" and guardrail and guardrail.grounding_threshold > 0 and grounding_source:
                return [
                    {"guardContent": grounding_source},
                    {"guardContent": {"text": {"text": c.body, "qualifiers": ["query"]}}},
                ]
            return [{"text": c.body}] if isinstance(c.body, str) else []

        # IMAGE (base64 -> bytes)
        elif c.content_type == "image":
            if not isinstance(c.body, str):
                logger.error("El cuerpo de la imagen no es una cadena Base64.")
                return []
            fmt = (c.media_type.split("/")[1] if c.media_type else "jpeg").lower()
            try:
                image_bytes = base64.b64decode(c.body)
                return [{"image": {"format": fmt, "source": {"bytes": image_bytes}}}]
            except Exception as e:
                logger.error(f"Error al decodificar imagen Base64: {e}")
                return []

        # FILE (PDF, DOCX, etc.) -> marcar para attachments
        elif c.content_type == "textAttachment":
            try:
                file_bytes = base64.b64decode(c.body)
                guessed_fmt = None
                if c.media_type and "/" in c.media_type:
                    mt = c.media_type.split("/")[-1].lower()
                    if mt in ["pdf", "csv", "html", "txt", "md"]:
                        guessed_fmt = mt
                    elif mt in ["msword", "vnd.openxmlformats-officedocument.wordprocessingml.document"]:
                        guessed_fmt = "docx"
                    elif mt in ["vnd.ms-excel", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"]:
                        guessed_fmt = "xlsx"

                if not guessed_fmt and c.file_name:
                    ext = c.file_name.split(".")[-1].lower()
                    guessed_fmt = _get_converse_supported_format(ext)

                if not guessed_fmt:
                    guessed_fmt = "pdf"

                clean_name = _convert_to_valid_file_name(c.file_name or f"document.{guessed_fmt}")
                return [{"_attachment": {"name": clean_name, "format": guessed_fmt, "source": {"bytes": file_bytes}}}]
            except Exception as e:
                logger.error(f"Error al decodificar el archivo adjunto '{c.file_name}': {e}")
                return []

        else:
            raise NotImplementedError(f"Unsupported content type: {c.content_type}")

    # 1) Construir messages y attachments desde el contenido
    attachments_from_content: list[dict] = []
    arg_messages: list[dict] = []

    for message in messages:
        if message.role in ["system", "instruction"]:
            continue

        content_blocks: list[dict] = []
        for c in message.content:
            blocks = process_content(c, message.role)
            for b in blocks:
                if "_attachment" in b:
                    attachments_from_content.append(b["_attachment"])
                else:
                    content_blocks.append(b)

        if content_blocks:
            arg_messages.append({"role": message.role, "content": content_blocks})

    # 2) Construir attachments desde el payload raíz y MERGE sin duplicados
    attachments_from_root = _build_attachments_from_root(attachments)
    merged_attachments: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for a in (attachments_from_root + attachments_from_content):
        key = (a.get("name") or "", a.get("format") or "")
        if key in seen:
            continue
        seen.add(key)
        merged_attachments.append(a)

    # 🔎 LOG: adjuntos finales que irán a Bedrock
    try:
        atts_names = [a.get("name") for a in merged_attachments]
        atts_fmts  = [a.get("format") for a in merged_attachments]
        atts_sizes = [len(a.get("source", {}).get("bytes", b"")) for a in merged_attachments]
        logger.info("[ConverseArgs] Adjuntos fusionados: count=%d names=%s formats=%s sizes=%s",
                    len(merged_attachments), atts_names, atts_fmts, atts_sizes)
    except Exception:
        logger.exception("[ConverseArgs] No pude inspeccionar merged_attachments")

    # 3) Inference config
    inference_config = {
        **DEFAULT_GENERATION_CONFIG,
        "maxTokens": 4096,
        **(
            {
                "temperature": generation_params.temperature,
                "topP": generation_params.top_p,
                "stopSequences": generation_params.stop_sequences,
            }
            if generation_params
            else {}
        ),
    }
    additional_model_request_fields = {}
    if "top_k" in inference_config:
        additional_model_request_fields["top_k"] = inference_config.pop("top_k")

    # 4) Empujar instrucción útil si hay PDF(s)
    if merged_attachments:
        if any(att.get("format") == "pdf" for att in merged_attachments):
            extra_instruction = "Analiza el/los archivo(s) PDF adjunto(s) y responde a la solicitud del usuario."
            instruction = (instruction + " " + extra_instruction) if instruction else extra_instruction

    # 🔎 LOG: resumen de mensajes que van a Bedrock
    try:
        msg_summary = [{"role": m["role"], "blocks": len(m["content"])} for m in arg_messages]
        logger.info("[ConverseArgs] Mensajes: %s", msg_summary)
    except Exception:
        logger.exception("[ConverseArgs] No pude resumir mensajes")
        
    args: ConverseApiRequest = {
        "inference_config": convert_dict_keys_to_camel_case(inference_config),
        "additional_model_request_fields": additional_model_request_fields,
        "model_id": get_model_id(model),
        "messages": arg_messages,
        "stream": stream,
        "system": [{"text": instruction}] if instruction else [],
    }

    if merged_attachments:
        args["attachments"] = merged_attachments  # [{name, format, source:{bytes}}]

    if guardrail and guardrail.guardrail_arn and guardrail.guardrail_version:
        args["guardrailConfig"] = {
            "guardrailIdentifier": guardrail.guardrail_arn,
            "guardrailVersion": guardrail.guardrail_version,
            "trace": "enabled",
        }
        if stream:
            args["guardrailConfig"]["streamProcessingMode"] = "async"

    # Log seguro (sin bytes)
    safe_args = dict(args)
    if safe_args.get("attachments"):
        safe_args["attachments"] = [{k: v for k, v in a.items() if k != "source"} for a in safe_args["attachments"]]
    logger.info("=" * 50)
    logger.info("Payload Converse (sin bytes): %s", safe_args)
    logger.info("=" * 50)

    return args

def call_converse_api(args: ConverseApiRequest) -> ConverseApiResponse:
    client = get_bedrock_runtime_client()
    base_args = {
        "modelId": args["model_id"],
        "messages": args["messages"],
        "inferenceConfig": args["inference_config"],
        "system": args["system"],
        "additionalModelRequestFields": args["additional_model_request_fields"],
    }
    if "guardrailConfig" in args:
        base_args["guardrailConfig"] = args["guardrailConfig"]
    if "attachments" in args and args["attachments"]:
        base_args["attachments"] = args["attachments"]

    logger.info("Llamando a converse con %d attachment(s)", len(base_args.get("attachments", [])))
    try:
        resp = client.converse(**base_args)
        # 🔎 LOG: pequeño resumen de la respuesta (sin contenido completo)
        try:
            meta = resp.get("ResponseMetadata", {})
            stop = resp.get("stopReason", "")
            usage = resp.get("usage", {})
            logger.info("[ConverseResp] HTTP=%s stopReason=%s usage=%s requestId=%s",
                        meta.get("HTTPStatusCode"), stop, usage, meta.get("RequestId"))
        except Exception:
            logger.exception("[ConverseResp] No pude inspeccionar la respuesta")
        return resp
    except Exception as e:
        logger.exception("[Converse] Error al llamar a converse: %s", e)
        raise

def calculate_price(
    model: type_model_name,
    input_tokens: int,
    output_tokens: int,
    region: str = BEDROCK_REGION,
) -> float:
    # ... (El código de esta función se mantiene igual)
    input_price = (
        BEDROCK_PRICING.get(region, {})
        .get(model, {})
        .get("input", BEDROCK_PRICING["default"][model]["input"])
    )
    output_price = (
        BEDROCK_PRICING.get(region, {})
        .get(model, {})
        .get("output", BEDROCK_PRICING["default"][model]["output"])
    )
    return input_price * input_tokens / 1000.0 + output_price * output_tokens / 1000.0


def get_model_id(model: type_model_name) -> str:
    # ... (El código de esta función se mantiene igual)
    if model == "claude-v2":
        return "anthropic.claude-v2:1"
    elif model == "claude-instant-v1":
        return "anthropic.claude-instant-v1"
    elif model == "claude-v3-sonnet":
        return "anthropic.claude-3-sonnet-20240229-v1:0"
    elif model == "claude-v3-haiku":
        return "anthropic.claude-3-haiku-20240307-v1:0"
    elif model == "claude-v3-opus":
        return "anthropic.claude-3-opus-20240229-v1:0"
    elif model == "claude-v3.5-sonnet":
        return "anthropic.claude-3-5-sonnet-20240620-v1:0"
    elif model == "mistral-7b-instruct":
        return "mistral.mistral-7b-instruct-v0:2"
    elif model == "mixtral-8x7b-instruct":
        return "mistral.mixtral-8x7b-instruct-v0:1"
    elif model == "mistral-large":
        return "mistral.mistral-large-2402-v1:0"


def calculate_query_embedding(question: str) -> list[float]:
    # ... (El código de esta función se mantiene igual)
    model_id = DEFAULT_EMBEDDING_CONFIG["model_id"]
    assert model_id == "cohere.embed-multilingual-v3"
    payload = json.dumps({"texts": [question], "input_type": "search_query"})
    response = client.invoke_model(
        accept="application/json", contentType="application/json", body=payload, modelId=model_id
    )
    output = json.loads(response.get("body").read())
    return output.get("embeddings")[0]


def calculate_document_embeddings(documents: list[str]) -> list[list[float]]:
    # ... (El código de esta función se mantiene igual)
    def _calculate_document_embeddings(docs: list[str]) -> list[list[float]]:
        payload = json.dumps({"texts": docs, "input_type": "search_document"})
        response = client.invoke_model(
            accept="application/json", contentType="application/json", body=payload, modelId=model_id
        )
        output = json.loads(response.get("body").read())
        return output.get("embeddings")

    BATCH_SIZE = 10
    model_id = DEFAULT_EMBEDDING_CONFIG["model_id"]
    assert model_id == "cohere.embed-multilingual-v3"
    embeddings = [] 
    for i in range(0, len(documents), BATCH_SIZE):
        batch = documents[i : i + BATCH_SIZE]
        embeddings.extend(_calculate_document_embeddings(batch))
    return embeddings