"""🎤 Voice Cascade System

Based on Agent Friday's voice pipeline.
Automatically falls back: Cloud → Local → Text

Pathway priority:
0. Cloud (Gemini Live) - best quality
1. Local (Whisper + local TTS) - fully offline
2. Text-only - last resort
"""

import os
import asyncio
import logging
from typing import Optional, Dict, Callable
from dataclasses import dataclass
from enum import Enum
from dotenv import load_dotenv

load_dotenv(".env")

logger = logging.getLogger(__name__)


class VoicePathway(Enum):
    """Voice pathway options."""

    CLOUD = "cloud"  # Gemini Live
    LOCAL = "local"  # Whisper + local TTS
    TEXT_ONLY = "text"  # No voice, text only


@dataclass
class VoiceConfig:
    """Configuration for voice system."""

    prefer_cloud: bool = True
    prefer_local: bool = True
    allow_text_fallback: bool = True


class VoiceCascade:
    """Voice pipeline with automatic fallback cascade."""

    def __init__(self):
        self.current_pathway: VoicePathway = VoicePathway.TEXT_ONLY
        self.config = VoiceConfig()
        self._initialized = False

        # Check what's available
        self.cloud_available = bool(
            os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        )
        self.local_stt_available = self._check_local_stt()
        self.local_tts_available = self._check_local_tts()

        self._determine_initial_pathway()

    def _check_local_stt(self) -> bool:
        """Check if local STT (Whisper) is available."""
        try:
            import speech_recognition

            return True
        except:
            return False

    def _check_local_tts(self) -> bool:
        """Check if local TTS is available."""
        # Check for pyttsx3 or say command
        try:
            import pyttsx3

            return True
        except:
            pass

        # macOS has 'say' built-in
        return True  # say command always available

    def _determine_initial_pathway(self):
        """Determine best available pathway."""
        if self.config.prefer_cloud and self.cloud_available:
            self.current_pathway = VoicePathway.CLOUD
            logger.info("🎤 Voice: Using Cloud pathway (Gemini Live)")
        elif self.config.prefer_local and (
            self.local_stt_available or self.local_tts_available
        ):
            self.current_pathway = VoicePathway.LOCAL
            logger.info("🎤 Voice: Using Local pathway (Whisper + TTS)")
        else:
            self.current_pathway = VoicePathway.TEXT_ONLY
            logger.info("🎤 Voice: Using Text-only mode")

    def get_available_pathway(self) -> VoicePathway:
        """Get the best available pathway right now."""
        if self.current_pathway == VoicePathway.CLOUD and self.cloud_available:
            return VoicePathway.CLOUD
        if self.current_pathway == VoicePathway.LOCAL and (
            self.local_stt_available or self.local_tts_available
        ):
            return VoicePathway.LOCAL
        return VoicePathway.TEXT_ONLY

    async def listen(self, timeout: int = 5) -> tuple[str, VoicePathway]:
        """Listen to microphone and return transcribed text.

        Returns: (transcribed_text, pathway_used)
        """
        # Try current pathway first
        pathway = self.get_available_pathway()

        if pathway == VoicePathway.CLOUD:
            try:
                text = await self._cloud_listen(timeout)
                if text:
                    return text, VoicePathway.CLOUD
            except Exception as e:
                logger.warning(f"Cloud listen failed: {e}")

        # Fall back to local
        if pathway == VoicePathway.LOCAL or pathway == VoicePathway.TEXT_ONLY:
            try:
                text = await self._local_listen(timeout)
                if text:
                    return text, VoicePathway.LOCAL
            except Exception as e:
                logger.warning(f"Local listen failed: {e}")

        return "", VoicePathway.TEXT_ONLY

    async def _cloud_listen(self, timeout: int) -> str:
        """Listen using cloud (would use Gemini Live)."""
        # For now, return empty - would need full Gemini Live integration
        # This is where Agent Friday uses Gemini Live WebSocket
        raise Exception("Cloud listening not fully implemented")

    async def _local_listen(self, timeout: int) -> str:
        """Listen using local Whisper/STT."""
        try:
            from tools.voice_input import get_voice_input

            return await get_voice_input().listen(timeout=timeout, phrase_time_limit=max(5, timeout * 2))
        except Exception as e:
            logger.warning(f"Local STT failed: {e}")
            return ""

    async def speak(self, text: str) -> VoicePathway:
        """Speak text using best available TTS.

        Returns: pathway_used
        """
        pathway = self.get_available_pathway()

        if pathway == VoicePathway.CLOUD:
            try:
                await self._cloud_speak(text)
                return VoicePathway.CLOUD
            except Exception as e:
                logger.warning(f"Cloud TTS failed: {e}")

        # Fall back to local
        if pathway == VoicePathway.LOCAL or pathway == VoicePathway.TEXT_ONLY:
            try:
                await self._local_speak(text)
                return VoicePathway.LOCAL
            except Exception as e:
                logger.warning(f"Local TTS failed: {e}")

        logger.info("No TTS available, skipping voice output")
        return VoicePathway.TEXT_ONLY

    async def _cloud_speak(self, text: str):
        """Speak using cloud TTS (would use ElevenLabs or Gemini)."""
        # Would use ElevenLabs or Gemini TTS here
        raise Exception("Cloud TTS not fully implemented")

    async def _local_speak(self, text: str):
        """Speak using local TTS (say command on macOS)."""
        import subprocess

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, lambda: subprocess.run(["say", text], capture_output=True)
        )

    async def full_conversation(self, user_input: str = None) -> tuple[str, str]:
        """Full conversation cycle: listen → think → speak.

        Returns: (user_text, jarvis_response)
        """
        # 1. Listen (if no input provided)
        if user_input is None:
            user_text, pathway = await self.listen()
            if not user_text:
                return "", "I didn't catch that. Could you please repeat?"
        else:
            user_text = user_input
            pathway = self.get_available_pathway()

        # 2. Think (would call LLM)
        # For now, return a placeholder
        jarvis_response = f"You said: {user_text}"

        # 3. Speak
        await self.speak(jarvis_response)

        return user_text, jarvis_response

    def get_status(self) -> Dict:
        """Get voice system status."""
        try:
            from tools.voice_input import get_voice_input

            voice_runtime = get_voice_input().get_status()
        except Exception:
            voice_runtime = {
                "active": False,
                "session_id": None,
                "open_sessions": 0,
                "listening_sessions": 0,
                "total_sessions": 0,
            }

        return {
            "active": True,
            "current_pathway": self.current_pathway.value,
            "cloud_available": self.cloud_available,
            "local_stt_available": self.local_stt_available,
            "local_tts_available": self.local_tts_available,
            "voice_runtime": voice_runtime,
            "config": {
                "prefer_cloud": self.config.prefer_cloud,
                "prefer_local": self.config.prefer_local,
                "allow_text_fallback": self.config.allow_text_fallback,
            },
        }


# Singleton
_voice_cascade = None


def get_voice_cascade() -> VoiceCascade:
    global _voice_cascade
    if _voice_cascade is None:
        _voice_cascade = VoiceCascade()
    return _voice_cascade


# Test
if __name__ == "__main__":
    import asyncio

    async def test():
        vc = get_voice_cascade()

        print("🎤 Voice Cascade Status:")
        status = vc.get_status()
        print(f"  Current pathway: {status['current_pathway']}")
        print(f"  Cloud available: {status['cloud_available']}")
        print(f"  Local STT: {status['local_stt_available']}")
        print(f"  Local TTS: {status['local_tts_available']}")

        print("\n🧪 Testing speak (local):")
        await vc.speak("Hello! This is JARVIS using local voice.")

        print("\n✅ Voice cascade ready!")

    asyncio.run(test())
