"""System monitor skill — CPU, RAM, disk (read-only)."""
from __future__ import annotations

import logging
import shutil
from typing import Any, Dict, Optional

from core.skill_manager import SkillResult

logger = logging.getLogger(__name__)


def _stats() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    try:
        import psutil  # type: ignore

        data["cpu_percent"] = float(psutil.cpu_percent(interval=0.3))
        mem = psutil.virtual_memory()
        data["ram_percent"] = float(mem.percent)
        data["ram_used_gb"] = round(mem.used / (1024 ** 3), 2)
        data["ram_total_gb"] = round(mem.total / (1024 ** 3), 2)
        # disk: system drive on Windows (C:\), else root
        import sys

        root = "C:\\" if sys.platform == "win32" else "/"
        disk = psutil.disk_usage(root)
        data["disk_percent"] = float(disk.percent)
        data["disk_free_gb"] = round(disk.free / (1024 ** 3), 2)
        data["disk_total_gb"] = round(disk.total / (1024 ** 3), 2)
        data["disk_path"] = root
    except Exception as e:
        logger.warning("psutil stats failed: %s", e)
        # minimal disk fallback
        try:
            import sys

            root = "C:\\" if sys.platform == "win32" else "/"
            usage = shutil.disk_usage(root)
            data["disk_percent"] = round(100 * usage.used / usage.total, 1)
            data["disk_free_gb"] = round(usage.free / (1024 ** 3), 2)
            data["disk_total_gb"] = round(usage.total / (1024 ** 3), 2)
            data["disk_path"] = root
        except Exception as e2:
            logger.warning("disk fallback failed: %s", e2)
    return data


class SystemMonitorSkill:
    name = "system_monitor"
    description = (
        "Monitor sistem: CPU, RAM, disk (hanya baca). "
        "Perintah: /sys  atau teks 'cek cpu' / 'cek disk'."
    )
    enabled_by_default = False

    DISK_WARN = 90.0
    RAM_WARN = 90.0
    CPU_WARN = 95.0

    async def handle(
        self,
        action: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> SkillResult:
        action = (action or "").strip().lower()
        if action not in ("status", "check", "read"):
            return SkillResult(False, "Aksi tidak dikenal. Gunakan: status")

        s = _stats()
        if not s:
            return SkillResult(False, "Gagal membaca status sistem. Install: pip install psutil")

        lines = ["📊 STATUS SISTEM", ""]
        alerts = []

        if "cpu_percent" in s:
            lines.append(f"CPU : {s['cpu_percent']:.0f}%")
            if s["cpu_percent"] >= self.CPU_WARN:
                alerts.append(f"CPU tinggi ({s['cpu_percent']:.0f}%)")
        if "ram_percent" in s:
            lines.append(
                f"RAM : {s['ram_percent']:.0f}% "
                f"({s.get('ram_used_gb', '?')} / {s.get('ram_total_gb', '?')} GB)"
            )
            if s["ram_percent"] >= self.RAM_WARN:
                alerts.append(f"RAM tinggi ({s['ram_percent']:.0f}%)")
        if "disk_percent" in s:
            lines.append(
                f"Disk {s.get('disk_path', '')}: {s['disk_percent']:.0f}% "
                f"(bebas {s.get('disk_free_gb', '?')} / {s.get('disk_total_gb', '?')} GB)"
            )
            if s["disk_percent"] >= self.DISK_WARN:
                alerts.append(f"Disk hampir penuh ({s['disk_percent']:.0f}%)")

        if alerts:
            lines.append("")
            lines.append("⚠️ " + " · ".join(alerts))
        else:
            lines.append("")
            lines.append("Tidak ada peringatan.")

        return SkillResult(True, "\n".join(lines), s)
