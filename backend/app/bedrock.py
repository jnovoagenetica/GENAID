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
    guardrailIdentifier: str
    guardrailVersion: str
    trace: str
    streamProcessingMode: NotRequired[str]


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
    logger.warning(
        "compose_args is deprecated. Use compose_args_for_converse_api instead."
    )
    return dict(
        compose_args_for_converse_api(
            messages, model, instruction, stream, generation_params
        )
    )


def _get_converse_supported_format(ext: str | None) -> str | None:
    if not ext:
        return None
    supported_formats = {
        "pdf": "pdf",
        "csv": "csv",
        "doc": "doc",
        "docx": "docx",
        "xls": "xls",
        "xlsx": "xlsx",
        "html": "html",
        "txt": "txt",
        "md": "md",
    }
    return supported_formats.get(ext.lower())


def _sanitize_bedrock_doc_name(file_name: str) -> str:
    try:
        base = Path(file_name).stem
    except Exception:
        base = file_name or "Document"

    base = re.sub(r"[._]+", " ", base)
    base = re.sub(r"[^A-Za-z0-9 \-\(\)\[\]]+", " ", base)
    base = re.sub(r"\s+", " ", base).strip()

    if not base:
        base = "Document"

    return base[:100]


def _guess_format_from_mime(mime: str | None) -> str | None:
    if not mime:
        return None
    mt = mime.lower()
    if mt == "application/pdf":
        return "pdf"
    if mt in ("text/csv",):
        return "csv"
    if mt in ("text/html",):
        return "html"
    if mt in ("text/plain",):
        return "txt"
    if mt in ("text/markdown", "text/x-markdown"):
        return "md"
    if mt in (
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        return "docx"
    if mt in (
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ):
        return "xlsx"
    return None


def compose_args_for_converse_api(
    messages: list[MessageModel],
    model: type_model_name,
    instruction: str | None = None,
    stream: bool = False,
    generation_params: GenerationParamsModel | None = None,
    grounding_source: dict | None = None,
    guardrail: BedrockGuardrailsModel | None = None,
    attachments: list[dict] | None = None,
) -> ConverseApiRequest:
    def process_content(c: ContentModel, role: str):
        # TEXT
        if c.content_type == "text":
            if (
                role == "user"
                and guardrail
                and guardrail.grounding_threshold > 0
                and grounding_source
            ):
                return [
                    {"guardContent": grounding_source},
                    {
                        "guardContent": {
                            "text": {"text": c.body, "qualifiers": ["query"]}
                        }
                    },
                ]
            return [{"text": c.body}] if isinstance(c.body, str) else []

        # IMAGE
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

        # DOCUMENT / ATTACHMENT
        elif c.content_type == "textAttachment":
            try:
                file_bytes = base64.b64decode(c.body)
                guessed_fmt = None
                if c.media_type and "/" in c.media_type:
                    mt = c.media_type.split("/")[-1].lower()
                    if mt in ["pdf", "csv", "html", "txt", "md"]:
                        guessed_fmt = mt
                    elif mt in [
                        "msword",
                        "vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ]:
                        guessed_fmt = "docx"
                    elif mt in [
                        "vnd.ms-excel",
                        "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ]:
                        guessed_fmt = "xlsx"

                if not guessed_fmt and c.file_name:
                    ext = c.file_name.split(".")[-1].lower()
                    guessed_fmt = _get_converse_supported_format(ext)
                if not guessed_fmt:
                    guessed_fmt = "pdf"

                clean_name = _sanitize_bedrock_doc_name(c.file_name or "Document")
                logger.info(
                    "Adjuntando documento: name='%s' format='%s' size=%d",
                    clean_name,
                    guessed_fmt,
                    len(file_bytes),
                )
                return [
                    {
                        "document": {
                            "format": guessed_fmt,
                            "name": clean_name,
                            "source": {"bytes": file_bytes},
                        }
                    }
                ]
            except Exception as e:
                logger.error(
                    f"Error al decodificar el archivo adjunto '{c.file_name}': {e}"
                )
                return []

        else:
            raise NotImplementedError(f"Unsupported content type: {c.content_type}")

    arg_messages: list[dict] = []
    for message in messages:
        if message.role in ["system", "instruction"]:
            continue

        content_blocks: list[dict] = []
        for c in message.content:
            blocks = process_content(c, message.role)
            content_blocks.extend(blocks)

        if content_blocks:
            arg_messages.append({"role": message.role, "content": content_blocks})

    def _doc_block(name: str, fmt: str, raw: bytes) -> dict:
        return {"document": {"format": fmt, "name": name, "source": {"bytes": raw}}}

    root_doc_blocks = []
    for f in (attachments or []):
        b64 = f.get("base64") or ""
        if not b64:
            continue
        try:
            raw = base64.b64decode(b64)
            original_file_name = f.get("name") or ""
            name = _sanitize_bedrock_doc_name(original_file_name or "Document")
            fmt = (
                _guess_format_from_mime(f.get("mimeType"))
                or (
                    original_file_name.rsplit(".", 1)[-1].lower()
                    if "." in original_file_name
                    else None
                )
            )
            fmt = _get_converse_supported_format(fmt) if fmt else "pdf"

            logger.info(
                "Adjuntando documento (raíz): name='%s' format='%s' size=%d",
                name,
                fmt,
                len(raw),
            )
            root_doc_blocks.append(_doc_block(name, fmt, raw))
        except Exception as e:
            logger.warning(
                "No se pudo decodificar base64 para %s: %s",
                f.get("name"),
                e,
            )

    if root_doc_blocks:
        if not arg_messages or arg_messages[-1]["role"] != "user":
            arg_messages.append({"role": "user", "content": []})
        arg_messages[-1]["content"].extend(root_doc_blocks)

    try:
        msg_summary = []
        for m in arg_messages:
            block_types = [list(b.keys())[0] for b in m["content"]]
            msg_summary.append({"role": m["role"], "blocks": block_types})
        logger.info("[ConverseArgs] Mensajes: %s", msg_summary)
    except Exception:
        logger.exception("[ConverseArgs] No pude resumir mensajes")

     # ================== INICIO BLOQUE AJUSTADO (Anthropic) ==================
    inference_config = {
        **DEFAULT_GENERATION_CONFIG,
        "maxTokens": 4096,
        **(
            {
                "temperature": generation_params.temperature,
                # Ojo: aquí usamos la clave camel (topP) si viene desde params;
                # pero DEFAULT_GENERATION_CONFIG podría traer 'top_p' (snake) o 'topP' (camel)
                "topP": generation_params.top_p,
                "stopSequences": generation_params.stop_sequences,
            }
            if generation_params
            else {}
        ),
    }

    # Mover top_k a additional_model_request_fields si viniera en DEFAULT_GENERATION_CONFIG
    additional_model_request_fields = {}
    # top_k puede venir en snake o camel; cubrimos ambos
    if "top_k" in inference_config:
        additional_model_request_fields["top_k"] = inference_config.pop("top_k")
    if "topK" in inference_config:
        additional_model_request_fields["top_k"] = inference_config.pop("topK")

    # Si el modelo es Anthropic (claude-*), no enviar additional_model_request_fields (evita top_k y otros no soportados)
    if isinstance(model, str) and model.startswith("claude-"):
        additional_model_request_fields = {}

    # Sanitizar combinaciones no soportadas por Claude 4.5:
    # quitar topP/top_p si también hay temperature
    def _sanitize_inference_config_for_model(model_name: type_model_name, cfg: dict) -> dict:
        cfg = dict(cfg)
        is_anthropic = isinstance(model_name, str) and model_name.startswith("claude-")
        if is_anthropic:
            has_temp = "temperature" in cfg and cfg["temperature"] is not None
            if has_temp:
                # Eliminar ambas variantes si existen
                if "topP" in cfg:
                    cfg.pop("topP", None)
                if "top_p" in cfg:
                    cfg.pop("top_p", None)
        return cfg

    inference_config = _sanitize_inference_config_for_model(model, inference_config)
    # ================== FIN BLOQUE AJUSTADO (Anthropic) ======================

    if any(any("document" in b for b in m["content"]) for m in arg_messages):
        extra_instruction = (
            "Analiza el/los archivo(s) PDF adjunto(s) y responde a la solicitud del usuario."
        )
        instruction = (
            instruction + " " + extra_instruction if instruction else extra_instruction
        )

    args: ConverseApiRequest = {
        "inference_config": convert_dict_keys_to_camel_case(inference_config),
        "additional_model_request_fields": additional_model_request_fields,
        "model_id": get_model_id(model),
        "messages": arg_messages,
        "stream": stream,
        "system": [{"text": instruction}] if instruction else [],
    }

    if guardrail and guardrail.guardrail_arn and guardrail.guardrail_version:
        args["guardrailConfig"] = {
            "guardrailIdentifier": guardrail.guardrail_arn,
            "guardrailVersion": guardrail.guardrail_version,
            "trace": "enabled",
        }
        if stream:
            args["guardrailConfig"]["streamProcessingMode"] = "async"

    safe_args = json.loads(json.dumps(args, default=lambda o: "<bytes>"))
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

    logger.info("Llamando a converse API...")
    try:
        resp = client.converse(**base_args)
        try:
            meta = resp.get("ResponseMetadata", {})
            stop = resp.get("stopReason", "")
            usage = resp.get("usage", {})
            logger.info(
                "[ConverseResp] HTTP=%s stopReason=%s usage=%s requestId=%s",
                meta.get("HTTPStatusCode"),
                stop,
                usage,
                meta.get("RequestId"),
            )
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
    """
    Mapeo interno -> modelId aceptado por Bedrock Converse/ConverseStream.
    - Modelos on-demand clásicos: foundation model id.
    - Claude 4.5 Sonnet: requiere Inference Profile (ID system-defined por región
      o ARN/ID provisto por env BEDROCK_MODEL_ID_OVERRIDE).
    """
    # Permite override manual (ARN/ID) para cualquier modelo
    override = os.environ.get("BEDROCK_MODEL_ID_OVERRIDE")
    if override:
        return override

    region = os.environ.get("BEDROCK_REGION", "us-east-1").lower()
    is_us = region.startswith("us-")
    is_eu = region.startswith("eu-")

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

    elif model == "claude-v4.5-sonnet":
        # Claude 4.5 Sonnet SOLO vía Inference Profile
        if is_us:
            return "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        elif is_eu:
            return "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
        else:
            # fallback seguro a US
            return "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

    elif model == "mistral-7b-instruct":
        return "mistral.mistral-7b-instruct-v0:2"
    elif model == "mixtral-8x7b-instruct":
        return "mistral.mixtral-8x7b-instruct-v0:1"
    elif model == "mistral-large":
        return "mistral.mistral-large-2402-v1:0"
    else:
        raise ValueError(f"Modelo no soportado en get_model_id(): {model}")


def calculate_query_embedding(question: str) -> list[float]:
    model_id = DEFAULT_EMBEDDING_CONFIG["model_id"]
    assert model_id == "cohere.embed-multilingual-v3"
    payload = json.dumps({"texts": [question], "input_type": "search_query"})
    response = client.invoke_model(
        accept="application/json",
        contentType="application/json",
        body=payload,
        modelId=model_id,
    )
    output = json.loads(response.get("body").read())
    return output.get("embeddings")[0]


def calculate_document_embeddings(documents: list[str]) -> list[list[float]]:
    def _calculate_document_embeddings(docs: list[str]) -> list[list[float]]:
        payload = json.dumps({"texts": docs, "input_type": "search_document"})
        response = client.invoke_model(
            accept="application/json",
            contentType="application/json",
            body=payload,
            modelId=model_id,
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
