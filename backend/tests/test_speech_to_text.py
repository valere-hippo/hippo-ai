from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import app.services.speech_to_text as speech_to_text


class FakeModel:
    def transcribe(self, audio_path, language=None, vad_filter=None):
        assert language == "de"
        assert vad_filter is True
        return (
            [
                SimpleNamespace(text="Hallo"),
                SimpleNamespace(text="Welt"),
                SimpleNamespace(text=""),
            ],
            SimpleNamespace(language="de"),
        )


def test_transcribe_audio_file_joins_segments():
    with patch.object(speech_to_text, "_load_model", return_value=FakeModel()):
        assert speech_to_text.transcribe_audio_file("/tmp/sample.webm") == "Hallo Welt"
