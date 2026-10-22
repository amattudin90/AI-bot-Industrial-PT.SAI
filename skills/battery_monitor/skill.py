"""Battery monitor skill 

- Evaluates thresholds: low <=10%, near-full >=99%
- Can read real Windows battery via psutil (fallback: WinAPI)
- Does NOT start its own scheduler (bot.py job_queue does that)
- Does NOT send Telegram messages itself (bot.py notifies)
"""
from __future__ import annotations

import logging
import sys
from typing import Any, Dict, Optional, Tuple

from core.skill_manager import SkillResult

logger = logging.getLogger(__name__)


def _read_battery_windows() -> Tuple[Optional[int], Optional[bool]]:
    """Return (percent 0-100, plugged_in) or (None, None) on failure."""
    # 1) psutil if installed
    try:
        import psutil  # type: ignore
        bat = psutil.sensors_battery()
        if bat is not None:
            pct = int(bat.percent) if bat.percent is not None else None
            plugged = bool(bat.power_plugged) if bat.power_plugged is not None else None
            return pct, plugged
    except Exception as e:
        logger.debug("psutil battery failed: %s", e)

    # 2) WinAPI GetSystemPowerStatus
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class SYSTEM_POWER_STATUS(ctypes.Structure):
                _fields_ = [
                    ("ACLineStatus", wintypes.BYTE),
                    ("BatteryFlag", wintypes.BYTE),
                    ("BatteryLifePercent", wintypes.BYTE),
                    ("SystemStatusFlag", wintypes.BYTE),
                    ("BatteryLifeTime", wintypes.DWORD),
                    ("BatteryFullLifeTime", wintypes.DWORD),
                ]

            status = SYSTEM_POWER_STATUS()
            if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)) == 0:
                return None, None
            pct = status.BatteryLifePercent
            if pct == 255:  # unknown
                return None, None
            plugged = status.ACLineStatus == 1
            return int(pct), plugged
        except Exception as e:
            logger.warning("WinAPI battery failed: %s", e)

    return None, None


class BatteryMonitorSkill:
    name = "battery_monitor"
    description = (
        "Pantau baterai laptop: alert <=10% atau >=99%. "
        "Bisa baca level Windows asli; notifikasi dikirim bot saat skill AKTIF."
    )
    enabled_by_default = False

    LOW_THRESHOLD = 10
    HIGH_THRESHOLD = 99

    async def handle(
        self,
        action: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> SkillResult:
        payload = payload or {}
        action = (action or "").strip().lower()

        if action == "read":
            return self._action_read()

        if action == "check_threshold":
            return self._action_check(payload)

        if action == "check_real":
            # read hardware then evaluate thresholds
            read = self._action_read()
            if not read.ok:
                return read
            percent = read.data.get("percent")
            return self._action_check({"percent": percent}, extra=read.data)

        return SkillResult(
            False,
            "Aksi tidak dikenal. Gunakan: check_threshold | read | check_real",
        )

    # ------------------------------------------------------------------ helpers
    def _action_read(self) -> SkillResult:
        percent, plugged = _read_battery_windows()
        if percent is None:
            return SkillResult(
                False,
                "Gagal membaca level baterai. Pastikan psutil terpasang "
                "atau bot jalan di Windows.",
            )
        plug_txt = "colok (AC)" if plugged else "baterai (DC)" if plugged is not None else "status AC tidak diketahui"
        return SkillResult(
            True,
            f"Baterai sekarang {percent}% ({plug_txt}).",
            {"percent": percent, "plugged": plugged},
        )

    def _action_check(
        self,
        payload: Dict[str, Any],
        extra: Optional[Dict[str, Any]] = None,
    ) -> SkillResult:
        level = payload.get("percent")
        if isinstance(level, bool) or not isinstance(level, (int, float)):
            return SkillResult(False, "Persentase baterai harus berupa angka 0 sampai 100.")
        if not 0 <= float(level) <= 100:
            return SkillResult(False, "Persentase baterai harus berada di rentang 0 sampai 100.")

        level = int(level)
        if level <= self.LOW_THRESHOLD:
            message = f"Peringatan baterai rendah: {level}% (ambang <= {self.LOW_THRESHOLD}%)."
            state = "low"
            alert = True
        elif level >= self.HIGH_THRESHOLD:
            message = f"Peringatan baterai hampir penuh: {level}% (ambang >= {self.HIGH_THRESHOLD}%)."
            state = "near_full"
            alert = True
        else:
            message = f"Baterai {level}%: berada di antara ambang peringatan."
            state = "normal"
            alert = False

        data: Dict[str, Any] = {"percent": level, "state": state, "alert": alert}
        if extra:
            data.update({k: v for k, v in extra.items() if k not in data})
        return SkillResult(True, message, data)
