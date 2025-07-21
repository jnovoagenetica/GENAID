# --- CÓDIGO FINAL Y MEJORADO CON LECTURA DE PDF POTENTE ---

# 1. Importaciones necesarias
import logging
import time
from typing import Optional

# Importaciones de FastAPI y pydantic
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

# Importaciones de tu aplicación
from app.repositories.conversation import (
    change_conversation_title, delete_conversation_by_id,
    delete_conversation_by_user_id, find_conversation_by_user_id, update_feedback
)
from app.repositories.models.conversation import FeedbackModel
from app.routes.schemas.conversation import (
    ChatInput, ChatOutput, Conversation, ConversationMetaOutput, FeedbackInput,
    FeedbackOutput, NewTitleInput, ProposedTitle, RelatedDocumentsOutput
)
from app.usecases.chat import (chat, fetch_conversation, fetch_related_documents,
                               propose_conversation_title)
from app.user import User

# /-------------------------------------------------------------------\
# |              CAMBIO DE LIBRERÍA DE LECTURA DE PDF               |
# \-------------------------------------------------------------------/
# Importamos PyMuPDF (fitz). Es mucho más potente que pypdf.
import fitz  # PyMuPDF
# /-------------------------------------------------------------------\

# Router sin prefijo para que las rutas coincidan con las originales
router = APIRouter(tags=["conversation"])
logger = logging.getLogger(__name__)

def get_current_user(request: Request) -> User:
    return request.state.current_user

@router.get("/health")
def health():
    return {"status": "ok"}

@router.post("/conversation", response_model=ChatOutput)
async def post_message_with_optional_file(
    current_user: User = Depends(get_current_user),
    message: str = Form(...),
    conversation_id: Optional[str] = Form(None),
    bot_id: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
):
    logger.info(f"Received chat request from user '{current_user.id}'")
    
    final_message_content = message
    
    if file:
        logger.info(f"File received: {file.filename}, content-type: {file.content_type}")
        
        if file.content_type != "application/pdf":
            raise HTTPException(status_code=400, detail="Unsupported file type. Please upload a PDF.")

        try:
            # Leemos el contenido del archivo en memoria
            pdf_content = await file.read()
            
            # /-------------------------------------------------------------------\
            # |           NUEVA LÓGICA DE LECTURA DE PDF CON PyMuPDF            |
            # \-------------------------------------------------------------------/
            pdf_text = ""
            with fitz.open(stream=pdf_content, filetype="pdf") as doc:
                for page in doc:
                    pdf_text += page.get_text()
            # /-------------------------------------------------------------------\
            
            if not pdf_text.strip():
                logger.warning(f"PyMuPDF could not extract text from '{file.filename}'. The file might be image-based or empty.")
            else:
                logger.info(f"PyMuPDF extracted {len(pdf_text)} characters from PDF '{file.filename}'")

            final_message_content = f"""
Mensaje del usuario: {message}

Contenido del documento adjunto ({file.filename}):
---
{pdf_text}
---
"""
        except Exception as e:
            logger.error(f"Failed to process PDF file with PyMuPDF: {e}")
            raise HTTPException(status_code=500, detail=f"Error processing PDF file: {e}")
        finally:
            await file.close()

    # Construimos el objeto `ChatInput` en el formato complejo que la función `chat` espera
    chat_input = ChatInput(
        conversation_id=conversation_id,
        bot_id=bot_id,
        message={
            "role": "user",
            "content": [
                {
                    "contentType": "text",
                    "body": final_message_content
                }
            ],
            "model": "claude-v3-sonnet", 
            "parentMessageId": None,
            "feedback": None,
        },
    )
    
    return chat(user_id=current_user.id, chat_input=chat_input)


# --- EL RESTO DE TUS ENDPOINTS (SIN CAMBIOS) ---
@router.get("/conversations", response_model=list[ConversationMetaOutput])
# ... (el resto del archivo sigue igual) ...
# ...
def get_all_conversations(current_user: User = Depends(get_current_user)):
    conversations = find_conversation_by_user_id(current_user.id)
    return [
        ConversationMetaOutput(
            id=c.id, title=c.title, create_time=c.create_time, model=c.model, bot_id=c.bot_id,
        ) for c in conversations
    ]

@router.post("/conversation/related-documents", response_model=list[RelatedDocumentsOutput] | None)
def get_related_documents(chat_input: ChatInput, current_user: User = Depends(get_current_user)):
    return fetch_related_documents(user_id=current_user.id, chat_input=chat_input)

@router.get("/conversation/{conversation_id}", response_model=Conversation)
def get_conversation(conversation_id: str, current_user: User = Depends(get_current_user)):
    return fetch_conversation(current_user.id, conversation_id)

@router.delete("/conversation/{conversation_id}")
def remove_conversation(conversation_id: str, current_user: User = Depends(get_current_user)):
    delete_conversation_by_id(current_user.id, conversation_id)

@router.delete("/conversations")
def remove_all_conversations(current_user: User = Depends(get_current_user)):
    delete_conversation_by_user_id(current_user.id)

@router.patch("/conversation/{conversation_id}/title")
def patch_conversation_title(conversation_id: str, new_title_input: NewTitleInput, current_user: User = Depends(get_current_user)):
    change_conversation_title(current_user.id, conversation_id, new_title_input.new_title)

@router.get("/conversation/{conversation_id}/proposed-title", response_model=ProposedTitle)
def get_proposed_title(conversation_id: str, current_user: User = Depends(get_current_user)):
    title = propose_conversation_title(current_user.id, conversation_id)
    try:
        change_conversation_title(current_user.id, conversation_id, title)
    except Exception as e:
        logger.error(f"Failed to save new title for conversation {conversation_id}: {e}")
    return ProposedTitle(title=title)

@router.put("/conversation/{conversation_id}/{message_id}/feedback", response_model=FeedbackOutput)
def put_feedback(conversation_id: str, message_id: str, feedback_input: FeedbackInput, current_user: User = Depends(get_current_user)):
    update_feedback(
        user_id=current_user.id, conversation_id=conversation_id, message_id=message_id,
        feedback=FeedbackModel(
            thumbs_up=feedback_input.thumbs_up, category=feedback_input.category or "", comment=feedback_input.comment or "",
        )
    )
    return FeedbackOutput(thumbs_up=feedback_input.thumbs_up, category=feedback_input.category or "", comment=feedback_input.comment or "")