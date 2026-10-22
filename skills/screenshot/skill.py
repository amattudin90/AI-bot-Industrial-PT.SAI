"""Screenshot skill — capture screen to a temp PNG (Windows/macOS/Linux via mss or PIL)."""
from __future__ import annotations

import logging
import os
import tempfile
import time
from typing import Any, Dict, Optional

from core.skill_manager import SkillResult

logger = logging.getLogger(__name__)


def _capture(path: str) -> tuple[bool, str]:
    # 1) mss (fast, multi-monitor aware)
    try:
        import mss  # type: ignore
        import mss.tools  # type: ignore

        with mss.mss() as sct:
            # monitor 1 = primary
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            shot = sct.grab(mon)
            mss.tools.to_png(shot.rgb, shot.size, output=path)
        return True, path
    except Exception as e:
        logger.debug("mss capture failed: %s", e)

    # 2) Pillow ImageGrab (Windows/macOS)
    try:
        from PIL import ImageGrab  # type: ignore

        img = ImageGrab.grab()
        img.save(path, "PNG")
        return True, path
    except Exception as e:
        logger.debug("PIL capture failed: %s", e)

    # 3) Windows PowerShell + .NET (last resort)
    import sys

    if sys.platform == "win32":
        try:
            import subprocess

            ps = (
                "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
                "$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
                "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
                "$g = [System.Drawing.Graphics]::FromImage($bmp); "
                "$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size); "
                f"$bmp.Save('{path.replace(chr(39), '')}'); "
                "$g.Dispose(); $bmp.Dispose()"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode == 0 and os.path.isfile(path):
                return True, path
            return False, (r.stderr or r.stdout or "PowerShell screenshot gagal")[:200]
        except Exception as e:
            return False, str(e)

    return False, "Tidak ada backend screenshot (install: pip install mss  atau  pillow)."


class ScreenshotSkill:
    name = "screenshot"
    description = (
        "Ambil screenshot layar dan kirim ke Telegram. "
        "Perintah: /screenshot  atau teks 'screenshot' / 'ss layar'."
    )
    enabled_by_default = False

    async def handle(
        self,
        action: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> SkillResult:
        action = (action or "").strip().lower()
        if action not in ("capture", "take", "shot"):
            return SkillResult(False, "Aksi tidak dikenal. Gunakan: capture")

        ts = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(tempfile.gettempdir(), f"factory_ai_ss_{ts}.png")
        ok, info = _capture(path)
        if not ok:
            return SkillResult(False, f"Gagal ambil screenshot: {info}")
        if not os.path.isfile(path) or os.path.getsize(path) < 100:
            return SkillResult(False, "File screenshot kosong atau tidak dibuat.")

        return SkillResult(
            True,
            f"Screenshot tersimpan ({os.path.getsize(path) // 1024} KB).",
            {"path": path},
        )
