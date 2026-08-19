# GPU Hub Setup

This document describes the external model services hippo-ai expects when the
models are hosted in GPU Hub.

Production mode for `hippo-ai` should be GPU Hub-first. The app should call the
remote model services for chat, embeddings, and reranking. Local model fallback
is only for development and must be disabled in production by setting:

```bash
HIPPO_AI_MODEL_MODE=remote
```

## Services to expose

### 1. Main chat model

- Model: `Qwen3-30B-A3B-Instruct-2507`
- Serving mode: `vLLM`
- Endpoint: `POST /v1/chat/completions`
- Recommended use: project chat, report drafting, agent reasoning

### 2. Fast assistant model

- Model: `Qwen3-8B-Instruct`
- Serving mode: `vLLM`
- Endpoint: `POST /v1/chat/completions`
- Recommended use: quick responses, routing, smaller tasks

### 3. Embedding model

- Model: `BAAI/bge-m3`
- Endpoint: `POST /v1/embeddings`
- Recommended use: project index embeddings, retrieval

### 4. Reranker

- Model: `BAAI/bge-reranker-v2-m3`
- Endpoint: `POST /v1/rerank`
- Recommended use: reranking retrieval hits

### 5. Vector store

- Service: `Qdrant`
- Endpoint: `http://<host>:6333`
- Recommended use: project document index

## Environment variables for hippo-ai

Set these in `.env` or in the backend runtime environment:

```bash
HIPPO_AI_QDRANT_URL=http://qdrant:6333
HIPPO_AI_EMBEDDING_URL=http://gpu-hub:8001/v1/embeddings
HIPPO_AI_EMBEDDING_MODEL=BAAI/bge-m3
HIPPO_AI_RERANKER_URL=http://gpu-hub:8002/v1/rerank
HIPPO_AI_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
HIPPO_AI_LLM_URL=http://gpu-hub:8000/v1/chat/completions
HIPPO_AI_LLM_MODEL=Qwen3-30B-A3B-Instruct-2507
HIPPO_AI_ASSISTANT_MODEL=Qwen3-8B-Instruct
HIPPO_AI_REMOTE_TIMEOUT_SECONDS=60
```

## Notes

- In production, `hippo-ai` should use GPU Hub endpoints only.
- Retrieval and chat will use the remote endpoints when they are configured.
- If `HIPPO_AI_MODEL_MODE=remote` is set and an endpoint is missing, `hippo-ai`
  fails fast so the deployment is never silently local.
