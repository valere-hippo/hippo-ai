from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


def normalize_service_url(url: str, default_path: str) -> str:
    value = url.strip().rstrip("/")
    if not value:
        raise ValueError("service url is empty")
    if value.endswith(default_path):
        return value
    if value.endswith("/v1"):
        return f"{value}{default_path.removeprefix('/v1')}"
    if value.endswith("/"):
        value = value.rstrip("/")
    if default_path.startswith("/"):
        return f"{value}{default_path}"
    return f"{value}/{default_path}"


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:  # pragma: no cover - network error handling
        detail = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else ""
        raise RuntimeError(f"remote service responded with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:  # pragma: no cover - network error handling
        raise RuntimeError(f"remote service request failed: {exc.reason}") from exc
    return json.loads(raw) if raw.strip() else {}


@dataclass(slots=True)
class OpenAICompatibleEmbeddingClient:
    base_url: str
    model_name: str
    api_key: str | None = None
    timeout: int = 60

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self.model_name, "input": texts}
        response = _post_json(self.endpoint, payload, api_key=self.api_key, timeout=self.timeout)
        return self._parse_embeddings(response, len(texts))

    @property
    def endpoint(self) -> str:
        return normalize_service_url(self.base_url, "/v1/embeddings")

    def _parse_embeddings(self, response: dict[str, Any], expected: int) -> list[list[float]]:
        if "data" in response and isinstance(response["data"], list):
            indexed: list[tuple[int, list[float]]] = []
            for item in response["data"]:
                if not isinstance(item, dict):
                    continue
                embedding = item.get("embedding")
                if isinstance(embedding, list):
                    index = int(item.get("index", len(indexed)))
                    indexed.append((index, [float(value) for value in embedding]))
            if indexed:
                indexed.sort(key=lambda item: item[0])
                return [embedding for _, embedding in indexed][:expected]
        for key in ("embeddings", "vectors", "data_embeddings"):
            value = response.get(key)
            if isinstance(value, list) and value and isinstance(value[0], list):
                return [[float(item) for item in embedding] for embedding in value][:expected]
        raise RuntimeError("remote embeddings response did not contain embeddings")


@dataclass(slots=True)
class OpenAICompatibleRerankerClient:
    base_url: str
    model_name: str
    api_key: str | None = None
    timeout: int = 60

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        payload = {"model": self.model_name, "query": query, "documents": documents}
        response = _post_json(self.endpoint, payload, api_key=self.api_key, timeout=self.timeout)
        return self._parse_scores(response, len(documents))

    @property
    def endpoint(self) -> str:
        return normalize_service_url(self.base_url, "/v1/rerank")

    def _parse_scores(self, response: dict[str, Any], expected: int) -> list[float]:
        if "scores" in response and isinstance(response["scores"], list):
            scores = [float(value) for value in response["scores"]]
            return scores[:expected]
        if "data" in response and isinstance(response["data"], list):
            indexed: list[tuple[int, float]] = []
            for item in response["data"]:
                if not isinstance(item, dict):
                    continue
                if "score" not in item:
                    continue
                index = int(item.get("index", len(indexed)))
                indexed.append((index, float(item["score"])))
            if indexed:
                indexed.sort(key=lambda item: item[0])
                return [score for _, score in indexed][:expected]
        for key in ("results", "rerank_scores"):
            value = response.get(key)
            if isinstance(value, list):
                return [float(item) for item in value][:expected]
        raise RuntimeError("remote rerank response did not contain scores")


@dataclass(slots=True)
class OpenAICompatibleChatClient:
    base_url: str
    model_name: str
    api_key: str | None = None
    timeout: int = 60

    def chat(self, messages: list[dict[str, Any]], *, temperature: float = 0.2) -> str:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
        }
        response = _post_json(self.endpoint, payload, api_key=self.api_key, timeout=self.timeout)
        return self._parse_message(response)

    @property
    def endpoint(self) -> str:
        return normalize_service_url(self.base_url, "/v1/chat/completions")

    def _parse_message(self, response: dict[str, Any]) -> str:
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0]
            if isinstance(choice, dict):
                message = choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content
                delta = choice.get("delta")
                if isinstance(delta, dict):
                    content = delta.get("content")
                    if isinstance(content, str):
                        return content
        if isinstance(response.get("output"), str):
            return response["output"]
        raise RuntimeError("remote chat response did not contain a message")
