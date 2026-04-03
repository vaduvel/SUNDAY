"""Persistent voice input runtime for JARVIS."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

import speech_recognition as sr

logger = logging.getLogger(__name__)

VOICE_RUNTIME_DIR = Path(".jarvis/voice")
VOICE_SESSIONS_FILE = VOICE_RUNTIME_DIR / "sessions.json"


@dataclass
class VoiceSession:
    """Persistent voice session state."""

    session_id: str
    status: str
    started_at: str
    updated_at: str
    transcript: str = ""
    partial_transcript: str = ""
    interrupt_detected: bool = False
    cancel_requested: bool = False
    events: List[Dict[str, Any]] = field(default_factory=list)
    listen_count: int = 0
    pathway: str = "speech_recognition"
    stopped_at: Optional[str] = None
    last_error: Optional[str] = None


class VoiceInput:
    """Native speech recognition for JARVIS voice input."""

    INTERRUPT_KEYWORDS = {"stop", "cancel", "gata", "oprește", "halt", "abort"}

    def __init__(self, runtime_dir: Path = VOICE_RUNTIME_DIR):
        self.runtime_dir = Path(runtime_dir)
        self.sessions_file = self.runtime_dir / "sessions.json"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.recognizer = sr.Recognizer()
        self.is_active = True
        self.current_session_id: Optional[str] = None
        self._sessions: Dict[str, VoiceSession] = {}
        self.last_error: Optional[str] = None
        self.available_devices: List[str] = []
        self._load_sessions()
        self.microphone = None
        self._initialize_microphone()

    def _ensure_runtime_state(self) -> None:
        """Backfill runtime attributes for tests and resumed instances."""
        runtime_dir = getattr(self, "runtime_dir", VOICE_RUNTIME_DIR)
        self.runtime_dir = Path(runtime_dir)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_file = Path(
            getattr(self, "sessions_file", self.runtime_dir / "sessions.json")
        )
        self._sessions = getattr(self, "_sessions", {})
        self.current_session_id = getattr(self, "current_session_id", None)
        self.is_active = getattr(self, "is_active", False)
        self.last_error = getattr(self, "last_error", None)
        self.available_devices = list(getattr(self, "available_devices", []))
        self.microphone = getattr(self, "microphone", None)
        self.recognizer = getattr(self, "recognizer", sr.Recognizer())

    def _initialize_microphone(self) -> None:
        """Attempt to initialize the microphone and capture diagnostics."""
        self._ensure_runtime_state()
        self.available_devices = self._list_microphone_names()
        try:
            self.microphone = sr.Microphone()
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            self.is_active = True
            self.last_error = None
            logger.info("🎤 Voice input ready!")
        except Exception as exc:
            self.microphone = None
            self.is_active = False
            self.last_error = str(exc)
            logger.info("Voice input unavailable in current runtime: %s", exc)

    def refresh_hardware(self) -> Dict[str, Any]:
        """Retry microphone initialization and report current hardware state."""
        self._ensure_runtime_state()
        self._initialize_microphone()
        return self.get_status()

    def _list_microphone_names(self) -> List[str]:
        try:
            names = sr.Microphone.list_microphone_names()
            return [name for name in names if name]
        except Exception as exc:
            logger.debug("Unable to enumerate microphones: %s", exc)
            return []

    async def listen(self, timeout: int = 5, phrase_time_limit: int = 10) -> str:
        """Listen to microphone and return transcribed text."""
        self._ensure_runtime_state()
        if not self.is_active or not self.microphone:
            self._initialize_microphone()
        if not self.is_active or not self.microphone:
            return ""

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, self._recognize_speech, timeout, phrase_time_limit
            )
            return result or ""
        except Exception as exc:
            logger.error("Voice input error: %s", exc)
            return ""

    def start_voice_session(self, session_id: str | None = None) -> Dict[str, Any]:
        """Start or resume a persistent voice session."""
        self._ensure_runtime_state()
        if not self.is_active or not self.microphone:
            self._initialize_microphone()
        session_id = session_id or f"voice_{uuid.uuid4().hex[:8]}"
        session = self._sessions.get(session_id)
        now = datetime.now().isoformat()
        if session is None:
            session = VoiceSession(
                session_id=session_id,
                status="active",
                started_at=now,
                updated_at=now,
            )
        else:
            session.status = "active"
            session.cancel_requested = False
            session.updated_at = now
            session.stopped_at = None
            session.last_error = None

        self.current_session_id = session_id
        self._sessions[session_id] = session
        self._append_event(session, "session_started", {"session_id": session_id})
        self._save_sessions()
        return self._session_payload(session)

    async def stream_listen(
        self,
        session_id: str,
        timeout: int = 5,
        phrase_time_limit: int = 10,
    ) -> Dict[str, Any]:
        """Listen and return transcript chunks plus final session state."""
        self._ensure_runtime_state()
        events = []
        async for event in self.stream_listen_events(
            session_id, timeout=timeout, phrase_time_limit=phrase_time_limit
        ):
            events.append(event)

        session = self._sessions.get(session_id)
        return {
            "session_id": session_id,
            "events": events,
            "transcript": session.transcript if session else "",
            "interrupted": bool(session and session.interrupt_detected),
            "cancelled": bool(session and session.cancel_requested and session.status == "cancelled"),
            "status": session.status if session else "unknown",
        }

    async def stream_listen_events(
        self,
        session_id: str,
        timeout: int = 5,
        phrase_time_limit: int = 10,
        chunk_delay: float = 0.01,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Yield incremental transcript events for a voice session."""
        self._ensure_runtime_state()
        session = self._sessions.get(session_id)
        if session is None or session.status not in {"active", "idle"}:
            self.start_voice_session(session_id)
            session = self._sessions[session_id]

        session.status = "listening"
        session.updated_at = datetime.now().isoformat()
        session.listen_count += 1
        self._append_event(session, "listening_started", {"timeout": timeout})
        self._save_sessions()

        yield {"type": "session_started", "session_id": session_id}

        transcript = await self.listen(timeout=timeout, phrase_time_limit=phrase_time_limit)
        if session.cancel_requested:
            session.status = "cancelled"
            session.updated_at = datetime.now().isoformat()
            self._append_event(session, "cancelled", {})
            self._save_sessions()
            yield {"type": "cancelled", "session_id": session_id}
            return

        if not transcript:
            session.status = "idle"
            session.partial_transcript = ""
            session.updated_at = datetime.now().isoformat()
            self._append_event(session, "no_speech", {})
            self._save_sessions()
            yield {"type": "done", "session_id": session_id, "transcript": ""}
            return

        chunks = self._chunk_transcript(transcript)
        collected: List[str] = []
        for chunk in chunks:
            if session.cancel_requested:
                session.status = "cancelled"
                session.updated_at = datetime.now().isoformat()
                self._append_event(session, "cancelled", {})
                self._save_sessions()
                yield {"type": "cancelled", "session_id": session_id}
                return

            collected.append(chunk)
            partial = " ".join(collected).strip()
            session.partial_transcript = partial
            interrupted = self.detect_interrupt(partial)
            event = {
                "type": "transcript",
                "session_id": session_id,
                "content": chunk,
                "partial": partial,
                "interrupted": interrupted,
            }
            self._append_event(session, "transcript", event)
            self._save_sessions()
            yield event

            if interrupted:
                session.interrupt_detected = True
                session.status = "interrupted"
                session.transcript = partial
                session.updated_at = datetime.now().isoformat()
                self._append_event(session, "interrupt_detected", {"partial": partial})
                self._save_sessions()
                yield {
                    "type": "interrupt",
                    "session_id": session_id,
                    "transcript": partial,
                }
                return

            await asyncio.sleep(chunk_delay)

        session.transcript = transcript
        session.partial_transcript = transcript
        session.status = "idle"
        session.updated_at = datetime.now().isoformat()
        self._append_event(session, "transcript_complete", {"transcript": transcript})
        self._save_sessions()
        yield {"type": "done", "session_id": session_id, "transcript": transcript}

    def stop_voice_session(self, session_id: str) -> Dict[str, Any]:
        """Stop an active voice session."""
        self._ensure_runtime_state()
        session = self._sessions.get(session_id)
        if session is None:
            session = VoiceSession(
                session_id=session_id,
                status="stopped",
                started_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
            )
            self._sessions[session_id] = session

        session.status = "stopped"
        session.stopped_at = datetime.now().isoformat()
        session.updated_at = session.stopped_at
        session.cancel_requested = False
        if self.current_session_id == session_id:
            self.current_session_id = None
        self._append_event(session, "session_stopped", {})
        self._save_sessions()
        return self._session_payload(session)

    def cancel_voice_session(self, session_id: str) -> Dict[str, Any]:
        """Request cancellation for a session."""
        self._ensure_runtime_state()
        session = self._sessions.get(session_id)
        if session is None:
            session = VoiceSession(
                session_id=session_id,
                status="cancelled",
                started_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
            )
            self._sessions[session_id] = session

        session.cancel_requested = True
        session.status = "cancelling" if session.status == "listening" else "cancelled"
        session.updated_at = datetime.now().isoformat()
        self._append_event(session, "cancel_requested", {})
        self._save_sessions()
        return self._session_payload(session)

    def detect_interrupt(self, transcript: str) -> bool:
        lowered = (transcript or "").lower()
        return any(keyword in lowered for keyword in self.INTERRUPT_KEYWORDS)

    def get_status(self) -> Dict[str, Any]:
        """Get aggregate voice runtime status."""
        self._ensure_runtime_state()
        open_sessions = [
            session for session in self._sessions.values() if session.status == "active"
        ]
        listening_sessions = [
            session for session in self._sessions.values() if session.status == "listening"
        ]
        return {
            "active": self.is_active,
            "session_id": self.current_session_id,
            "open_sessions": len(open_sessions),
            "listening_sessions": len(listening_sessions),
            "total_sessions": len(self._sessions),
            "last_error": self.last_error,
            "available_devices": self.available_devices,
        }

    def get_session(self, session_id: str) -> Dict[str, Any]:
        self._ensure_runtime_state()
        session = self._sessions.get(session_id)
        return self._session_payload(session) if session else {"error": "Session not found"}

    def list_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        self._ensure_runtime_state()
        sessions = sorted(
            self._sessions.values(),
            key=lambda item: item.updated_at,
            reverse=True,
        )
        return [self._session_payload(item) for item in sessions[:limit]]

    async def transcribe_file(self, audio_path: str) -> str:
        self._ensure_runtime_state()
        if not os.path.exists(audio_path):
            return ""

        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._transcribe_file_sync, audio_path)
        except Exception as exc:
            logger.error("File transcription error: %s", exc)
            return ""

    def _recognize_speech(self, timeout: int, phrase_time_limit: int) -> str:
        try:
            with self.microphone as source:
                logger.info("🎤 Listening...")
                audio = self.recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )
            logger.info("🔄 Processing speech...")
            return self.recognizer.recognize_google(audio)
        except sr.WaitTimeoutError:
            logger.info("No speech detected within timeout")
            return ""
        except sr.UnknownValueError:
            logger.info("Speech not understood")
            return ""
        except sr.RequestError as exc:
            logger.error("Speech recognition error: %s", exc)
            return ""

    def _transcribe_file_sync(self, audio_path: str) -> str:
        try:
            with sr.AudioFile(audio_path) as source:
                audio = self.recognizer.record(source)
            return self.recognizer.recognize_google(audio)
        except Exception as exc:
            logger.error("Transcription failed: %s", exc)
            return ""

    def _chunk_transcript(self, transcript: str, size: int = 3) -> List[str]:
        words = transcript.split()
        if not words:
            return []
        return [" ".join(words[index : index + size]) for index in range(0, len(words), size)]

    def _append_event(self, session: VoiceSession, event_type: str, payload: Dict[str, Any]) -> None:
        session.events.append(
            {
                "type": event_type,
                "timestamp": datetime.now().isoformat(),
                **payload,
            }
        )
        session.events = session.events[-100:]

    def _session_payload(self, session: VoiceSession) -> Dict[str, Any]:
        payload = asdict(session)
        payload["event_count"] = len(session.events)
        return payload

    def _load_sessions(self) -> None:
        if not self.sessions_file.exists():
            return
        try:
            data = json.loads(self.sessions_file.read_text(encoding="utf-8"))
            for item in data.get("sessions", []):
                session = VoiceSession(**item)
                self._sessions[session.session_id] = session
        except Exception as exc:
            logger.warning("Failed to load voice sessions: %s", exc)

    def _save_sessions(self) -> None:
        self._ensure_runtime_state()
        payload = {
            "sessions": [asdict(session) for session in self._sessions.values()],
            "updated_at": datetime.now().isoformat(),
        }
        self.sessions_file.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


_voice_input: Optional[VoiceInput] = None


def get_voice_input() -> VoiceInput:
    global _voice_input
    if _voice_input is None:
        _voice_input = VoiceInput()
    return _voice_input


async def test():
    voice = get_voice_input()
    session = voice.start_voice_session("voice-demo")
    print(session)
    result = await voice.stream_listen("voice-demo")
    print(result)


if __name__ == "__main__":
    asyncio.run(test())
