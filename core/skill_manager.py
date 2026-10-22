"""
Skill registry for Factory AI.

Contract expected by skills:
  - skill.name: str
  - skill.description: str
  - skill.enabled_by_default: bool
  - async skill.handle(action, payload) -> SkillResult

Enable/disable state is persisted to data/skills_state.json so it survives restart.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default path: <cwd>/data/skills_state.json (Factory AI folder)
_STATE_PATH = Path(os.environ.get("SKILLS_STATE_PATH", "data/skills_state.json"))


@dataclass
class SkillResult:
    ok: bool
    message: str
    data: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.data is None:
            self.data = {}


def _load_state(path: Path) -> Dict[str, Any]:
    try:
        if path.is_file():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        logger.warning("Gagal baca skills state %s: %s", path, e)
    return {}


def _save_state(path: Path, data: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(path)
    except Exception as e:
        logger.warning("Gagal simpan skills state %s: %s", path, e)


class SkillManager:
    """In-memory registry with persisted enable flags + notify chat ids."""

    def __init__(self, state_path: Optional[Path] = None) -> None:
        self._skills: Dict[str, Any] = {}
        self._enabled: Dict[str, bool] = {}
        self._state_path = Path(state_path) if state_path else _STATE_PATH
        self._state = _load_state(self._state_path)
        # enabled map from disk (name -> bool)
        raw = self._state.get("enabled") or {}
        self._saved_enabled: Dict[str, bool] = {
            str(k).strip().lower(): bool(v) for k, v in raw.items()
        }
        # chat ids for battery notifications
        raw_chats = self._state.get("notify_chat_ids") or []
        self._notify_chat_ids: set = set()
        for c in raw_chats:
            try:
                self._notify_chat_ids.add(int(c))
            except (TypeError, ValueError):
                pass
        # poll interval seconds (battery)
        try:
            self._battery_poll_sec = int(self._state.get("battery_poll_sec") or 0)
        except (TypeError, ValueError):
            self._battery_poll_sec = 0

    # ------------------------------------------------------------------ persist
    def _persist(self) -> None:
        self._state["enabled"] = dict(self._enabled)
        self._state["notify_chat_ids"] = sorted(self._notify_chat_ids)
        if self._battery_poll_sec > 0:
            self._state["battery_poll_sec"] = self._battery_poll_sec
        _save_state(self._state_path, self._state)

    # ------------------------------------------------------------------ register
    def register(self, skill: Any) -> None:
        name = getattr(skill, "name", None)
        if not name or not isinstance(name, str):
            raise ValueError("Skill must have a non-empty string 'name'")
        name = name.strip().lower()
        self._skills[name] = skill
        # prefer saved state; else enabled_by_default
        if name in self._saved_enabled:
            self._enabled[name] = self._saved_enabled[name]
        else:
            self._enabled[name] = bool(getattr(skill, "enabled_by_default", False))

    def get(self, name: str) -> Optional[Any]:
        return self._skills.get((name or "").strip().lower())

    # ----------------------------------------------------------- enable/disable
    def enable(self, name: str) -> bool:
        key = (name or "").strip().lower()
        if key not in self._skills:
            return False
        self._enabled[key] = True
        self._persist()
        return True

    def disable(self, name: str) -> bool:
        key = (name or "").strip().lower()
        if key not in self._skills:
            return False
        self._enabled[key] = False
        self._persist()
        return True

    def is_enabled(self, name: str) -> bool:
        return bool(self._enabled.get((name or "").strip().lower(), False))

    # ----------------------------------------------------------- notify chats
    def add_notify_chat(self, chat_id: int) -> None:
        self._notify_chat_ids.add(int(chat_id))
        self._persist()

    def notify_chat_ids(self) -> List[int]:
        return list(self._notify_chat_ids)

    # ----------------------------------------------------------- poll interval
    def get_battery_poll_sec(self, default: int = 120) -> int:
        if self._battery_poll_sec >= 30:
            return self._battery_poll_sec
        return default

    def set_battery_poll_sec(self, seconds: int) -> int:
        seconds = int(seconds)
        if seconds < 30:
            raise ValueError("Interval minimal 30 detik.")
        if seconds > 3600:
            raise ValueError("Interval maksimal 3600 detik (1 jam).")
        self._battery_poll_sec = seconds
        self._persist()
        return seconds

    # ----------------------------------------------------------------- describe
    def describe(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for name, skill in self._skills.items():
            items.append({
                "name": name,
                "description": getattr(skill, "description", ""),
                "enabled": self._enabled.get(name, False),
            })
        return items

    # ----------------------------------------------------------------- dispatch
    async def dispatch(
        self,
        name: str,
        action: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> SkillResult:
        key = (name or "").strip().lower()
        skill = self._skills.get(key)
        if skill is None:
            return SkillResult(False, f"Skill '{name}' tidak ditemukan.")
        if not self._enabled.get(key, False):
            return SkillResult(False, f"Skill '{name}' belum diaktifkan.")
        try:
            result = await skill.handle(action, payload or {})
            if not isinstance(result, SkillResult):
                return SkillResult(False, "Skill mengembalikan hasil yang tidak valid.")
            return result
        except Exception as e:
            return SkillResult(False, f"Error di skill '{name}': {e}")
