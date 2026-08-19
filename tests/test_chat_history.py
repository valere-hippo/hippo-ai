from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tier_ai.chat import answer_general_question, answer_project_question


class ChatHistoryTest(unittest.TestCase):
    def test_answer_general_question_persists_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            history_root = Path(temp_dir)
            response = answer_general_question(
                question="Hallo hippo-ai",
                history_root=history_root,
                prefer_real_models=False,
            )

            self.assertTrue(response.answer)
            history_path = history_root / "chat" / "general.json"
            self.assertTrue(history_path.exists())

            messages = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(len(messages), 2)
            self.assertEqual(messages[0]["role"], "user")
            self.assertEqual(messages[0]["content"], "Hallo hippo-ai")
            self.assertEqual(messages[1]["role"], "assistant")
            self.assertTrue(messages[1]["content"])

    def test_answer_project_question_persists_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            project_root.mkdir(parents=True, exist_ok=True)

            fake_search = SimpleNamespace(
                index_path=str(project_root / "index"),
                total_candidates=3,
                returned_hits=1,
                backend="local",
                project_slug="beispiel",
            )

            with patch("tier_ai.chat.prepare_project_question", return_value=(fake_search, [])), patch(
                "tier_ai.chat._generate_answer",
                return_value=("Antwort [S1]", ["S1"]),
            ):
                response = answer_project_question(
                    project_id="abc123",
                    project_slug="beispiel",
                    question="Welche Dateien gibt es?",
                    index_root=project_root / "index",
                    project_data_root=project_root,
                    prefer_real_models=False,
                )

            self.assertEqual(response.project_id, "abc123")
            history_path = project_root / "chat" / "history.json"
            self.assertTrue(history_path.exists())

            messages = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(len(messages), 2)
            self.assertEqual(messages[0]["role"], "user")
            self.assertEqual(messages[1]["role"], "assistant")
            self.assertEqual(messages[1]["citations"], ["S1"])


if __name__ == "__main__":
    unittest.main()
