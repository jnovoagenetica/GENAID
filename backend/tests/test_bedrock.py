import sys
import os
import boto3
from ulid import ULID
from dotenv import load_dotenv

sys.path.append(".")

import unittest
from pprint import pprint

from app.bedrock import (
    calculate_query_embedding,
    call_converse_api,
    compose_args_for_converse_api,
)
from app.repositories.models.conversation import ContentModel, MessageModel
from app.repositories.models.custom_bot_guardrails import BedrockGuardrailsModel
from app.routes.schemas.conversation import type_model_name

# Cargar variables de entorno desde .env.local
load_dotenv(dotenv_path=".env.local")

# Configuración AWS desde entorno
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

MODEL: type_model_name = "claude-v3.5-sonnet"


def get_bedrock_client(service="bedrock"):
    """Devuelve un cliente boto3 usando credenciales del .env.local"""
    return boto3.client(
        service,
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )


class TestBedrockEmbedding(unittest.TestCase):
    def test_calculate_query_embedding(self):
        question = "こんにちは"
        embeddings = calculate_query_embedding(question)
        self.assertEqual(len(embeddings), 1024)
        self.assertEqual(type(embeddings), list)
        self.assertEqual(type(embeddings[0]), float)


class TestCallConverseApi(unittest.TestCase):
    def test_call_converse_api(self):
        message = MessageModel(
            role="user",
            content=[
                ContentModel(
                    content_type="text",
                    media_type=None,
                    body="Hello, World!",
                    file_name=None,
                )
            ],
            model=MODEL,
            children=[],
            parent=None,
            create_time=0,
            feedback=None,
            used_chunks=None,
            thinking_log=None,
        )
        arg = compose_args_for_converse_api(
            [message],
            MODEL,
            instruction=None,
            stream=False,
            generation_params=None,
        )

        response = call_converse_api(arg)
        pprint(response)


class TestCallConverseApiWithGuardrails(unittest.TestCase):
    def setUp(self):
        self.bedrock_client = get_bedrock_client("bedrock")
        self.guardrail_name = f"test-guardrail-{ULID()}"

        res = self.bedrock_client.create_guardrail(
            name=self.guardrail_name,
            description="Test guardrail for unit tests",
            contentPolicyConfig={
                "filtersConfig": [
                    {"type": "SEXUAL", "inputStrength": "LOW", "outputStrength": "LOW"},
                ]
            },
            blockedInputMessaging="blocked",
            blockedOutputsMessaging="blocked",
        )

        res_ver = self.bedrock_client.create_guardrail_version(
            guardrailIdentifier=res["guardrailArn"],
        )

        self.guardrail = BedrockGuardrailsModel(
            is_guardrail_enabled=True,
            hate_threshold=0,
            insults_threshold=0,
            sexual_threshold=1,
            violence_threshold=0,
            misconduct_threshold=0,
            grounding_threshold=0,
            relevance_threshold=0,
            guardrail_arn=res["guardrailArn"],
            guardrail_version=res_ver["version"],
        )
        self.guardrail_arn = res["guardrailArn"]

    def tearDown(self):
        print("Cleaning up...")
        try:
            self.bedrock_client.delete_guardrail(guardrailIdentifier=self.guardrail_arn)
        except Exception as e:
            print(f"Error deleting guardrail: {e}")

    def test_call_converse_api_with_guardrails(self):
        message = MessageModel(
            role="user",
            content=[
                ContentModel(
                    content_type="text",
                    media_type=None,
                    body="Hello, World!",
                    file_name=None,
                )
            ],
            model=MODEL,
            children=[],
            parent=None,
            create_time=0,
            feedback=None,
            used_chunks=None,
            thinking_log=None,
        )
        arg = compose_args_for_converse_api(
            [message],
            MODEL,
            instruction=None,
            stream=False,
            generation_params=None,
            grounding_source=None,
            guardrail=self.guardrail,
        )

        pprint(arg)

        response = call_converse_api(arg)
        pprint(response)


if __name__ == "__main__":
    unittest.main()
