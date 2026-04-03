"""🎯 JARVIS LIVE - Gemini Live API Integration
==============================================

Live video + audio conversation with JARVIS.
- Sees your screen + webcam in real-time
- Listens and responds with voice
- Latency: <1 second

Usage:
    python3 tools/jarvis_live.py

Or import in JARVIS:
    from tools.jarvis_live import JarvisLiveSession
    await JarvisLiveSession.start()
"""

import asyncio
import io
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import logging
from typing import Optional

import cv2
import mss
import numpy as np
from PIL import Image
import pyaudio

logger = logging.getLogger(__name__)

# Load env
try:
    from core.runtime_config import load_project_env

    load_project_env()
except ImportError:
    pass

# Google GenAI
try:
    from google import genai
    from google.genai import types

    GOOGLE_GENAI_AVAILABLE = True
except ImportError:
    GOOGLE_GENAI_AVAILABLE = False
    logger.warning("google-genai not installed. Run: pip install google-genai")


class JarvisLiveSession:
    """JARVIS Live Session - Bidirectional Video/Audio via Gemini Live API"""

    def __init__(self):
        if not GOOGLE_GENAI_AVAILABLE:
            raise ImportError(
                "google-genai not installed. Run: pip install google-genai"
            )

        # Get API key
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("No GEMINI_API_KEY found in .env")

        # Initialize Google Client
        self.client = genai.Client(
            api_key=self.api_key, http_options={"api_version": "v1alpha"}
        )

        # Screen capture
        self.sct = mss.mss()

        # Webcam
        self.webcam = cv2.VideoCapture(0)
        if not self.webcam.isOpened():
            logger.warning("Webcam not available")

        # Audio
        self.p = pyaudio.PyAudio()
        self.FORMAT = pyaudio.paInt16
        self.CHANNELS = 1
        self.RATE = 16000
        self.CHUNK = 1024

        # State
        self.running = False
        self.session = None
        self.audio_thread = None

    def _capture_screen(self) -> Optional[bytes]:
        """Capture screen and return JPEG bytes"""
        try:
            scr = np.array(self.sct.grab(self.sct.monitors[1]))
            scr = cv2.cvtColor(scr, cv2.COLOR_BGRA2RGB)

            # Add webcam PiP
            ret, cam = self.webcam.read()
            if ret:
                cam = cv2.cvtColor(cam, cv2.COLOR_BGR2RGB)
                cam = cv2.resize(cam, (320, 240))
                h, w = scr.shape[:2]
                scr[max(0, h - 240) : h, 0:320] = cam  # Bottom-left corner

            # Resize & encode
            img = Image.fromarray(scr)
            img.thumbnail((1024, 1024))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70)
            return buf.getvalue()
        except Exception as e:
            logger.error(f"Screen capture error: {e}")
            return None

    async def _stream_video(self, session):
        """Send video frames to Gemini (1 FPS)"""
        while self.running:
            try:
                frame_data = self._capture_screen()
                if frame_data:
                    await session.send_realtime_input(
                        video=types.Blob(data=frame_data, mime_type="image/jpeg")
                    )
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.error(f"Video stream error: {e}")
                break

    async def _stream_audio_input(self, session):
        """Send microphone audio to Gemini"""
        try:
            stream = self.p.open(
                format=self.FORMAT,
                channels=self.CHANNELS,
                rate=self.RATE,
                input=True,
                frames_per_buffer=self.CHUNK,
                start=True,
            )

            while self.running:
                try:
                    data = stream.read(self.CHUNK, exception_on_overflow=False)
                    await session.send_realtime_input(
                        audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                    )
                except Exception as e:
                    logger.error(f"Audio input error: {e}")
                    break

        except Exception as e:
            logger.error(f"Mic stream error: {e}")

    def _play_audio_output(self, audio_data: bytes):
        """Play audio data to speakers"""
        try:
            stream = self.p.open(
                format=self.FORMAT,
                channels=self.CHANNELS,
                rate=24000,  # Gemini output rate
                output=True,
                frames_per_buffer=self.CHUNK,
            )
            stream.write(audio_data)
            stream.stop_stream()
            stream.close()
        except Exception as e:
            logger.error(f"Audio playback error: {e}")

    async def _receive_responses(self, session):
        """Receive and play Gemini responses"""
        try:
            async for response in session.receive():
                if not response.server_content:
                    continue

                for part in response.server_content.model_turn.parts:
                    # Text response
                    if part.text:
                        print(f"\n💬 JARVIS: {part.text}")

                    # Audio response
                    if part.inline_data and "audio" in part.inline_data.mime_type:
                        self._play_audio_output(part.inline_data.data)

        except Exception as e:
            logger.error(f"Response receive error: {e}")

    async def start(self):
        """Start JARVIS Live session"""
        print("🎯 Starting JARVIS LIVE...")
        print("=" * 50)

        config = {
            "response_modalities": ["AUDIO", "TEXT"],
            "system_instruction": """You are JARVIS, a helpful AI assistant. 
Keep responses concise and conversational. You can see the user's screen and webcam.
You have a friendly, helpful personality.""",
        }

        try:
            async with self.client.aio.live.connect(
                model="gemini-3.1-flash-live-preview", config=config
            ) as session:
                self.session = session
                self.running = True

                print("✅ JARVIS LIVE is running!")
                print("   - You are seen via webcam")
                print("   - Your screen is shared")
                print("   - Speak to chat with JARVIS")
                print("   - Press Ctrl+C to stop")
                print("=" * 50)

                # Start video and audio streams
                await asyncio.gather(
                    self._stream_video(session),
                    self._stream_audio_input(session),
                    self._receive_responses(session),
                )

        except Exception as e:
            print(f"❌ Error: {e}")
        finally:
            self.running = False
            self._cleanup()

    def _cleanup(self):
        """Clean up resources"""
        self.running = False
        if self.webcam:
            self.webcam.release()
        if self.p:
            self.p.terminate()
        print("👋 JARVIS LIVE stopped")


async def main():
    """Standalone test"""
    try:
        jarvis = JarvisLiveSession()
        await jarvis.start()
    except KeyboardInterrupt:
        print("\n👋 Stopping JARVIS LIVE...")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
