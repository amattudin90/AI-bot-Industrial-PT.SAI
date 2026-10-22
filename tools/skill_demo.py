"""Safe local demo of skill registration; no Telegram or system action is run."""
import asyncio
import tempfile
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.skill_manager import SkillManager
from skills.battery_monitor import BatteryMonitorSkill
from skills.laptop_control import LaptopControlSkill


async def main() -> None:
    # Isolate persisted flags so a demo never changes the real bot's skill state.
    with tempfile.TemporaryDirectory(prefix="factory_ai_skill_demo_") as temp_dir:
        manager = SkillManager(state_path=Path(temp_dir) / "skills_state.json")
        manager.register(BatteryMonitorSkill())
        manager.register(LaptopControlSkill())
        manager.enable("battery_monitor")
        manager.enable("laptop_control")

        print("Registered skills:")
        for item in manager.describe():
            print(f"- {item['name']}: enabled={item['enabled']} | {item['description']}")

        for percent in (8, 50, 99):
            result = await manager.dispatch(
                "battery_monitor", "check_threshold", {"percent": percent}
            )
            print(f"Battery {percent}% -> {result.message}")

        # No system lock is performed because confirmation is deliberately false.
        result = await manager.dispatch("laptop_control", "lock", {"confirm": False})
        print(f"Safe lock test -> {result.message}")


if __name__ == "__main__":
    asyncio.run(main())
