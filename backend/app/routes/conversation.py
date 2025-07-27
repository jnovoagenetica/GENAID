import logging
import base64
from fastapi import APIRouter, Request, UploadFile, File, Form
from app.repositories.models.conversation import MessageModel, ContentModel
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

router = APIRouter(tags=["conversation"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/conversation", response_model=ChatOutput)
def post_message(request: Request, chat_input: ChatInput):
    current_user: User = request.state.current_user
    return chat(user_id=current_user.id, chat_input=chat_input)


@router.post("/conversation/upload", response_model=ChatOutput)
async def post_message_with_file(
    request: Request,
    message: str = Form(...),
    model: str = Form(...),
    parent_message_id: str = Form(...),
    conversation_id: str | None = Form(None),
    bot_id: str | None = Form(None),
    file: UploadFile = File(...)
):
    current_user: User = request.state.current_user
    file_bytes = await file.read()

    encoded_file_body = base64.b64encode(file_bytes).decode('utf-8')

    # --- CAMBIO FINALÍSIMO: Usamos un diccionario simple en lugar de MessageModel ---
    # Esto imita exactamente la estructura que el frontend enviaría en un POST normal.
    message_data = {
        "role": "user",
        "content": [
            # Usamos .model_dump() para convertir los objetos Pydantic a diccionarios
            ContentModel(body=message, content_type="text", media_type="text/plain").model_dump(),
            ContentModel(
                file_name=file.filename,
                body=encoded_file_body,
                content_type="attachment",
                media_type=file.content_type
            ).model_dump()
        ],
        "model": model,
        "parentMessageId": parent_message_id, # Usamos camelCase para que coincida con la entrada esperada
    }
    
    chat_input = ChatInput(
        message=message_data,
        conversation_id=conversation_id,
        bot_id=bot_id,
    )

    return chat(user_id=current_user.id, chat_input=chat_input)


# ... (el resto del archivo sigue igual)
@router.post("/conversation/related-documents", response_model=list[RelatedDocumentsOutput] | None)
def get_related_documents(request: Request, chat_input: ChatInput):
    current_user: User = request.state.current_user
    return fetch_related_documents(user_id=current_user.id, chat_input=chat_input)


@router.get("/conversation/{conversation_id}", response_model=Conversation)
def get_conversation(request: Request, conversation_id: str):
    current_user: User = request.state.current_user
    return fetch_conversation(current_user.id, conversation_id)


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
            id=conv.id,
            title=conv.title,
            create_time=conv.create_time,
            model=conv.model,
            bot_id=conv.bot_id,
        )
        for conv in conversations
    ]


@router.delete("/conversations")
def remove_all_conversations(request: Request):
    delete_conversation_by_user_id(request.state.current_user.id)


@router.patch("/conversation/{conversation_id}/title")
def patch_conversation_title(
    request: Request, conversation_id: str, new_title_input: NewTitleInput
):
    current_user: User = request.state.current_user
    change_conversation_title(current_user.id, conversation_id, new_title_input.new_title)


@router.get("/conversation/{conversation_id}/proposed-title", response_model=ProposedTitle)
def get_proposed_title(request: Request, conversation_id: str):
    current_user: User = request.state.current_user
    title = propose_conversation_title(current_user.id, conversation_id)
    try:
        change_conversation_title(current_user.id, conversation_id, title)
        logging.info(f"Título actualizado para la conversación {conversation_id}: '{title}'")
    except Exception as e:
        logging.error(f"FALLO al guardar el nuevo título para la conversación {conversation_id}: {e}")
    return ProposedTitle(title=title)


@router.put("/conversation/{conversation_id}/{message_id}/feedback", response_model=FeedbackOutput)
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