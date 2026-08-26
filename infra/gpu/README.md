# HIPPO-AI GPU Node

This deployment is intentionally separate from the main HIPPO-AI application stack.
The GPU node runs model inference only; PostgreSQL/Redis/API remain on the application host.

## Services

- vLLM: OpenAI-compatible LLM API on localhost:8001
- Faster-Whisper Server: OpenAI-compatible transcription API on localhost:8002

The services are bound to `127.0.0.1` on purpose. Do not expose them directly to the public internet.
Put the HIPPO-AI API/reverse proxy in front of them later.

## 1. Copy configuration

```bash
cp .env.gpu.example .env.gpu
nano .env.gpu
```

Set a strong `VLLM_API_KEY` and `WHISPER_API_KEY`.

The default vLLM GPU utilization is intentionally 0.78 because vLLM and Whisper share the same 96 GB GPU. We can raise it after measuring real memory usage.

If your GPUHub data disk is mounted somewhere else, change `HIPPO_GPU_DATA_DIR`.

## 2. Prepare host

Run from this directory:

```bash
chmod +x *.sh
./bootstrap-host.sh
```

The script deliberately does **not** install or replace the NVIDIA GPU driver. GPUHub should provide the driver.

## 3. Verify GPU Docker access

```bash
./check.sh
```

## 4. Start models

```bash
./start.sh
```

The first start downloads model weights and can take time.

## 5. Check logs

```bash
docker logs -f hippo-ai-vllm
```

```bash
docker logs -f hippo-ai-whisper
```

## 6. Check vLLM

```bash
curl -H "Authorization: Bearer YOUR_VLLM_API_KEY" http://127.0.0.1:8001/v1/models
```

## 7. Check Whisper

The exact health endpoint can vary by image version. First inspect:

```bash
docker logs --tail=100 hippo-ai-whisper
```

Then test the OpenAI-compatible transcription endpoint with a sample audio file.

## Important production notes

- Do not commit `.env.gpu`.
- Do not expose ports 8001/8002 publicly.
- Pin image versions after the first successful validation instead of using `latest` forever.
- Model files are persisted on the data disk.
- We will later move the model calls behind the HIPPO-AI API and add TLS/auth/rate limiting.
