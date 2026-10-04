"""Emulator controllers for different platforms."""

from enum import StrEnum
from typing import TYPE_CHECKING

from pyclashbot.utils.platform import is_windows

if TYPE_CHECKING:
    from pyclashbot.emulators.base import BaseEmulatorController


class EmulatorType(StrEnum):
    """Available emulator types with display names."""

    MEMU = "MEmu"
    GOOGLE_PLAY = "Google Play Games"
    BLUESTACKS = "BlueStacks 5"
    ADB = "ADB Device"


def get_emulator_registry() -> dict[EmulatorType, type["BaseEmulatorController"]]:
    """Return mapping of emulator types to controller classes.

    Only imports modules that are supported on the current platform.
    """
    registry: dict[EmulatorType, type[BaseEmulatorController]] = {}

    # Always available - pure ADB, no platform-specific deps
    from pyclashbot.emulators.adb import AdbController  # noqa: PLC0415 - Backend registry uses lazy imports.

    registry[EmulatorType.ADB] = AdbController

    # BlueStacks - supports both Windows and macOS
    from pyclashbot.emulators.bluestacks import BlueStacksEmulatorController  # noqa: PLC0415

    registry[EmulatorType.BLUESTACKS] = BlueStacksEmulatorController

    # Windows-only emulators
    if is_windows():
        from pyclashbot.emulators.google_play import GooglePlayEmulatorController  # noqa: PLC0415 - Windows-only.
        from pyclashbot.emulators.memu import MemuEmulatorController  # noqa: PLC0415 - Windows-only.

        registry[EmulatorType.GOOGLE_PLAY] = GooglePlayEmulatorController
        registry[EmulatorType.MEMU] = MemuEmulatorController

    return registry


def get_available_emulators() -> list[EmulatorType]:
    """Return list of emulator types supported on current platform."""
    return [emu_type for emu_type, cls in get_emulator_registry().items() if cls.is_supported_on_current_platform()]
