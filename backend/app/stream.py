# app/stream.py

import logging
from typing import Any, Callable, Tuple

from app.bedrock import ConverseApiRequest, calculate_price
from app.routes.schemas.conversation import type_model_name
from app.utils import get_bedrock_runtime_client, convert_dict_keys_to_camel_case
from pydantic import BaseModel

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class OnStopInput(BaseModel):
    full_token: str
    stop_reason: str
    input_token_count: int
    output_token_count: int
    price: float


def _is_anthropic_model_id(model_id: str) -> bool:
    mid = (model_id or "").lower()
    return ("anthropic" in mid) or ("claude" in mid)


def _sanitize_for_anthropic(
    model_id: str,
    inference_config: dict | None,
    addl_fields: dict | None,
) -> Tuple[dict, dict]:
    """
    Para modelos Anthropic (Claude 4.x/4.5), limpiamos combinaciones que cortan el stream:
      - Quitar stopSequences
      - Quitar topP/top_p
      - No enviar additionalModelRequestFields (top_k, etc.)
    Además, normalizamos a camelCase por si llegó en snake_case.
    """
    inf = convert_dict_keys_to_camel_case(inference_config or {})
    addl = dict(addl_fields or {})

    if _is_anthropic_model_id(model_id):
        # Claude 4.5 se corta si llegan estos campos en streaming
        inf.pop("stopSequences", None)
        inf.pop("topP", None)
        inf.pop("top_p", None)  # por si vino sin convertir
        # No enviar extras (top_k, etc.)
        addl = {}

    return inf, addl


class ConverseApiStreamHandler:
    """Stream handler usando Bedrock ConverseStream."""

    def __init__(
        self,
        model: type_model_name,
        on_stream: Callable[[str], None],
        on_stop: Callable[[OnStopInput], None],
    ):
        self.model: type_model_name = model
        self.on_stream = on_stream
        self.on_stop = on_stop

    @classmethod
    def from_model(cls, model: type_model_name):
        return ConverseApiStreamHandler(
            model=model, on_stream=lambda x: None, on_stop=lambda x: None
        )

    def bind(
        self, on_stream: Callable[[str], Any], on_stop: Callable[[OnStopInput], Any]
    ):
        self.on_stream = on_stream
        self.on_stop = on_stop
        return self

    def run(self, args: ConverseApiRequest):
        client = get_bedrock_runtime_client()

        # --- Sanitizar args para Anthropic (clave del fix) ---
        model_id = args["model_id"]
        sanitized_inf, sanitized_addl = _sanitize_for_anthropic(
            model_id,
            args.get("inference_config", {}),
            args.get("additional_model_request_fields", {}),
        )

        # Armado de base_args. Omitimos additionalModelRequestFields si está vacío.
        base_args = {
            "modelId": model_id,
            "messages": args["messages"],
            "inferenceConfig": sanitized_inf,
            "system": args["system"],
        }
        if sanitized_addl:
            base_args["additionalModelRequestFields"] = sanitized_addl

        if "guardrailConfig" in args:
            base_args["guardrailConfig"] = args["guardrailConfig"]  # type: ignore

        logger.info("args for converse_stream (sanitized): %s", base_args)

        try:
            response = client.converse_stream(**base_args)
        except Exception as e:
            logger.error(f"Error al llamar converse_stream: {e}")
            raise

        completions: list[str] = []
        stop_reason: str | None = None
        input_token_count: int | None = None
        output_token_count: int | None = None

        # A veces metadata llega antes o después de messageStop. Esperamos a tener ambos.
        sent_final = False

        def maybe_emit_final():
            nonlocal sent_final
            if sent_final:
                return None
            if (stop_reason is not None) and (input_token_count is not None) and (output_token_count is not None):
                concatenated = "".join(completions)
                price = calculate_price(self.model, input_token_count, output_token_count)
                payload = OnStopInput(
                    full_token=concatenated.rstrip(),
                    stop_reason=stop_reason or "",
                    input_token_count=input_token_count,
                    output_token_count=output_token_count,
                    price=price,
                )
                out = self.on_stop(payload)
                logger.info(
                    "event of converse_stream: stop_reason=%s usage={input:%s, output:%s}",
                    stop_reason, input_token_count, output_token_count,
                )
                sent_final = True
                return out
            return None

        try:
            for event in response["stream"]:
                # messageStart / contentBlockStart: no-op
                if "contentBlockDelta" in event:
                    # Puede venir un delta sin 'text' (por ejemplo toolUse).
                    delta = event.get("contentBlockDelta", {}).get("delta", {})
                    text = delta.get("text", "")
                    if text:
                        completions.append(text)
                        yield self.on_stream(text)

                elif "messageStop" in event:
                    stop_reason = event["messageStop"].get("stopReason", "")
                    out = maybe_emit_final()
                    if out is not None:
                        yield out

                elif "metadata" in event:
                    usage = event.get("metadata", {}).get("usage", {}) or {}
                    input_token_count = usage.get("inputTokens", 0)
                    output_token_count = usage.get("outputTokens", 0)
                    out = maybe_emit_final()
                    if out is not None:
                        yield out

                elif "error" in event:
                    err = event.get("error", {})
                    logger.error("Bedrock stream error: %s", err)
                    # Emitimos final con lo que haya
                    stop_reason = stop_reason or "error"
                    input_token_count = input_token_count or 0
                    output_token_count = output_token_count or 0
                    out = maybe_emit_final()
                    if out is not None:
                        yield out
                    break

                # contentBlockStart/Stop, messageStart: ignorados a propósito
                # para no “ensuciar” el contrato de streaming hacia el front

            # Si el stream termina sin alguno de los dos (raro), cerramos igual.
            if not sent_final:
                stop_reason = stop_reason or "end_of_stream"
                input_token_count = input_token_count or 0
                output_token_count = output_token_count or 0
                out = maybe_emit_final()
                if out is not None:
                    yield out

        finally:
            try:
                response.close()
            except Exception:
                pass
