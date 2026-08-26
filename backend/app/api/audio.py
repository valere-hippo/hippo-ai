from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.dependencies import get_current_user
from app.services.speech_to_text import transcribe_audio_file

router = APIRouter(prefix="/audio", tags=["audio"])


@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...), current_user=Depends(get_current_user)):
    raw = await file.read()
    if not raw:
        return {"text": ""}

    suffix = Path(file.filename or "").suffix or ".webm"
    tmp_path: Path | None = None
    try:
        with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw)
            tmp.flush()
            tmp_path = Path(tmp.name)

        text = transcribe_audio_file(tmp_path)
        return {"text": text}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"Der lokale Transkriptionsdienst ist nicht verfügbar: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Fehler bei der Transkription: {exc}")
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
