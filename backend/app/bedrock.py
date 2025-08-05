# backend/app/bedrock.py (VERSIÓN CON LOGS PARA DEPURACIÓN)

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
# Aseguramos que el logger capture los mensajes de tipo INFO
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


class ConverseApiAttachment(TypedDict):
    name: str
    data: bytes
    type: str


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
    logger.warn(
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


def compose_args_for_converse_api(
    messages: list[MessageModel],
    model: type_model_name,
    instruction: str | None = None,
    stream: bool = False,
    generation_params: GenerationParamsModel | None = None,
    grounding_source: dict | None = None,
    guardrail: BedrockGuardrailsModel | None = None,
) -> ConverseApiRequest:
    def process_content(c: ContentModel, role: str):
        # 🟩 Si el contenido es texto plano, simplemente lo empaquetamos como tal
        if c.content_type == "text":
            if role == "user" and guardrail and guardrail.grounding_threshold > 0:
                return [{"guardContent": grounding_source}, {"guardContent": {"text": {"text": c.body, "qualifiers": ["query"]}}}]
            return [{"text": c.body}] if isinstance(c.body, str) else []
        
        # 🟦 Si es imagen (base64), se decodifica y se empaqueta como imagen binaria
        elif c.content_type == "image":
            if not isinstance(c.body, str):
                logger.error("El cuerpo de la imagen no es una cadena Base64.")
                return []
            format = c.media_type.split("/")[1] if c.media_type else "jpeg"
            try:
                image_bytes = base64.b64decode(c.body)
                return [{"image": {"format": format, "source": {"bytes": image_bytes}}}]
            except Exception as e:
                logger.error(f"Error al decodificar imagen Base64: {e}")
                return []
        
         # 🟥 Si es un archivo adjunto (PDF, Word, etc.), se decodifica y prepara como 'attachment'
        elif c.content_type == "textAttachment":
            try:
                # ✅ Paso 1: Decodificamos el contenido base64 del archivo
                file_bytes = base64.b64decode(c.body)
                 # ✅ Paso 2: Creamos un attachment válido para Claude (nombre limpio, tipo MIME, datos)
                return [{
                    "attachment": {
                        "name": _convert_to_valid_file_name(c.file_name or "document.pdf"), # Limpia el nombre
                        "data": file_bytes, # Bytes reales del archivo
                        "type": c.media_type or "application/pdf", # MIME type correcto
                    }
                }]
            except Exception as e:
                logger.error(f"Error al decodificar el archivo adjunto '{c.file_name}': {e}")
                return []
        
        # ❌ Tipo de contenido no soportado
        else:
            raise NotImplementedError(f"Unsupported content type: {c.content_type}")

    attachments = []
    arg_messages = []
    # 🔁 Iteramos por cada mensaje del historial para procesar sus contenidos
    for message in messages:
        if message.role in ["system", "instruction"]:
            continue # Se omiten mensajes del sistema

        content_blocks = []
        for c in message.content:
            blocks = process_content(c, message.role) # Procesamos texto, imagen o adjunto
            for b in blocks:
                if "attachment" in b:
                    # ✅ Paso 3: Extraemos los adjuntos y los agregamos a la lista de 'attachments'
                    attachments.append(b["attachment"])
                else:
                    content_blocks.append(b)
        
       # ✅ Paso 4: Agregamos el contenido procesado al cuerpo de mensajes para enviar a Claude
        if content_blocks:
            arg_messages.append({
                "role": message.role,
                "content": content_blocks,
            })

    # 🔧 Se construye la configuración de inferencia del modelo (tokens, temperatura, etc.)
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
    if 'top_k' in inference_config:
        additional_model_request_fields["top_k"] = inference_config.pop("top_k")

    # ✅ Paso 5: Se crea el diccionario final que será enviado a Claude vía la API de Bedrock
    args: ConverseApiRequest = {
        "inference_config": convert_dict_keys_to_camel_case(inference_config),
        "additional_model_request_fields": additional_model_request_fields,
        "model_id": get_model_id(model),
        "messages": arg_messages,
        "stream": stream,
        "system": [{"text": instruction}] if instruction else [],
    }

    # ✅ Paso 6: Si hay archivos adjuntos, se agregan al payload
    if attachments:
        args["attachments"] = attachments

    # 🛡️ Si hay configuración de guardrails (moderación), se adjunta también
    if guardrail and guardrail.guardrail_arn and guardrail.guardrail_version:
        args["guardrailConfig"] = {
            "guardrailIdentifier": guardrail.guardrail_arn,
            "guardrailVersion": guardrail.guardrail_version,
            "trace": "enabled",
        }
        if stream:
            args["guardrailConfig"]["streamProcessingMode"] = "async"

    # --- INICIO DEL BLOQUE DE LOGS PARA DEPURACIÓN ---
    # 📋 Log del payload final (sin mostrar los bytes de los archivos por seguridad)
    logger.info("="*50)
    logger.info("Argumentos finales para la API de Bedrock Converse:")
    # Hacemos una copia para no loggear los bytes del archivo que son muy largos
    args_for_log = args.copy()
    if "attachments" in args_for_log and args_for_log["attachments"]:
        args_for_log["attachments"] = [
            {k: v for k, v in att.items() if k != 'data'} 
            for att in args_for_log["attachments"]
        ]
    logger.info(args_for_log)
    logger.info("="*50)
    # --- FIN DEL BLOQUE DE LOGS ---

    return args


def call_converse_api(args: ConverseApiRequest) -> ConverseApiResponse:
     # 🛠️ Se obtiene el cliente de runtime de Bedrock
    client = get_bedrock_runtime_client()
    # 🧱 Se construye el objeto base con los parámetros principales de la llamada
    base_args = {
        "modelId": args["model_id"], # ID del modelo (por ejemplo, Claude 3.5 Sonnet)
        "messages": args["messages"], # Mensajes ya procesados (texto, imágenes, adjuntos)
        "inferenceConfig": args["inference_config"], # Configuración del modelo (tokens, temperatura, etc.)
        "system": args["system"], # Instrucciones de sistema, si las hay
        "additionalModelRequestFields": args["additional_model_request_fields"], # Campos opcionales
    }
    # 🛡️ Si hay guardrails configurados, se agregan
    if "guardrailConfig" in args:
        base_args["guardrailConfig"] = args["guardrailConfig"]
    
    # 📎 Si hay archivos adjuntos (PDFs u otros), se agregan a la solicitud
    if "attachments" in args and args["attachments"]:
        base_args["attachments"] = args["attachments"]

    # 🚀 Finalmente, se realiza la llamada a la API de Bedrock con el payload completo
    return client.converse(**base_args)


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
    model_id = DEFAULT_EMBEDDING_CONFIG["model_id"]
    assert model_id == "cohere.embed-multilingual-v3"
    payload = json.dumps({"texts": [question], "input_type": "search_query"})
    response = client.invoke_model(
        accept="application/json", contentType="application/json", body=payload, modelId=model_id
    )
    output = json.loads(response.get("body").read())
    return output.get("embeddings")[0]


def calculate_document_embeddings(documents: list[str]) -> list[list[float]]:
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