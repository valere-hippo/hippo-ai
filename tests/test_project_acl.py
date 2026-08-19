from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

if FASTAPI_AVAILABLE:
    from backend.app.auth import verify_credentials
    from backend.app.models import ProjectCreate, UserCreate
    from backend.app.project_store import ProjectStore
    from backend.app.users import UserStore
    from backend.app.audit import list_audit_events, write_audit
    from backend.app.settings import get_settings
else:  # pragma: no cover - depends on local dev environment
    verify_credentials = None  # type: ignore[assignment]
    ProjectCreate = None  # type: ignore[assignment]
    UserCreate = None  # type: ignore[assignment]
    ProjectStore = None  # type: ignore[assignment]
    UserStore = None  # type: ignore[assignment]
    list_audit_events = None  # type: ignore[assignment]
    write_audit = None  # type: ignore[assignment]
    get_settings = None  # type: ignore[assignment]


class ProjectAclTests(unittest.TestCase):
    @unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi ist lokal nicht installiert")
    def test_project_visibility_and_sharing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir) / "workspace"
            original_env = {key: os.environ.get(key) for key in ["HIPPO_AI_DATA_ROOT", "HIPPO_AI_ADMIN_USER", "HIPPO_AI_ADMIN_PASSWORD", "HIPPO_AI_JWT_SECRET"]}
            try:
                os.environ["HIPPO_AI_DATA_ROOT"] = str(data_root)
                os.environ["HIPPO_AI_ADMIN_USER"] = "hippo"
                os.environ["HIPPO_AI_ADMIN_PASSWORD"] = "hippo"
                os.environ["HIPPO_AI_JWT_SECRET"] = "test-secret"
                get_settings.cache_clear()

                users = UserStore()
                self.assertTrue(verify_credentials("hippo", "hippo"))
                collaborator = users.create_user(
                    UserCreate(username="alice", display_name="Alice", role="member", password="secret")
                )
                self.assertEqual(collaborator.username, "alice")

                store = ProjectStore()
                project = store.create_project(ProjectCreate(name="Access Test"), owner_username="hippo")
                self.assertEqual(project.owner_username, "hippo")

                visible_for_owner = store.list_projects("hippo", "admin")
                self.assertTrue(any(item.id == project.id for item in visible_for_owner))

                visible_for_collaborator = store.list_projects("alice", "member")
                self.assertFalse(any(item.id == project.id for item in visible_for_collaborator))

                shared = store.share_project(project.id, "alice", ["read", "export"], granted_by="hippo")
                self.assertTrue(any(share.username == "alice" for share in shared.shared_with))
                self.assertTrue(store.can_access(shared, "alice", "read"))
                self.assertTrue(store.can_access(shared, "alice", "export"))
                self.assertFalse(store.can_access(shared, "alice", "write"))
                self.assertTrue(store.can_manage_shares(shared, "hippo"))

                visible_for_collaborator = store.list_projects("alice", "member")
                self.assertTrue(any(item.id == project.id for item in visible_for_collaborator))
            finally:
                for key, value in original_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
                get_settings.cache_clear()

    @unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi ist lokal nicht installiert")
    def test_audit_log_is_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir) / "workspace"
            original_env = {key: os.environ.get(key) for key in ["HIPPO_AI_DATA_ROOT", "HIPPO_AI_ADMIN_USER", "HIPPO_AI_ADMIN_PASSWORD", "HIPPO_AI_JWT_SECRET"]}
            try:
                os.environ["HIPPO_AI_DATA_ROOT"] = str(data_root)
                os.environ["HIPPO_AI_ADMIN_USER"] = "hippo"
                os.environ["HIPPO_AI_ADMIN_PASSWORD"] = "hippo"
                os.environ["HIPPO_AI_JWT_SECRET"] = "test-secret"
                get_settings.cache_clear()

                write_audit("project.create", "project", "p1", "hippo", {"name": "Demo"})
                write_audit("project.share", "project", "p1", "hippo", {"target_user": "alice"})

                events = list_audit_events(subject_type="project", subject_id="p1")
                self.assertGreaterEqual(len(events), 2)
                self.assertEqual(events[0].subject_id, "p1")
                self.assertTrue(any(event.action == "project.share" for event in events))
            finally:
                for key, value in original_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
                get_settings.cache_clear()


if __name__ == "__main__":
    unittest.main()
