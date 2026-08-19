from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tier_ai.remote_clients import OpenAICompatibleChatClient, OpenAICompatibleEmbeddingClient, OpenAICompatibleRerankerClient


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - context manager protocol
        return None


class RemoteClientTests(unittest.TestCase):
    def test_openai_embedding_client_parses_data_payload(self) -> None:
        client = OpenAICompatibleEmbeddingClient(base_url="http://gpu-hub:8001/v1", model_name="BAAI/bge-m3")

        def fake_urlopen(request, timeout=60):
            self.assertTrue(request.full_url.endswith("/v1/embeddings"))
            payload = json.loads(request.data.decode("utf-8"))
            self.assertEqual(payload["model"], "BAAI/bge-m3")
            self.assertEqual(payload["input"], ["eins", "zwei"])
            return _FakeResponse(
                {
                    "data": [
                        {"index": 0, "embedding": [0.1, 0.2]},
                        {"index": 1, "embedding": [0.3, 0.4]},
                    ]
                }
            )

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            embeddings = client.embed(["eins", "zwei"])

        self.assertEqual(embeddings, [[0.1, 0.2], [0.3, 0.4]])

    def test_openai_reranker_client_parses_scores_payload(self) -> None:
        client = OpenAICompatibleRerankerClient(
            base_url="http://gpu-hub:8002",
            model_name="bge-reranker-v2-m3",
        )

        def fake_urlopen(request, timeout=60):
            self.assertTrue(request.full_url.endswith("/v1/rerank"))
            payload = json.loads(request.data.decode("utf-8"))
            self.assertEqual(payload["query"], "Amsel")
            self.assertEqual(payload["documents"], ["Dokument A", "Dokument B"])
            return _FakeResponse({"scores": [0.9, 0.1]})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            scores = client.rerank("Amsel", ["Dokument A", "Dokument B"])

        self.assertEqual(scores, [0.9, 0.1])

    def test_openai_chat_client_parses_message_payload(self) -> None:
        client = OpenAICompatibleChatClient(
            base_url="http://gpu-hub:8000",
            model_name="Qwen3-30B-A3B-Instruct-2507",
        )

        def fake_urlopen(request, timeout=60):
            self.assertTrue(request.full_url.endswith("/v1/chat/completions"))
            payload = json.loads(request.data.decode("utf-8"))
            self.assertEqual(payload["model"], "Qwen3-30B-A3B-Instruct-2507")
            self.assertEqual(payload["messages"][0]["role"], "user")
            return _FakeResponse({"choices": [{"message": {"content": "Hallo Hippo"}}]})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            message = client.chat([{"role": "user", "content": "Hallo"}])

        self.assertEqual(message, "Hallo Hippo")


if __name__ == "__main__":
    unittest.main()
