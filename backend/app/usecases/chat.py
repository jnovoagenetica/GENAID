# backend/app/usecases/chat.py

import logging
from copy import deepcopy
from typing import Literal
import base64
import io
import fitz  # PyMuPDF
import re
from math import ceil # Necesario para los nuevos logs

from app.agents.agent import AgentRunner
from app.agents.tools.knowledge import create_knowledge_tool
from app.agents.utils import get_tool_by_name
from app.bedrock import (
    calculate_price,
    call_converse_api,
    compose_args_for_converse_api,
)
from app.prompt import build_rag_prompt
from app.repositories.conversation import (
    RecordNotFoundError,
    find_conversation_by_id,
    store_conversation,
)
from app.repositories.custom_bot import find_alias_by_id, store_alias
from app.repositories.models.conversation import (
    ChunkModel,
    ContentModel,
    ConversationModel,
    MessageModel,
)
from app.repositories.models.custom_bot import (
    BotAliasModel,
    BotModel,
    ConversationQuickStarterModel,
)
from app.routes.schemas.conversation import (
    AgentMessage,
    ChatInputWithFiles,
    ChatOutput,
    Chunk,
    Content,
    Conversation,
    FeedbackOutput,
    MessageOutput,
    RelatedDocumentsOutput,
)
from app.usecases.bot import fetch_bot, modify_bot_last_used_time
from app.utils import get_current_time, is_running_on_lambda
from app.vector_search import (
    SearchResult,
    filter_used_results,
    get_source_link,
    search_related_docs,
    to_guardrails_grounding_source,
)
from ulid import ULID

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


# Helpers para limpiar/decodificar sin romper
def _clean(s):
    if not s:
        return ""
    try:
        return re.sub(r"\s+", " ", s).strip()
    except Exception as e:
        logger.warning("Clean failed: %s", e)
        return ""

def _b64(s):
    if not s:
        return b""
    try:
        return base64.b64decode(s, validate=False)
    except Exception as e:
        logger.warning("b64 decode failed: %s", e)
        return b""

def _pdf_to_text(pdf_bytes: bytes) -> str:
    if not pdf_bytes:
        return ""
    try:
        out = []
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                out.append(page.get_text("text") or "")
        return "\n".join(out) or ""
    except Exception as e:
        logger.warning("PDF extract failed: %s", e)
        return ""


def _convert_to_valid_file_name(filename: str) -> str:
    """Remueve caracteres no válidos de un nombre de archivo."""
    return re.sub(r'[^\w\._-]', '_', filename)


def prepare_conversation(
    user_id: str,
    chat_input: ChatInputWithFiles,
) -> tuple[str, ConversationModel, BotModel | None]:
    # ... (El contenido de esta función se mantiene igual)
    current_time = get_current_time()
    bot = None

    try:
        # Fetch existing conversation
        conversation = find_conversation_by_id(user_id, chat_input.conversation_id)
        logger.info(f"Found conversation: {conversation}")
        parent_id = chat_input.message.parent_message_id
        if chat_input.message.parent_message_id == "system" and chat_input.bot_id:
            # The case editing first user message and use bot
            parent_id = "instruction"
        elif chat_input.message.parent_message_id is None:
            parent_id = conversation.last_message_id
        if chat_input.bot_id:
            logger.info("Bot id is provided. Fetching bot.")
            owned, bot = fetch_bot(user_id, chat_input.bot_id)
    except RecordNotFoundError:
        # The case for new conversation. Note that editing first user message is not considered as new conversation.
        logger.info(
            f"No conversation found with id: {chat_input.conversation_id}. Creating new conversation."
        )

        initial_message_map = {
            # Dummy system message, which is used for root node of the message tree.
            "system": MessageModel(
                role="system",
                content=[
                    ContentModel(
                        content_type="text",
                        media_type=None,
                        body="",
                        file_name=None,
                    )
                ],
                model=chat_input.message.model,
                children=[],
                parent=None,
                create_time=current_time,
                feedback=None,
                used_chunks=None,
                thinking_log=None,
            )
        }
        parent_id = "system"
        if chat_input.bot_id:
            logger.info("Bot id is provided. Fetching bot.")
            parent_id = "instruction"
            # Fetch bot and append instruction
            owned, bot = fetch_bot(user_id, chat_input.bot_id)
            initial_message_map["instruction"] = MessageModel(
                role="instruction",
                content=[
                    ContentModel(
                        content_type="text",
                        media_type=None,
                        body=bot.instruction,
                        file_name=None,
                    )
                ],
                model=chat_input.message.model,
                children=[],
                parent="system",
                create_time=current_time,
                feedback=None,
                used_chunks=None,
                thinking_log=None,
            )
            initial_message_map["system"].children.append("instruction")

            if not owned:
                try:
                    # Check alias is already created
                    find_alias_by_id(user_id, chat_input.bot_id)
                except RecordNotFoundError:
                    logger.info(
                        "Bot is not owned by the user. Creating alias to shared bot."
                    )
                    # Create alias item
                    store_alias(
                        user_id,
                        BotAliasModel(
                            id=bot.id,
                            title=bot.title,
                            description=bot.description,
                            original_bot_id=chat_input.bot_id,
                            create_time=current_time,
                            last_used_time=current_time,
                            is_pinned=False,
                            sync_status=bot.sync_status,
                            has_knowledge=bot.has_knowledge(),
                            has_agent=bot.is_agent_enabled(),
                            conversation_quick_starters=(
                                []
                                if bot.conversation_quick_starters is None
                                else [
                                    ConversationQuickStarterModel(
                                        title=starter.title,
                                        example=starter.example,
                                    )
                                    for starter in bot.conversation_quick_starters
                                ]
                            ),
                        ),
                    )

        # Create new conversation
        conversation = ConversationModel(
            id=chat_input.conversation_id,
            title="New conversation",
            total_price=0.0,
            create_time=current_time,
            message_map=initial_message_map,
            last_message_id="",
            bot_id=chat_input.bot_id,
            should_continue=False,
        )

    # Append user chat input to the conversation
    if chat_input.message.message_id:
        message_id = chat_input.message.message_id
    else:
        message_id = str(ULID())
    # If the "Generate continue" button is pressed, a new_message is not generated.
    if not chat_input.continue_generate:
        new_message = MessageModel(
            role=chat_input.message.role,
            content=[
                ContentModel(
                    content_type=c.content_type,
                    media_type=c.media_type,
                    body=c.body,
                    file_name=c.file_name,
                )
                for c in chat_input.message.content
            ],
            model=chat_input.message.model,
            children=[],
            parent=parent_id,
            create_time=current_time,
            feedback=None,
            used_chunks=None,
            thinking_log=None,
        )
        conversation.message_map[message_id] = new_message
        conversation.message_map[parent_id].children.append(message_id)  # type: ignore

    return (message_id, conversation, bot)


def trace_to_root(
    node_id: str | None, message_map: dict[str, MessageModel]
) -> list[MessageModel]:
    # ... (El contenido de esta función se mantiene igual)
    result = []
    if not node_id or node_id == "system":
        node_id = "instruction" if "instruction" in message_map else "system"

    current_node = message_map.get(node_id)
    while current_node:
        result.append(current_node)
        parent_id = current_node.parent
        if parent_id is None:
            break
        current_node = message_map.get(parent_id)

    return result[::-1]


def insert_knowledge(
    conversation: ConversationModel,
    search_results: list[SearchResult],
    display_citation: bool = True,
) -> ConversationModel:
    # ... (El contenido de esta función se mantiene igual)
    if len(search_results) == 0:
        return conversation

    inserted_prompt = build_rag_prompt(conversation, search_results, display_citation)
    logger.info(f"Inserted prompt: {inserted_prompt}")

    conversation_with_context = deepcopy(conversation)
    conversation_with_context.message_map["instruction"].content[
        0
    ].body = inserted_prompt

    return conversation_with_context


async def chat(user_id: str, chat_input: ChatInputWithFiles) -> ChatOutput:
    # --- INICIO DE LOS CAMBIOS ---
    # 1. Añadir bloque de logs
    logger.info("[CHAT] ----- INICIO chat() -----")
    logger.info("[CHAT] conversation_id=%s  bot_id=%s  model=%s",
                chat_input.conversation_id, chat_input.bot_id, chat_input.message.model)

    total_blocks = len(chat_input.message.content)
    logger.info("[CHAT] message.content: %d bloque(s)", total_blocks)

    num_txt = 0
    num_img = 0
    num_attach = 0

    for i, c in enumerate(chat_input.message.content):
        ct = getattr(c, "content_type", None)
        mt = getattr(c, "media_type", None)
        fn = getattr(c, "file_name", None)
        body_len = len(c.body) if isinstance(c.body, str) else 0

        if ct == "text":
            num_txt += 1
            logger.info("[CHAT][%d] TEXT len=%d", i, body_len)
        elif ct == "image":
            num_img += 1
            logger.info("[CHAT][%d] IMAGE media=%s base64_len=%d", i, mt, body_len)
        elif ct == "textAttachment":
            num_attach += 1
            approx_kb = ceil((body_len * 3) / 4 / 1024)
            logger.info(
                "[CHAT][%d] ATTACH name=%s media=%s base64_len=%d (~%d KB)",
                i, fn, mt, body_len, approx_kb
            )
        else:
            logger.info("[CHAT][%d] tipo desconocido: %s", i, ct)

    logger.info("[CHAT] Totales -> text=%d image=%d attachments=%d", num_txt, num_img, num_attach)

    # 2. Eliminar bloque de procesamiento de chat_input.files (ahora es obsoleto)
    # El siguiente bloque ha sido eliminado:
    # attachments = []
    # if chat_input.files: ...

    # 3. Corregir llamada a prepare_conversation (sin await)
    user_msg_id, conversation, bot = prepare_conversation(user_id, chat_input)
    # --- FIN DE LOS CAMBIOS ---

    used_chunks = None
    price = 0.0
    thinking_log = None

    if bot and bot.is_agent_enabled():
        # ... (La lógica del agente se mantiene igual)
        logger.info("Bot has agent tools. Using agent for response.")
        tools = [get_tool_by_name(t.name) for t in bot.agent.tools]

        if bot.has_knowledge():
            knowledge_tool = create_knowledge_tool(bot, chat_input.message.model)
            tools.append(knowledge_tool)

        runner = AgentRunner(
            bot=bot, tools=tools, model=chat_input.message.model,
            on_thinking=None, on_tool_result=None, on_stop=None,
        )
        message_map = conversation.message_map
        messages = trace_to_root(node_id=user_msg_id, message_map=message_map)

        result = runner.run(messages)
        reply_txt = result.last_response["output"]["message"]["content"][0].get("text", "")
        price = result.price
        thinking_log = result.thinking_conversation
        conversation.should_continue = False
    else:
        message_map = conversation.message_map
        search_results = []
        if bot and is_running_on_lambda():
            query_content = conversation.message_map[user_msg_id].content[0]
            if isinstance(query_content.body, str):
                query: str = query_content.body
                search_results = search_related_docs(bot=bot, query=query)
                logger.info(f"Search results from vector store: {search_results}")
                conversation_with_context = insert_knowledge(
                    conversation, search_results, display_citation=bot.display_retrieved_chunks
                )
                message_map = conversation_with_context.message_map

        messages = trace_to_root(node_id=user_msg_id, message_map=message_map)

        # --- Normaliza adjuntos: convertir textAttachment -> texto plano ---
        for idx, m in enumerate(messages):
            new_contents = []
            for c in m.content:
                ct = (getattr(c, "content_type", None) or "").lower()
                mt = (getattr(c, "media_type", None) or "")

                if ct == "text":
                    txt = _clean(c.body if isinstance(c.body, str) else "")
                    if txt:
                        new_contents.append(
                            ContentModel(content_type="text", media_type=None, body=txt, file_name=None)
                        )

                elif ct == "textattachment":
                    blob = _b64(c.body if isinstance(c.body, str) else "")
                    txt = ""

                    if "pdf" in mt.lower():
                        txt = _clean(_pdf_to_text(blob))
                        if not txt:
                            # PDF escaneado/sin texto -> no rompas
                            fname = c.file_name or "archivo.pdf"
                            txt = f"[Adjunto PDF sin texto legible: {fname}]"
                    elif mt.lower().startswith("text/"):
                        try:
                            txt = _clean(blob.decode("utf-8", errors="ignore"))
                        except Exception:
                            txt = ""
                    else:
                        fname = c.file_name or "archivo"
                        kind = mt or "binario"
                        txt = f"[Adjunto {kind}: {fname}]"

                    if txt:
                        new_contents.append(
                            ContentModel(content_type="text", media_type=None, body=txt, file_name=None)
                        )

                else:
                    # Ignora tipos no soportados en esta ruta
                    pass

            # Si logramos extraer algo, reemplaza el contenido del mensaje por solo texto
            if new_contents:
                logger.info("[CHAT] msg[%d]: %d item(s) normalizados a texto", idx, len(new_contents))
                m.content = new_contents
            else:
                # Evita None/colecciones vacías
                m.content = [
                    ContentModel(content_type="text", media_type=None, body="", file_name=None)
                ]
        # --- Fin normalización ---
        
        # 4. Añadir log antes de llamar a Bedrock
        logger.info("[CHAT] Preparando args para Bedrock. (extraerá attachments desde message.content)")
        
        # 5. Simplificar la llamada a compose_args_for_converse_api
        generation_config = bot.generation_params if bot else None

        args = compose_args_for_converse_api(
            messages=messages,
            model=chat_input.message.model,
            instruction=(
                message_map["instruction"].content[0].body
                if "instruction" in message_map and isinstance(message_map["instruction"].content[0].body, str)
                else None
            ),
            generation_params=generation_config,
            grounding_source=to_guardrails_grounding_source(search_results),
            guardrail=(bot.bedrock_guardrails if bot else None),
        )
        
        response = call_converse_api(args)

        reply_txt = response["output"]["message"]["content"][0].get("text", "")
        reply_txt = reply_txt.rstrip()

        if bot and bot.display_retrieved_chunks and is_running_on_lambda():
            if len(search_results) > 0:
                used_chunks = []
                for r in filter_used_results(reply_txt, search_results):
                    content_type, source_link = get_source_link(r.source)
                    used_chunks.append(
                        ChunkModel(content=r.content, content_type=content_type, source=source_link, rank=r.rank)
                    )

        input_tokens = response["usage"]["inputTokens"]
        output_tokens = response["usage"]["outputTokens"]
        price = calculate_price(chat_input.message.model, input_tokens, output_tokens)
        conversation.should_continue = False

    assistant_msg_id = str(ULID())
    message = MessageModel(
        role="assistant",
        content=[ContentModel(content_type="text", body=reply_txt, media_type=None, file_name=None)],
        model=chat_input.message.model,
        children=[],
        parent=user_msg_id,
        create_time=get_current_time(),
        feedback=None,
        used_chunks=used_chunks,
        thinking_log=thinking_log,
    )

    if chat_input.continue_generate:
        conversation.message_map[conversation.last_message_id].content[0].body += reply_txt
    else:
        conversation.message_map[assistant_msg_id] = message
        conversation.message_map[user_msg_id].children.append(assistant_msg_id)
        conversation.last_message_id = assistant_msg_id

    conversation.total_price += price
    store_conversation(user_id, conversation)
    if chat_input.bot_id:
        modify_bot_last_used_time(user_id, chat_input.bot_id)

    message_output = MessageOutput(
        role=message.role,
        content=[
            Content(
                content_type=c.content_type,
                body=str(c.body) if isinstance(c.body, bytes) else c.body,
                media_type=c.media_type,
                file_name=c.file_name,
            ) for c in message.content
        ],
        model=message.model,
        children=message.children,
        parent=message.parent,
        feedback=None,
        used_chunks=(
            [Chunk(content=c.content, content_type=c.content_type, source=c.source, rank=c.rank) for c in message.used_chunks]
            if message.used_chunks else None
        ),
        thinking_log=(
            [AgentMessage.from_model(m) for m in message.thinking_log]
            if message.thinking_log else None
        ),
    )

    output = ChatOutput(
        conversation_id=conversation.id,
        create_time=conversation.create_time,
        message=message_output,
        bot_id=conversation.bot_id,
    )

    return output


def propose_conversation_title(
    # ... (El contenido de esta función se mantiene igual)
    user_id: str,
    conversation_id: str,
    model: Literal[
        "claude-instant-v1", "claude-v2", "claude-v3-opus", "claude-v3-sonnet",
        "claude-v3.5-sonnet", "claude-v3-haiku", "mistral-7b-instruct",
        "mixtral-8x7b-instruct", "mistral-large",
    ] = "claude-v3-haiku",
) -> str:
    PROMPT = """Reading the conversation above, what is the appropriate title for the conversation? When answering the title, please follow the rules below:
<rules>
- Title length must be from 15 to 20 characters.
- Prefer more specific title than general. Your title should always be distinct from others.
- Return the conversation title only. DO NOT include any strings other than the title.
- Title must be in the same language as the conversation.
</rules>
"""
    conversation = find_conversation_by_id(user_id, conversation_id)
    messages_with_attachment = trace_to_root(
        node_id=conversation.last_message_id, message_map=conversation.message_map,
    )
    messages = []
    for msg in messages_with_attachment:
        text_contents = [c for c in msg.content if c.content_type == "text" and isinstance(c.body, str)]
        if text_contents:
            new_msg = msg.model_copy(deep=True)
            new_msg.content = text_contents
            messages.append(new_msg)
    
    new_message = MessageModel(
        role="user",
        content=[ContentModel(content_type="text", body=PROMPT, media_type=None, file_name=None)],
        model=model,
        children=[],
        parent=conversation.last_message_id,
        create_time=get_current_time(),
        feedback=None, used_chunks=None, thinking_log=None,
    )
    messages.append(new_message)
    
    args = compose_args_for_converse_api(messages=messages, model=model)
    response = call_converse_api(args)
    reply_txt = response["output"]["message"]["content"][0].get("text", "")
    return reply_txt


def fetch_conversation(user_id: str, conversation_id: str) -> Conversation:
    # ... (El contenido de esta función se mantiene igual)
    conversation = find_conversation_by_id(user_id, conversation_id)
    message_map = {
        message_id: MessageOutput(
            role=message.role,
            content=[
                Content(
                    content_type=c.content_type,
                    body=str(c.body) if isinstance(c.body, bytes) else c.body,
                    media_type=c.media_type, file_name=c.file_name,
                ) for c in message.content
            ],
            model=message.model, children=message.children, parent=message.parent,
            feedback=(
                FeedbackOutput(
                    thumbs_up=message.feedback.thumbs_up, category=message.feedback.category,
                    comment=message.feedback.comment,
                ) if message.feedback else None
            ),
            used_chunks=(
                [Chunk(content=c.content, content_type=c.content_type, source=c.source, rank=c.rank) for c in message.used_chunks]
                if message.used_chunks else None
            ),
            thinking_log=(
                [AgentMessage.from_model(m) for m in message.thinking_log]
                if message.thinking_log else None
            ),
        ) for message_id, message in conversation.message_map.items()
    }
    if "instruction" in message_map:
        for c in message_map["instruction"].children:
            message_map[c].parent = "system"
        message_map["system"].children = message_map["instruction"].children
        del message_map["instruction"]
    
    output = Conversation(
        id=conversation_id, title=conversation.title, create_time=conversation.create_time,
        last_message_id=conversation.last_message_id, message_map=message_map,
        bot_id=conversation.bot_id, should_continue=conversation.should_continue,
    )
    return output


def fetch_related_documents(
    user_id: str, chat_input: ChatInputWithFiles
) -> list[RelatedDocumentsOutput] | None:
    # ... (El contenido de esta función se mantiene igual)
    if not chat_input.bot_id:
        return []

    _, bot = fetch_bot(user_id, chat_input.bot_id)
    if not bot.display_retrieved_chunks:
        return None

    query_content = chat_input.message.content[-1]
    if not isinstance(query_content.body, str):
        return []
        
    query: str = query_content.body
    chunks = search_related_docs(bot=bot, query=query)
    documents = []
    for chunk in chunks:
        content_type, source_link = get_source_link(chunk.source)
        documents.append(
            RelatedDocumentsOutput(
                chunk_body=chunk.content, content_type=content_type,
                source_link=source_link, rank=chunk.rank,
            )
        )
    return documents