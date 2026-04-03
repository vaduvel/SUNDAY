import subprocess
import logging
import os
from typing import Optional, List
# ElevenLabs is intentionally paused for now.
# from tools.audio_cloud import ElevenLabsTTS

logger = logging.getLogger(__name__)


class OSSovereign:
    """The macOS Automation Engine (AppleScript Bridge)."""

    def __init__(self):
        self.name = "OS Sovereign"
        # Keep the placeholder so the re-enable path is obvious later.
        # self.cloud_tts = ElevenLabsTTS()
        self.cloud_tts = None

    def execute_applescript(self, script: str) -> str:
        """Execută un script AppleScript și returnează output-ul."""
        try:
            process = subprocess.Popen(
                ["osascript", "-e", script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = process.communicate()
            if stderr:
                logger.error(f"AppleScript Error: {stderr}")
                return f"Error: {stderr}"
            return stdout.strip()
        except Exception as e:
            logger.error(f"Failed to execute AppleScript: {e}")
            return str(e)

    async def say(self, text: str, voice: str = "Daniel"):
        """Use macOS text-to-speech engine with a specific voice."""
        try:
            # ElevenLabs is intentionally commented out while Gemini Live is the
            # primary voice surface and native macOS speech remains the backup.
            #
            # if self.cloud_tts and self.cloud_tts.is_active:
            #     success = await self.cloud_tts.speak(text)
            #     if success:
            #         return True
            #     logger.warning("Cloud TTS failed, falling back to native.")

            # Native fallback only.
            subprocess.run(["say", "-v", voice, text], check=True)
            return True
        except Exception as e:
            logger.error(f"Failed to speak: {e}")
            return False

    def notify(self, message: str, title: str = "J.A.R.V.I.S."):
        """Trimite o notificare nativă macOS."""
        script = f'display notification "{message}" with title "{title}"'
        self.execute_applescript(script)

    def set_volume(self, level: int):
        """Setează volumul sistemului (0-100)."""
        level = max(0, min(100, level))
        script = f"set volume output volume {level}"
        self.execute_applescript(script)

    def get_volume(self) -> str:
        """Returnează volumul curent."""
        script = "output volume of (get volume settings)"
        return self.execute_applescript(script)

    def launch_app(self, app_name: str):
        """Lansează o aplicație pe Mac."""
        script = f'tell application "{app_name}" to activate'
        return self.execute_applescript(script)

    def finder_reveal(self, path: str):
        """Deschide Finder la o cale specifică."""
        abs_path = os.path.abspath(path)
        script = f'tell application "Finder" to open POSIX file "{abs_path}"'
        self.execute_applescript(script)
        self.execute_applescript('tell application "Finder" to activate')

    def say_system(self, text: str):
        """Folosește vocea sistemului pentru a vorbi."""
        script = f'say "{text}"'
        self.execute_applescript(script)


if __name__ == "__main__":
    os_sys = OSSovereign()
    print("Testing Notification...")
    os_sys.notify("OSSovereign Test", "NUCLEUS SUPREME")
    print("Current Volume:", os_sys.get_volume())
