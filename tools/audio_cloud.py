import os
import httpx
import logging
import subprocess
from typing import Optional
from dotenv import load_dotenv

# Load again to be sure
load_dotenv()

logger = logging.getLogger(__name__)

class ElevenLabsTTS:
    """The Diamond Grade TTS Engine (Grok-style via ElevenLabs)."""
    
    def __init__(self):
        self.api_key = os.getenv("ELEVENLABS_API_KEY")
        self.voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
        self.model_id = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
        self.url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
        
        # Status check
        if not self.api_key:
            logger.warning("ElevenLabs API Key not found. Cloud TTS disabled.")
            self.is_active = False
        else:
            self.is_active = True

    async def speak(self, text: str) -> bool:
        """Generate audio from text and play it immediately."""
        if not self.is_active:
            return False

        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": self.api_key
        }

        data = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.8
            }
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.url, json=data, headers=headers)
                if response.status_code == 200:
                    # Save temporary file in workspace
                    temp_file = os.path.join(os.getcwd(), "tmp_speech.mp3")
                    with open(temp_file, "wb") as f:
                        f.write(response.content)
                    
                    # Play using macOS native afplay asynchronously to avoid blocking FastAPI
                    # afplay is standard on macOS
                    import asyncio
                    process = await asyncio.create_subprocess_exec("afplay", temp_file)
                    await process.communicate()
                    
                    # Cleanup
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                    return True
                else:
                    logger.error(f"ElevenLabs API Error: {response.status_code} - {response.text}")
                    return False
        except Exception as e:
            logger.error(f"Failed to communicate with ElevenLabs: {e}")
            return False

if __name__ == "__main__":
    import asyncio
    # Simple test logic
    async def test():
        engine = ElevenLabsTTS()
        if engine.is_active:
            print("Testing XI-Audio...")
            await engine.speak("Hello Daniel, Diamond Audio is now online.")
        else:
            print("ElevenLabs not configured.")
    
    asyncio.run(test())
