"""Laptop control skill 

Lock action is implemented for Windows only, via LockWorkStation.
No arbitrary shell; single fixed API call. Bot layer must enforce allowlist
and (optionally) confirmation before calling action='lock'.
"""
from __future__ import annotations

import logging
import sys
from typing import Any, Dict, Optional

from core.skill_manager import SkillResult

logger = logging.getLogger(__name__)


def _lock_windows() -> tuple[bool, str]:
    """Lock the interactive Windows session. Returns (ok, message)."""
    if sys.platform != "win32":
        return False, "Lock hanya didukung di Windows (platform saat ini bukan win32)."
    try:
        import ctypes
        # LockWorkStation returns non-zero on success
        ok = bool(ctypes.windll.user32.LockWorkStation())
        if ok:
            return True, "Laptop dikunci (LockWorkStation)."
        return False, "LockWorkStation mengembalikan gagal (kode 0)."
    except Exception as e:
        logger.exception("Lock failed")
        return False, f"Gagal mengunci laptop: {e}"


class LaptopControlSkill:
    name = "laptop_control"
    description = (
        "Kontrol laptop: kunci sesi Windows (LockWorkStation). "
        "Hanya jalan jika skill AKTIF dan dipanggil lewat perintah bot yang diizinkan."
    )
    enabled_by_default = False

    async def handle(
        self,
        action: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> SkillResult:
        action = (action or "").strip().lower()

        if action == "status":
            return SkillResult(
                True,
                "Laptop control siap. Aksi 'lock' memakai LockWorkStation di Windows.",
                {"lock_implemented": True, "platform": sys.platform},
            )

        if action == "lock":
            # Safety: require explicit confirm flag from bot layer
            payload = payload or {}
            if not payload.get("confirm"):
                return SkillResult(
                    False,
                    "Lock dibatalkan: konfirmasi diperlukan. "
                    "Pakai tombol konfirmasi atau /lock_confirm.",
                    {"needs_confirm": True},
                )
            ok, msg = _lock_windows()
            return SkillResult(ok, msg, {"executed": ok})

        return SkillResult(
            False,
            "Aksi tidak dikenal. Aksi yang didukung: lock | status",
        )
