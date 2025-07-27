import argparse
import json
import logging
import multiprocessing
import os
from multiprocessing.managers import ListProxy
from typing import Any

import pg8000
import requests
from app.config import DEFAULT_EMBEDDING_CONFIG
from app.repositories.common import RecordNotFoundError, _get_table_client
from app.repositories.custom_bot import (
    compose_bot_id,
    decompose_bot_id,
    find_private_bot_by_id,
)
from app.routes.schemas.bot import type_sync_status
from app.utils import compose_upload_document_s3_path
from aws_lambda_powertools.utilities import parameters
from embedding.loaders import UrlLoader
from embedding.loaders.base import BaseLoader
from embedding.loaders.s3 import S3FileLoader
from embedding.wrapper import DocumentSplitter, Embedder
from llama_index.core.text_splitter import TokenTextSplitter  # <--- IMPORTACIÓN AÑADIDA
from retry import retry
from ulid import ULID

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
logger = logging.getLogger(__name__)

BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-east-1")
RETRIES_TO_INSERT_TO_POSTGRES = 4
RETRY_DELAY_TO_INSERT_TO_POSTGRES = 2
RETRIES_TO_UPDATE_SYNC_STATUS = 4
RETRY_DELAY_TO_UPDATE_SYNC_STATUS = 2

DB_SECRETS_ARN = os.environ.get("DB_SECRETS_ARN", "")
DOCUMENT_BUCKET = os.environ.get("DOCUMENT_BUCKET", "documents")

METADATA_URI = os.environ.get("ECS_CONTAINER_METADATA_URI_V4")


def get_exec_id() -> str:
    # Get task id from ECS metadata
    # Ref: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-metadata-endpoint-v4.html#task-metadata-endpoint-v4-enable
    response = requests.get(f"{METADATA_URI}/task")
    data = response.json()
    task_arn = data.get("TaskARN", "")
    task_id = task_arn.split("/")[-1]
    return task_id


@retry(tries=RETRIES_TO_INSERT_TO_POSTGRES, delay=RETRY_DELAY_TO_INSERT_TO_POSTGRES)
def insert_to_postgres(
    bot_id: str, contents: ListProxy, sources: ListProxy, embeddings: ListProxy
):
    secrets: Any = parameters.get_secret(DB_SECRETS_ARN)  # type: ignore
    db_info = json.loads(secrets)

    conn = pg8000.connect(
        database=db_info["dbname"],
        host=db_info["host"],
        port=db_info["port"],
        user=db_info["username"],
        password=db_info["password"],
    )

    try:
        with conn.cursor() as cursor:
            delete_query = "DELETE FROM items WHERE botid = %s"
            cursor.execute(delete_query, (bot_id,))

            insert_query = f"INSERT INTO items (id, botid, content, source, embedding) VALUES (%s, %s, %s, %s, %s)"
            values_to_insert = []
            for i, (source, content, embedding) in enumerate(
                zip(sources, contents, embeddings)
            ):
                id_ = str(ULID())
                logger.debug(f"Preview of content {i}: {content[:200]}")
                values_to_insert.append(
                    (id_, bot_id, content, source, json.dumps(embedding))
                )
            cursor.executemany(insert_query, values_to_insert)
        conn.commit()
        logger.info(f"Successfully inserted {len(values_to_insert)} records.")
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


@retry(tries=RETRIES_TO_UPDATE_SYNC_STATUS, delay=RETRY_DELAY_TO_UPDATE_SYNC_STATUS)
def update_sync_status(
    user_id: str,
    bot_id: str,
    sync_status: type_sync_status,
    sync_status_reason: str,
    last_exec_id: str,
):
    table = _get_table_client(user_id)
    table.update_item(
        Key={"PK": user_id, "SK": compose_bot_id(user_id, bot_id)},
        UpdateExpression="SET SyncStatus = :sync_status, SyncStatusReason = :sync_status_reason, LastExecId = :last_exec_id",
        ExpressionAttributeValues={
            ":sync_status": sync_status,
            ":sync_status_reason": sync_status_reason,
            ":last_exec_id": last_exec_id,
        },
    )


# --- INICIO DE LA SECCIÓN MODIFICADA ---
def embed(
    loader: BaseLoader,
    contents: ListProxy,
    sources: ListProxy,
    embeddings: ListProxy,
    chunk_size: int,
    chunk_overlap: int,
):
    # Se reemplaza SentenceSplitter por TokenTextSplitter.
    # TokenTextSplitter es más robusto para cortar texto por longitud, lo que garantiza
    # que ningún chunk exceda el límite del modelo de embeddings, incluso si el texto
    # no tiene una estructura clara de oraciones o párrafos.
    splitter = DocumentSplitter(
        splitter=TokenTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            # Se mantiene el truco del tokenizer por longitud de caracteres, que es
            # eficiente y adecuado para el modelo de Cohere.
            tokenizer=lambda text: [0] * len(text),
        )
    )
    embedder = Embedder(verbose=True)

    # Cargar documentos desde el loader (p. ej. S3)
    documents = loader.load()
    logger.info(f"Loaded {len(documents)} document(s) from loader.")
    for i, doc in enumerate(documents):
        logger.info(f"Document {i} initial size: {len(doc.text)} characters.")

    # Dividir los documentos en chunks más pequeños
    splitted = splitter.split_documents(documents)
    logger.info(f"Split documents into {len(splitted)} chunks.")
    # Loguear el tamaño de los primeros chunks para verificar
    for i, chunk in enumerate(splitted[:5]): # Loguear solo los primeros 5 para no saturar
        logger.info(f"Chunk {i} final size: {len(chunk.text)} characters.")
    
    if not splitted:
        logger.warning("Document splitting resulted in zero chunks. Nothing to embed.")
        return

    # Generar los embeddings para cada chunk
    splitted_embeddings = embedder.embed_documents(splitted)

    # Agregar los resultados a las listas compartidas para el procesamiento paralelo
    contents.extend([t.page_content for t in splitted])
    sources.extend([t.metadata["source"] for t in splitted])
    embeddings.extend(splitted_embeddings)

# --- FIN DE LA SECCIÓN MODIFICADA ---


def main(
    user_id: str,
    bot_id: str,
    sitemap_urls: list[str],
    source_urls: list[str],
    filenames: list[str],
    chunk_size: int,
    chunk_overlap: int,
    enable_partition_pdf: bool,
):
    exec_id = ""
    try:
        exec_id = get_exec_id()
    except Exception as e:
        logger.error(f"[ERROR] Failed to get exec_id: {e}")
        exec_id = "FAILED_TO_GET_ECS_EXEC_ID"

    update_sync_status(
        user_id,
        bot_id,
        "RUNNING",
        "",
        exec_id,
    )

    status_reason = ""
    try:
        if len(sitemap_urls) + len(source_urls) + len(filenames) == 0:
            logger.info("No contents to embed. Skipping.")
            status_reason = "No contents to embed."
            update_sync_status(
                user_id,
                bot_id,
                "SUCCEEDED",
                status_reason,
                exec_id,
            )
            return

        # Calcular embeddings
        with multiprocessing.Manager() as manager:
            contents: ListProxy = manager.list()
            sources: ListProxy = manager.list()
            embeddings: ListProxy = manager.list()

            if len(source_urls) > 0:
                embed(
                    UrlLoader(source_urls),
                    contents,
                    sources,
                    embeddings,
                    chunk_size,
                    chunk_overlap,
                )
            if len(sitemap_urls) > 0:
                for sitemap_url in sitemap_urls:
                    raise NotImplementedError()
            if len(filenames) > 0:
                with multiprocessing.Pool(processes=None) as pool:
                    futures = [
                        pool.apply_async(
                            embed,
                            args=(
                                S3FileLoader(
                                    bucket=DOCUMENT_BUCKET,
                                    key=compose_upload_document_s3_path(
                                        user_id, bot_id, filename
                                    ),
                                    enable_partition_pdf=enable_partition_pdf,
                                ),
                                contents,
                                sources,
                                embeddings,
                                chunk_size,
                                chunk_overlap,
                            ),
                        )
                        for filename in filenames
                    ]
                    for future in futures:
                        future.get()

            logger.info(f"Total number of chunks to be inserted: {len(contents)}")

            if len(contents) > 0:
                # Insert records into postgres
                insert_to_postgres(bot_id, contents, sources, embeddings)
                status_reason = "Successfully inserted to vector store."
            else:
                logger.warning("No content was generated to be inserted into the vector store.")
                status_reason = "Source data did not produce any content to be embedded."

    except Exception as e:
        logger.error("[ERROR] Failed to embed.", exc_info=True)
        update_sync_status(
            user_id,
            bot_id,
            "FAILED",
            f"{e}",
            exec_id,
        )
        return

    update_sync_status(
        user_id,
        bot_id,
        "SUCCEEDED",
        status_reason,
        exec_id,
    )


if __name__ == "__main__":
    # Get dynamodb stream event
    event_json = os.getenv("EVENT")
    if not event_json:
        raise ValueError("Environment variable 'EVENT' is not set.")
        
    logger.debug(f"event_json: {event_json}")

    keys = json.loads(event_json)
    sk = keys["SK"]["S"]
    bot_id = decompose_bot_id(sk)

    pk = keys["PK"]["S"]
    user_id = pk

    try:
        new_image = find_private_bot_by_id(user_id, bot_id)
    except RecordNotFoundError:
        logger.error(f"Bot with id {bot_id} for user {user_id} not found. Aborting.")
        raise

    embedding_params = new_image.embedding_params
    chunk_size = embedding_params.chunk_size
    chunk_overlap = embedding_params.chunk_overlap
    enable_partition_pdf = embedding_params.enable_partition_pdf
    knowledge = new_image.knowledge
    sitemap_urls = knowledge.sitemap_urls
    source_urls = knowledge.source_urls
    filenames = knowledge.filenames

    logger.info(f"Starting embedding job for bot_id: {bot_id}")
    logger.info(f"source_urls to crawl: {source_urls}")
    logger.info(f"sitemap_urls to crawl: {sitemap_urls}")
    logger.info(f"filenames: {filenames}")
    logger.info(f"chunk_size: {chunk_size}")
    logger.info(f"chunk_overlap: {chunk_overlap}")
    logger.info(f"enable_partition_pdf: {enable_partition_pdf}")

    main(
        user_id,
        bot_id,
        sitemap_urls,
        source_urls,
        filenames,
        chunk_size,
        chunk_overlap,
        enable_partition_pdf,
    )