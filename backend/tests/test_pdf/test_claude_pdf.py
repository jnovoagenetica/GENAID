import base64
from pathlib import Path
from datetime import datetime
from uuid import uuid4

from app.bedrock import compose_args_for_converse_api, call_converse_api
from app.repositories.models.conversation import ContentModel, MessageModel
from app.routes.schemas.conversation import type_model_name

def test_send_pdf_to_claude():
    # ✅ Ruta al archivo PDF
    pdf_path = Path(__file__).parent.parent / "example_files" / "Conversacion de video.pdf"
    assert pdf_path.exists(), f"❌ El archivo no existe en {pdf_path}"

    # 📥 Leer y codificar archivo
    file_bytes = pdf_path.read_bytes()
    file_base64 = base64.b64encode(file_bytes).decode("utf-8")

    # 📦 Crear mensaje con campos requeridos
    message = MessageModel(
        id=str(uuid4()),
        role="user",
        content=[
            ContentModel(
                content_type="textAttachment",
                body=file_base64,
                media_type="application/pdf",
                file_name="Conversacion de video.pdf",
            )
        ],
        model="claude-v3.5-sonnet",
        children=[],
        parent=None,
        create_time=datetime.now().timestamp(),  # 👈 Aquí el cambio
        feedback=None,
        used_chunks=None,
    )

    # 🧠 Componer argumentos y enviar
    args = compose_args_for_converse_api(
        messages=[message],
        model="claude-v3.5-sonnet",  # ✅ Esto es lo correcto
        instruction="Resume el contenido del archivo adjunto.",
        stream=False,
    )

    response = call_converse_api(args)

    # ✅ Mostrar respuesta
    print("\n✅ RESPUESTA DE CLAUDE:")
    print(response["output"]["message"])

if __name__ == "__main__":
    test_send_pdf_to_claude()
