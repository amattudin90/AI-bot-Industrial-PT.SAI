"""Small offline regression tests for the skill registry."""
import asyncio
import tempfile
import unittest
from pathlib import Path

from core.skill_manager import SkillManager, SkillResult


class DemoSkill:
    name = "demo"
    description = "Test skill"
    enabled_by_default = False

    async def handle(self, action, payload):
        if action == "echo":
            return SkillResult(True, "ok", {"value": payload.get("value")})
        return SkillResult(False, "unsupported")


class SkillManagerTests(unittest.TestCase):
    def test_enable_dispatch_and_persist(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "skills_state.json"
            manager = SkillManager(state_path=state_path)
            manager.register(DemoSkill())

            disabled = asyncio.run(manager.dispatch("demo", "echo", {"value": 7}))
            self.assertFalse(disabled.ok)

            self.assertTrue(manager.enable("demo"))
            result = asyncio.run(manager.dispatch("demo", "echo", {"value": 7}))
            self.assertTrue(result.ok)
            self.assertEqual(result.data["value"], 7)

            restored = SkillManager(state_path=state_path)
            restored.register(DemoSkill())
            self.assertTrue(restored.is_enabled("demo"))

    def test_unknown_skill_returns_result(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = SkillManager(state_path=Path(folder) / "state.json")
            result = asyncio.run(manager.dispatch("missing", "anything", {}))
            self.assertFalse(result.ok)
            self.assertIn("tidak ditemukan", result.message)


if __name__ == "__main__":
    unittest.main()
