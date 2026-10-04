import re
import subprocess
import time

from pyclashbot.bot.coords import CLAN_VOYAGE_CLOSE_BUTTON_COORDS
from pyclashbot.bot.state_detect import check_if_on_clan_voyage, check_if_on_clash_main_menu
from pyclashbot.emulators.adb_base import AdbBasedController, validate_device_serial
from pyclashbot.emulators.base import CLASH_ROYALE_PACKAGE, EmulatorNotReadyError
from pyclashbot.utils.platform import Platform

# Set to True for verbose ADB command logging
DEBUG = False


class AdbController(AdbBasedController):
    """
    Controller for a Android device/emulator using ADB.
    This class implements the BaseEmulatorController interface to interact with a
    physical/emulator Android device connected via USB or Wi-Fi.

    It now inherits shared ADB logic from AdbBasedController.
    """

    supported_platforms = [Platform.WINDOWS, Platform.MACOS, Platform.LINUX]

    def __init__(self, logger, device_serial: str | None = None):
        """
        Initializes the controller and connects to the adb device.
        Args:
            logger: The logger instance for status updates.
            device_serial (str, optional): The specific serial number of the device
                                           to connect to. If None, it will try to
                                           find a single connected device.
        """
        self.logger = logger
        self.device_serial: str | None = device_serial
        self._auto_stop_on_del = False  # No process to stop

        # For storing original screen settings
        self.original_size = None
        self.original_density = None
        self._original_screen_props = None

        self.logger.change_status("Connecting to ADB device...")

        if self.device_serial is None:
            self._discover_device()

        self.logger.log(f"Targeting device with serial: {self.device_serial}")

        # Verify connection
        if not self._is_connected():
            raise ConnectionError(
                f"Failed to connect to device {self.device_serial}. "
                "Ensure USB debugging is enabled and the device is authorized."
            )

        self.logger.log(f"Successfully connected to {self.device_serial}.")

        # Screen size/density is idempotent and a physical device has no boot phase,
        # so this stays in construction (documented exception). restart() launches Clash.
        self.handle_screen_size_and_density()

    def _read_screen_props(self):
        """Read physical defaults and optional overrides before changing the device."""
        size_result = self.adb("shell wm size")
        density_result = self.adb("shell wm density")
        size_text = size_result.stdout or ""
        density_text = density_result.stdout or ""
        physical_size = re.search(r"Physical size:\s*(\d+x\d+)", size_text)
        physical_density = re.search(r"Physical density:\s*(\d+)", density_text)
        size_override = re.search(r"Override size:\s*(\d+x\d+)", size_text)
        density_override = re.search(r"Override density:\s*(\d+)", density_text)
        if size_result.returncode or density_result.returncode or not physical_size or not physical_density:
            raise EmulatorNotReadyError("Unable to read original display settings; refusing to overwrite them")
        return {
            "physical_size": physical_size.group(1),
            "physical_density": int(physical_density.group(1)),
            "size_override": size_override.group(1) if size_override else None,
            "density_override": int(density_override.group(1)) if density_override else None,
        }

    def get_screen_props(self):
        """Return the effective dimensions/density, preferring existing overrides."""
        props = self._read_screen_props()
        return (
            props["size_override"] or props["physical_size"],
            props["density_override"] or props["physical_density"],
        )

    def handle_screen_size_and_density(self):
        """
        Checks the current screen size and density, sets them to the required values if they are not already set,
        and stores the original values for later restoration.
        """
        self.logger.log("Checking screen size and density...")
        props = self._read_screen_props()
        current_size = props["size_override"] or props["physical_size"]
        current_density = props["density_override"] or props["physical_density"]

        required_size = "419x633"
        required_density = 160

        # Snapshot exactly once: subsequent restarts must retain the user's
        # pre-bot override state rather than our own 419x633/160 overrides.
        if getattr(self, "_original_screen_props", None) is None:
            self._original_screen_props = props
            self.original_size = current_size
            self.original_density = current_density

        # Check and set size
        if current_size != required_size:
            self.logger.log(f"Current size {current_size} is not the required {required_size}. Setting it now.")
            self.set_screen_size(419, 633)
        else:
            self.logger.log("Screen size is already correct.")

        # Check and set density
        if current_density != required_density:
            self.logger.log(
                f"Current density {current_density} is not the required {required_density}. Setting it now."
            )
            self.set_screen_density(required_density)
        else:
            self.logger.log("Screen density is already correct.")

    def restore_original_screen_props(self):
        """Restore the user's overrides, or reset if there originally were none."""
        props = getattr(self, "_original_screen_props", None)
        if props is None:
            return
        failed = []
        for key, command in (("size_override", "size"), ("density_override", "density")):
            value = props[key] if props[key] is not None else "reset"
            try:
                result = self.adb(f"shell wm {command} {value}")
                if result.returncode != 0:
                    failed.append(command)
            except (OSError, subprocess.TimeoutExpired):
                failed.append(command)
        if failed:
            raise EmulatorNotReadyError(f"Failed to restore original display settings: {', '.join(failed)}")

    @staticmethod
    def connect_device(logger, device_address: str) -> bool:
        """Connects to a device via ADB over network or confirms a USB connection."""
        if not device_address:
            logger.change_status("Device address cannot be empty.")
            return False

        if not validate_device_serial(device_address):
            logger.change_status(f"Invalid device address format: {device_address}")
            return False

        # If device is already in the list (e.g., USB connected), no need to connect.
        if device_address in AdbController.discover_devices():
            logger.change_status(f"Device {device_address} is already connected.")
            return True

        command = f"adb connect {device_address}"
        try:
            process = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
                timeout=AdbController.adb_timeout,
            )
            output = process.stdout.strip()
            logger.change_status(output)
            if "connected" in output or "already connected" in output:
                return True
            logger.change_status(f"Failed to connect: {process.stderr.strip()}")
            return False
        except FileNotFoundError:
            logger.change_status("ADB command not found. Make sure ADB is installed and in your PATH.")
            return False
        except subprocess.TimeoutExpired:
            logger.change_status("ADB connection timed out.")
            return False
        except subprocess.CalledProcessError as e:
            logger.change_status(f"Error connecting to {device_address}: {e.stderr.strip()}")
            return False

    def _discover_device(self):
        """Discovers a single connected device if no serial is provided."""
        self.logger.log("No device serial provided, attempting to auto-discover...")
        devices = self.discover_devices()

        if not devices:
            raise ConnectionError("No ADB devices found. Check your connection and USB debugging settings.")

        if len(devices) > 1:
            raise ConnectionError(
                f"Multiple devices found: {devices}. Please specify the device serial during initialization."
            )

        self.device_serial = devices[0]
        self.logger.log(f"Auto-discovered device: {self.device_serial}")

    def _is_connected(self) -> bool:
        """Checks if the target device is connected and in 'device' state."""
        state = self.adb("get-state").stdout.strip()
        return state == "device"

    @staticmethod
    def restart_adb(logger):
        """Restarts the ADB server."""
        logger.change_status("Restarting ADB server...")
        try:
            # Kill the server
            kill_result = subprocess.run(
                "adb kill-server",
                shell=True,
                capture_output=True,
                text=True,
                check=False,
                timeout=AdbController.adb_timeout,
            )
            if kill_result.returncode == 0:
                logger.log("ADB server killed successfully.")
            else:
                logger.log(f"Failed to kill ADB server: {kill_result.stderr.strip()}")

            time.sleep(1)

            # Start the server
            start_result = subprocess.run(
                "adb start-server",
                shell=True,
                capture_output=True,
                text=True,
                check=False,
                timeout=AdbController.adb_timeout,
            )
            if start_result.returncode == 0:
                logger.change_status("ADB server started successfully.")
                return True
            logger.change_status(f"Failed to start ADB server: {start_result.stderr.strip()}")
            return False
        except FileNotFoundError:
            logger.change_status("ADB command not found. Make sure ADB is installed and in your PATH.")
            return False
        except subprocess.TimeoutExpired:
            logger.change_status("ADB server restart timed out.")
            return False
        except subprocess.CalledProcessError as e:
            logger.change_status(f"Error restarting ADB server: {e.stderr.strip()}")
            return False

    def set_screen_size(self, width: int, height: int):
        """Sets the screen size of the device."""
        self.logger.log(f"Setting screen size to {width}x{height}")
        result = self.adb(f"shell wm size {width}x{height}")
        if result.returncode == 0:
            self.logger.log("Screen size set successfully.")
        else:
            self.logger.log(f"Failed to set screen size: {result.stderr}")

    def set_screen_density(self, density: int):
        """Sets the screen density of the device."""
        self.logger.log(f"Setting screen density to {density}")
        result = self.adb(f"shell wm density {density}")
        if result.returncode == 0:
            self.logger.log("Screen density set successfully.")
        else:
            self.logger.log(f"Failed to set screen density: {result.stderr}")

    def reset_screen_size(self):
        """Resets the screen size of the device to its default."""
        self.logger.log("Resetting screen size.")
        result = self.adb("shell wm size reset")
        if result.returncode == 0:
            self.logger.log("Screen size reset successfully.")
        else:
            self.logger.log(f"Failed to reset screen size: {result.stderr}")

    def reset_screen_density(self):
        """Resets the screen density of the device to its default."""
        self.logger.log("Resetting screen density.")
        result = self.adb("shell wm density reset")
        if result.returncode == 0:
            self.logger.log("Screen density reset successfully.")
        else:
            self.logger.log(f"Failed to reset screen density: {result.stderr}")

    ## No-Op Methods (Not applicable to physical devices) ##

    def create(self):
        """Not applicable for a real device. Does nothing."""
        self.logger.log("Create method is not applicable for a physical device.")
        pass

    def configure(self):
        """Not applicable for a real device. Does nothing."""
        self.logger.log("Configure method is not applicable for a physical device.")
        pass

    def start(self):
        """Not applicable for a real device. Assumes the device is already on."""
        self.logger.log("Start method is not applicable for a physical device.")
        pass

    def stop(self):
        """
        Restores the original screen properties when the bot stops.
        """
        self.logger.log("Stop method called. Restoring original screen properties.")
        self.restore_original_screen_props()
        pass

    ## Implemented Methods ##

    def restart(self) -> bool:
        """
        Restarts the Clash Royale app to ensure a clean state.
        This method will:
        1. Force-stop the app.
        2. Start the app (using the base class method).
        3. Wait for the main menu to appear.
        Returns True once the main menu is reached; raises EmulatorNotReadyError
        if Clash isn't installed or the main menu never appears.
        """
        start_ts = time.time()
        self.logger.change_status("Restarting Clash Royale on device...")

        clash_pkg = CLASH_ROYALE_PACKAGE

        # 1. Force stop the app
        self.logger.change_status(f"Force-stopping {clash_pkg}...")
        self.adb(f"shell am force-stop {clash_pkg}")
        time.sleep(3)

        # 2. Start the app using the inherited method
        # start_app raises EmulatorNotReadyError if Clash Royale isn't installed.
        self.logger.change_status("Launching Clash Royale...")
        self.start_app(clash_pkg)

        time.sleep(5)  # Give the app some time to load initially

        # 3. Wait for main menu
        self.logger.change_status("Waiting for Clash Royale main menu...")
        deadline = time.time() + 240  # 4-minute timeout
        while time.time() < deadline:
            if check_if_on_clash_main_menu(self):
                self.logger.change_status("Clash Royale main menu detected.")
                dur = f"{time.time() - start_ts:.1f}s"
                self.logger.log(f"App restart completed in {dur}")
                return True

            # handle the clan voyage popup that can block the main menu at launch
            if check_if_on_clan_voyage(self):
                self.logger.change_status("Closing clan voyage page")
                self.click(*CLAN_VOYAGE_CLOSE_BUTTON_COORDS)
                time.sleep(2)
                continue

            # Click in a safe area to dismiss potential pop-ups
            self.click(35, 405)
            time.sleep(2)

        self.logger.change_status("Timeout waiting for Clash Royale main menu. Please check the device.")
        raise EmulatorNotReadyError("ADB device restart() timed out waiting for the Clash Royale main menu")
