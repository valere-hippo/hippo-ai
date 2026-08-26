from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from app.api.dependencies import get_current_user, DbSession
from app.core.config import settings
import httpx

router = APIRouter(prefix="/audio", tags=["audio"])

@router.post('/transcribe')
async def transcribe_audio(file: UploadFile = File(...), current_user = Depends(get_current_user)):
    if not settings.whisper_api_url or not settings.whisper_api_key:
        raise HTTPException(status_code=503, detail='Transcription service not configured')
    # read bytes
    data = await file.read()
    headers = {"Authorization": f"Bearer {settings.whisper_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            files = {'file': (file.filename, data, file.content_type)}
            r = await client.post(settings.whisper_api_url.rstrip('/') + '/v1/transcribe', headers=headers, files=files)
            r.raise_for_status()
            res = r.json()
            # expect { 'text': 'transcript' }
            if isinstance(res, dict) and 'text' in res:
                return {'text': res['text']}
            # fallback: try common keys
            if isinstance(res, dict) and 'transcript' in res:
                return {'text': res['transcript']}
            return {'text': str(res)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f'Transcription error: {e}')
