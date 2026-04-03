"""🔊 JARVIS Realtime Voice - Gemini Live API (GRATIS!)

Realtime bidirectional voice using Gemini 2.0 Flash + AgentScope.
Cost: FREE (experimental model)
"""

import os
import asyncio
import logging
from typing import Optional
from core.runtime_config import load_project_env

load_project_env()

logger = logging.getLogger(__name__)


class RealtimeVoice:
    """Realtime voice using Gemini 2.0 Flash (FREE!)."""

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.is_active = bool(self.api_key)
        self.agent = None
        self._initialized = False

        if not self.is_active:
            logger.warning("⚠️ No GEMINI_API_KEY found. Realtime voice disabled.")

    async def initialize(self):
        """Initialize the realtime agent."""
        if not self.is_active or self._initialized:
            return

        try:
            from agentscope.realtime import GeminiRealtimeModel
            from agentscope.agent import RealtimeAgent

            # Gemini 2.0 Flash experimental - FREE!
            model = GeminiRealtimeModel(
                model_name="gemini-2.0-flash-exp",
                api_key=self.api_key,
                voice="Puck",  # Options: Puck, Charon, Kore, Fenrir, Aoede
            )

            self.agent = RealtimeAgent(
                name="JARVIS",
                sys_prompt="""You are JARVIS, a helpful AI assistant. 
Keep responses concise and natural. You can use voice.""",
                model=model,
            )

            self._initialized = True
            logger.info("✅ Realtime voice initialized with Gemini (FREE)!")
        except Exception as e:
            logger.error(f"Failed to init realtime: {e}")
            self.is_active = False

    async def speak(self, text: str):
        """Speak text using realtime model."""
        if not self._initialized:
            await self.initialize()

        if self.agent:
            # For now, we'll use this as the speaking mechanism
            logger.info(f"🎤 Would speak: {text[:50]}...")
        else:
            # ElevenLabs is intentionally paused for now. If we want it back,
            # restore this block and place it ahead of the local cascade:
            #
            # try:
            #     from tools.audio_cloud import ElevenLabsTTS
            #
            #     tts = ElevenLabsTTS()
            #     if await tts.speak(text):
            #         return {"success": True, "mode": "elevenlabs"}
            # except Exception as exc:
            #     logger.warning("ElevenLabs fallback failed: %s", exc)

            from tools.voice_cascade import get_voice_cascade

            pathway = await get_voice_cascade().speak(text)
            return {"success": True, "mode": pathway.value}

        return {"success": True, "mode": "realtime"}

    def get_status(self) -> dict:
        """Get realtime voice backend status."""
        return {
            "active": self.is_active,
            "initialized": self._initialized,
            "provider": "agentscope_gemini_live" if self.is_active else "fallback_only",
            "has_agent": self.agent is not None,
        }


async def test():
    print("🎤 Testing Realtime Voice with Gemini...")

    voice = RealtimeVoice()
    print(f"Active: {voice.is_active}")

    if voice.is_active:
        await voice.initialize()
        print("✅ Realtime voice ready!")
    else:
        print("❌ Need GEMINI_API_KEY")


if __name__ == "__main__":
    asyncio.run(test())
