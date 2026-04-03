import logging
from core.os_sovereign import OSSovereign

logger = logging.getLogger(__name__)

class DesktopControl:
    """Toolkit for J.A.R.V.I.S. to control the macOS Desktop."""

    def __init__(self):
        self.os = OSSovereign()

    def desktop_notify(self, message: str, title: str = "J.A.R.V.I.S."):
        """Sends a macOS notification to the desktop.
        
        Args:
            message (str): The body of the notification.
            title (str): The title of the notification.
        """
        self.os.notify(message, title)
        return f"✅ Notification sent: {title} - {message}"

    def desktop_open_finder(self, path: str = "."):
        """Opens a Finder window at the specified path.
        
        Args:
            path (str): The directory or file path to reveal in Finder.
        """
        self.os.finder_reveal(path)
        return f"✅ Finder opened at: {path}"

    def desktop_set_volume(self, level: int):
        """Adjusts the system volume (0-100).
        
        Args:
            level (int): Target volume level.
        """
        self.os.set_volume(level)
        return f"✅ Volume set to {level}%"

    def desktop_launch_app(self, app_name: str):
        """Launches a specific application on the Mac.
        
        Args:
            app_name (str): The name of the app (e.g., 'Safari', 'Spotify', 'Slack').
        """
        self.os.launch_app(app_name)
        return f"✅ Launching {app_name}..."

    async def desktop_voice_say(self, text: str):
        """Uses the system voice to speak a message.
        
        Args:
            text (str): The text JARVIS should say aloud.
        """
        await self.os.say(text)
        return f"✅ JARVIS said: '{text}'"

if __name__ == "__main__":
    tools = DesktopControl()
    print(tools.desktop_notify("Toolkit Test", "JARVIS HUB"))
