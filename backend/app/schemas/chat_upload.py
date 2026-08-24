from pydantic import BaseModel

class ChatUploadResponse(BaseModel):
    filename: str
    path: str
