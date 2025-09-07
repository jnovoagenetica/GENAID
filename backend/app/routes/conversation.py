# backend/app/routes/conversation.py

from typing import Optional, List, Union
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
from app.repositories.models.conversation import FeedbackModel
from app.routes.schemas.conversation import (
    ChatInput,
    ChatOutput,
    ChatInputWithFiles,  # se mantiene por compatibilidad si lo usas en otro endpoint
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
import base64

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
    files: Optional[Union[UploadFile, List[UploadFile]]] = File(None, alias="files"),
):
    """Send chat message with optional files (PDFs, etc.)"""
    current_user: User = request.state.current_user

    # 1) Parsear JSON del campo 'message'
    try:
        message_dict = json.loads(message)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in 'message' field")

    # 2) Normalizar campos requeridos por el esquema
    #    - parentMessageId es requerido por ChatInput.message: si no viene, lo ponemos a None
    if "parentMessageId" not in message_dict:
        message_dict["parentMessageId"] = None
    #    - content debe ser lista
    if "content" not in message_dict or not isinstance(message_dict["content"], list):
        message_dict["content"] = []

    # 3) Procesar adjuntos (si existen)
    attachments: list[dict] = []

    # Normaliza 'files' a lista
    file_list: List[UploadFile] = []
    if isinstance(files, list):
        file_list = files
    elif files is not None:
        file_list = [files]

    # Extra: también acepta 'files[]'
    if not file_list:
        form = await request.form()
        for f in form.getlist("files[]"):
            if isinstance(f, UploadFile):
                file_list.append(f)

    if file_list:
        UPLOADS_DIR = "/tmp" if os.environ.get("AWS_EXECUTION_ENV") else r"C:\uploads"
        os.makedirs(UPLOADS_DIR, exist_ok=True)

        for upload in file_list:
            file_bytes = await upload.read()
            base64_data = base64.b64encode(file_bytes).decode("utf-8")

            # 🟢 Construye en camelCase para que lo acepte ChatInput
            attachments.append({
                "contentType": "textAttachment",
                "mediaType": upload.content_type or "application/pdf",
                "fileName": upload.filename or "file.pdf",
                "body": base64_data,
            })

            try:
                with open(os.path.join(UPLOADS_DIR, upload.filename), "wb") as f:
                    f.write(file_bytes)
            except Exception:
                pass

            print(f"[BACKEND] Archivo procesado: {upload.filename} ({upload.content_type}, {len(file_bytes)} bytes)")
    else:
        print("[BACKEND] No se recibieron archivos adjuntos")

    # Añade los adjuntos al mensaje
    if attachments:
        message_dict["content"].extend(attachments)


    # 4) Construir payload en camelCase para ChatInput
    payload = {
        "conversationId": conversation_id,
        "message": message_dict,
    }
    if bot_id is not None:
        payload["botId"] = bot_id

    # 5) Materializar ChatInput y llamar a chat()
    try:
        chat_input = ChatInput(**payload)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid message schema: {e}")

    output = await chat(user_id=current_user.id, chat_input=chat_input)
    return output


@router.post(
    "/conversation/related-documents",
    response_model=list[RelatedDocumentsOutput] | None,
)
def get_related_documents(
    request: Request, chat_input: ChatInput
) -> list[RelatedDocumentsOutput] | None:
    current_user: User = request.state.current_user
    output = fetch_related_documents(user_id=current_user.id, chat_input=chat_input)
    return output


@router.get("/conversation/{conversation_id}", response_model=Conversation)
def get_conversation(request: Request, conversation_id: str):
    current_user: User = request.state.current_user
    output = fetch_conversation(current_user.id, conversation_id)
    return output


@router.delete("/conversation/{conversation_id}")
def remove_conversation(request: Request, conversation_id: str):
    current_user: User = request.state.current_user
    delete_conversation_by_id(current_user.id, conversation_id)


@router.get("/conversations", response_model=list[ConversationMetaOutput])
def get_all_conversations(request: Request):
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
    delete_conversation_by_user_id(request.state.current_user.id)


@router.patch("/conversation/{conversation_id}/title")
def patch_conversation_title(
    request: Request, conversation_id: str, new_title_input: NewTitleInput
):
    current_user: User = request.state.current_user
    change_conversation_title(
        current_user.id, conversation_id, new_title_input.new_title
    )


@router.get(
    "/conversation/{conversation_id}/proposed-title", response_model=ProposedTitle
)
def get_proposed_title(request: Request, conversation_id: str):
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