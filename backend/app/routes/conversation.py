# backend/app/routes/conversation.py

from typing import Optional, List
import json
from fastapi import (
    APIRouter,
    Request,
    UploadFile,
    File,
    Form,
    HTTPException,
)

from app.repositories.conversation import (
    change_conversation_title,
    delete_conversation_by_id,
    delete_conversation_by_user_id,
    find_conversation_by_user_id,
    update_feedback,
)
from app.repositories.models.conversation import FeedbackModel, ContentModel
from app.routes.schemas.conversation import (
    ChatInput,
    ChatOutput,
    ChatInputWithFiles,
    Conversation,
    ConversationMetaOutput,
    FeedbackInput,
    FeedbackOutput,
    NewTitleInput,
    ProposedTitle,
    RelatedDocumentsOutput,
)
from app.usecases.chat import (
    chat,
    fetch_conversation,
    fetch_related_documents,
    propose_conversation_title,
)
from app.user import User

import os
import base64  # Importamos base64 a nivel de módulo

router = APIRouter(tags=["conversation"])


@router.get("/health")
def health():
    """For health check"""
    return {"status": "ok"}


@router.post("/conversation", response_model=ChatOutput)
async def post_message(
    request: Request,
    message: str = Form(...),
    conversation_id: str = Form(...),
    bot_id: Optional[str] = Form(None),
    files: Optional[List[UploadFile]] = File(None),
):
    """Send chat message with optional files (PDFs, etc.)"""
    current_user: User = request.state.current_user

    # 1) Parsear el JSON del campo 'message'
    try:
        message_dict = json.loads(message)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in 'message' field")

    # 2) Convertir a objeto Pydantic para que 'chat_input.message' NO sea dict
    #    (esto habilita el acceso por atributos como .model, .content, etc.)
    try:
        message_obj = ChatInput(**message_dict)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid message schema: {e}")

    # 3) Procesar archivos adjuntos (si los hay) -> generar ContentModel y añadirlos
    pdf_contents: list[ContentModel] = []
    if files:
        # Directorio para guardar archivos (si es para depuración)
        UPLOADS_DIR = r"C:\uploads"
        os.makedirs(UPLOADS_DIR, exist_ok=True)

        for upload in files:
            # Leemos el archivo UNA SOLA VEZ y guardamos los bytes
            file_bytes = await upload.read()

            # 3.1 Guardar en base64 para enviarlo como textAttachment
            base64_data = base64.b64encode(file_bytes).decode("utf-8")
            pdf_contents.append(
                ContentModel(
                    contentType="textAttachment",
                    mediaType=upload.content_type,
                    fileName=upload.filename,
                    body=base64_data,
                )
            )

            # 3.2 Guardar físicamente (opcional, para debug local)
            local_path = os.path.join(UPLOADS_DIR, upload.filename)
            with open(local_path, "wb") as f:
                f.write(file_bytes)

            print(f"[BACKEND] Archivo procesado y guardado: {upload.filename} → {local_path}")
            print(f"[BACKEND] Tipo MIME: {upload.content_type} | Tamaño: {len(file_bytes)} bytes")

        # 3.3 Añadir adjuntos al contenido del mensaje como ContentModel (no dicts)
        if hasattr(message_obj, "content") and isinstance(message_obj.content, list):
            message_obj.content.extend(pdf_contents)
        else:
            message_obj.content = pdf_contents  # fallback si venía vacío o None
    else:
        print("[BACKEND] No se recibieron archivos adjuntos")

    # 4) Construir el ChatInputWithFiles con el objeto tipado
    chat_input = ChatInputWithFiles(
        conversation_id=conversation_id,
        message=message_obj,  # <-- objeto Pydantic, NO dict
        bot_id=bot_id,
        files=files,
    )

    # 5) IMPORTANTÍSIMO: await a la función async
    output = await chat(user_id=current_user.id, chat_input=chat_input)

    return output


@router.post(
    "/conversation/related-documents",
    response_model=list[RelatedDocumentsOutput] | None,
)
def get_related_documents(
    request: Request, chat_input: ChatInput
) -> list[RelatedDocumentsOutput] | None:
    """Get related documents"""
    current_user: User = request.state.current_user
    output = fetch_related_documents(user_id=current_user.id, chat_input=chat_input)
    return output


@router.get("/conversation/{conversation_id}", response_model=Conversation)
def get_conversation(request: Request, conversation_id: str):
    """Get a conversation history"""
    current_user: User = request.state.current_user
    output = fetch_conversation(current_user.id, conversation_id)
    return output


@router.delete("/conversation/{conversation_id}")
def remove_conversation(request: Request, conversation_id: str):
    """Delete conversation"""
    current_user: User = request.state.current_user
    delete_conversation_by_id(current_user.id, conversation_id)


@router.get("/conversations", response_model=list[ConversationMetaOutput])
def get_all_conversations(request: Request):
    """Get all conversation metadata"""
    current_user: User = request.state.current_user
    conversations = find_conversation_by_user_id(current_user.id)
    return [
        ConversationMetaOutput(
            id=conversation.id,
            title=conversation.title,
            create_time=conversation.create_time,
            model=conversation.model,
            bot_id=conversation.bot_id,
        )
        for conversation in conversations
    ]


@router.delete("/conversations")
def remove_all_conversations(request: Request):
    """Delete all conversations"""
    delete_conversation_by_user_id(request.state.current_user.id)


@router.patch("/conversation/{conversation_id}/title")
def patch_conversation_title(
    request: Request, conversation_id: str, new_title_input: NewTitleInput
):
    """Update conversation title"""
    current_user: User = request.state.current_user
    change_conversation_title(
        current_user.id, conversation_id, new_title_input.new_title
    )


@router.get(
    "/conversation/{conversation_id}/proposed-title", response_model=ProposedTitle
)
def get_proposed_title(request: Request, conversation_id: str):
    """Suggest conversation title"""
    current_user: User = request.state.current_user
    title = propose_conversation_title(current_user.id, conversation_id)
    return ProposedTitle(title=title)


@router.put(
    "/conversation/{conversation_id}/{message_id}/feedback",
    response_model=FeedbackOutput,
)
def put_feedback(
    request: Request,
    conversation_id: str,
    message_id: str,
    feedback_input: FeedbackInput,
):
    """Send feedback."""
    current_user: User = request.state.current_user
    update_feedback(
        user_id=current_user.id,
        conversation_id=conversation_id,
        message_id=message_id,
        feedback=FeedbackModel(
            thumbs_up=feedback_input.thumbs_up,
            category=feedback_input.category or "",
            comment=feedback_input.comment or "",
        ),
    )
    return FeedbackOutput(
        thumbs_up=feedback_input.thumbs_up,
        category=feedback_input.category or "",
        comment=feedback_input.comment or "",
    )
