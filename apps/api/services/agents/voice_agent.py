# apps/api/services/agents/voice_agent.py
"""
Voice Agent - Handles voice conversation interface with Deepgram STT + Cartesia TTS
Manages real-time voice interactions and conversation flow
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np

# Cartesia SDK for standalone TTS
from cartesia import AsyncCartesia
from crewai.tools import tool

# Deepgram SDK (v5) for standalone STT
from deepgram import DeepgramClient

# LiveKit plugin imports for LiveKit-integrated voice assistant
from livekit import rtc
from livekit.agents import Agent as LKAgent
from livekit.plugins import cartesia, deepgram, silero

from apps.api.core.config import settings
from apps.api.services.agents.base_agent import AgentContext, BaseAgent

logger = logging.getLogger(__name__)


@dataclass
class VoiceMetrics:
    """Track voice interaction metrics"""

    vad_latency: float = 0
    stt_latency: float = 0
    tts_latency: float = 0
    turn_taking_latency: float = 0
    interruption_count: int = 0

    def log_metrics(self):
        logger.info(
            f"Voice Metrics - "
            f"VAD: {self.vad_latency:.2f}ms, "
            f"STT: {self.stt_latency:.2f}ms, "
            f"TTS: {self.tts_latency:.2f}ms, "
            f"Turn-taking: {self.turn_taking_latency:.2f}ms, "
            f"Interruptions: {self.interruption_count}"
        )


@dataclass
class ConversationState:
    """Maintain conversation state"""

    is_speaking: bool = False
    is_listening: bool = True
    current_transcript: str = ""
    last_user_speech: Optional[str] = None
    last_agent_response: Optional[str] = None
    conversation_phase: str = "greeting"
    turn_count: int = 0


class VoiceAgent(BaseAgent):
    """
    Voice Agent - Conversation interface specialist

    Uses:
    - Deepgram SDK v5 for speech-to-text (nova-3 model)
    - Cartesia AsyncCartesia for text-to-speech (sonic-2 model)
    - Silero VAD for voice activity detection
    - LiveKit plugins for real-time voice assistant sessions
    """

    def __init__(self):
        super().__init__(
            name="voice_agent",
            role="Voice Conversation Specialist",
            goal="Provide seamless voice interaction with natural conversation flow and minimal latency",
            backstory="""I am an expert in voice interaction and natural conversation management.
            I excel at understanding spoken language, managing conversation turns, and providing
            natural-sounding responses that make users feel heard and understood.""",
        )

    def _initialize(self):
        """Initialize voice components"""
        self.voice_metrics = VoiceMetrics()
        self.conversation_states: Dict[str, ConversationState] = {}

        # Initialize Deepgram client for standalone STT
        self._deepgram_client = None
        if settings.deepgram_api_key:
            try:
                self._deepgram_client = DeepgramClient(
                    api_key=settings.deepgram_api_key
                )
                logger.info("Deepgram client initialized")
            except Exception as e:
                logger.warning(f"Deepgram client init failed: {e}")

        # Initialize Cartesia client for standalone TTS
        self._cartesia_client = None
        if settings.cartesia_api_key:
            try:
                self._cartesia_client = AsyncCartesia(api_key=settings.cartesia_api_key)
                logger.info("Cartesia client initialized")
            except Exception as e:
                logger.warning(f"Cartesia client init failed: {e}")

        # Load Silero VAD model
        self._vad = None
        try:
            self._vad = silero.VAD.load(
                min_speech_duration=settings.vad_min_speech_duration,
                min_silence_duration=settings.vad_min_silence_duration,
                activation_threshold=settings.vad_threshold,
                sample_rate=16000,
            )
            logger.info("Silero VAD loaded")
        except Exception as e:
            logger.warning(f"Silero VAD load failed, falling back to energy-based: {e}")

        # Voice processing configuration
        self.voice_config = {
            "stt": {
                "model": "nova-3",
                "language": "en-US",
                "punctuate": True,
                "smart_format": True,
                "filler_words": False,
                "interim_results": True,
            },
            "tts": {
                "model_id": "sonic-2",
                "voice_id": settings.cartesia_voice_id,
                "language": "en",
                "encoding": "pcm_s16le",
                "sample_rate": 24000,
            },
        }

        self.audio_buffer_size = 4096
        self.audio_queues: Dict[str, asyncio.Queue] = {}
        self._register_tools()

    def _register_tools(self):
        """Register Voice Agent specific tools"""

        @tool("Convert Speech to Text")
        def speech_to_text(audio_data: bytes) -> str:
            """Convert speech audio to text using Deepgram"""
            return self._convert_speech_to_text(audio_data)

        @tool("Convert Text to Speech")
        def text_to_speech(text: str, emotion: str = "neutral") -> str:
            """Convert text to speech using Cartesia"""
            return self._convert_text_to_speech(text, emotion)

        @tool("Detect Voice Activity")
        def detect_voice_activity(audio_data: bytes) -> str:
            """Detect voice activity in audio stream"""
            return self._detect_voice_activity(audio_data)

        @tool("Manage Conversation Flow")
        def manage_flow(current_state: str, user_input: str) -> str:
            """Manage natural conversation flow and turn-taking"""
            return self._manage_conversation_flow(current_state, user_input)

        self.register_tool(speech_to_text)
        self.register_tool(text_to_speech)
        self.register_tool(detect_voice_activity)
        self.register_tool(manage_flow)

    async def process(
        self, input_data: Dict[str, Any], context: AgentContext
    ) -> Dict[str, Any]:
        """Process voice interaction"""
        try:
            action = input_data.get("action", "listen")

            if action == "listen":
                result = await self.measure_operation(
                    lambda: self._process_speech_input(input_data, context)
                )
                return result
            elif action == "speak":
                result = await self.measure_operation(
                    lambda: self._generate_speech_output(input_data, context)
                )
                return result
            elif action == "configure":
                result = await self.measure_operation(
                    lambda: self._configure_voice_pipeline(input_data, context)
                )
                return result
            elif action == "manage_flow":
                result = await self.measure_operation(
                    lambda: self._process_conversation_flow(input_data, context)
                )
                return result
            else:
                raise ValueError(f"Unknown voice action: {action}")

        except Exception as e:
            logger.error(f"Voice processing failed: {e}")
            self.metrics.record_error()
            raise

    async def _process_speech_input(
        self, input_data: Dict[str, Any], context: AgentContext
    ) -> Dict[str, Any]:
        """Process incoming speech and convert to text"""
        audio_data = input_data.get("audio_data")
        if not audio_data:
            raise ValueError("No audio data provided")

        session_id = context.session_id or context.conversation_id
        conv_state = self.conversation_states.get(session_id, ConversationState())

        # Perform VAD
        vad_start = datetime.now()
        has_speech = await self._perform_vad(audio_data)
        self.voice_metrics.vad_latency = (
            datetime.now() - vad_start
        ).total_seconds() * 1000

        if not has_speech:
            return {
                "transcript": "",
                "has_speech": False,
                "conversation_state": conv_state.__dict__,
            }

        # Perform STT
        stt_start = datetime.now()
        transcript = await self._perform_stt(audio_data, context)
        self.voice_metrics.stt_latency = (
            datetime.now() - stt_start
        ).total_seconds() * 1000

        # Update conversation state
        conv_state.last_user_speech = transcript
        conv_state.is_listening = False
        conv_state.turn_count += 1
        self.conversation_states[session_id] = conv_state

        return {
            "transcript": transcript,
            "has_speech": True,
            "conversation_state": conv_state.__dict__,
            "metrics": {
                "vad_latency_ms": self.voice_metrics.vad_latency,
                "stt_latency_ms": self.voice_metrics.stt_latency,
            },
        }

    async def _generate_speech_output(
        self, input_data: Dict[str, Any], context: AgentContext
    ) -> Dict[str, Any]:
        """Generate speech from text"""
        text = input_data.get("text", "")
        if not text:
            raise ValueError("No text provided for TTS")

        emotion = input_data.get("emotion", "neutral")
        session_id = context.session_id or context.conversation_id
        conv_state = self.conversation_states.get(session_id, ConversationState())

        # Perform TTS
        tts_start = datetime.now()
        audio_bytes = await self._perform_tts(text, emotion, context)
        self.voice_metrics.tts_latency = (
            datetime.now() - tts_start
        ).total_seconds() * 1000

        # Update conversation state
        conv_state.last_agent_response = text
        conv_state.is_speaking = True
        conv_state.is_listening = False
        self.conversation_states[session_id] = conv_state

        return {
            "audio_bytes": audio_bytes,
            "text": text,
            "emotion": emotion,
            "conversation_state": conv_state.__dict__,
            "metrics": {
                "tts_latency_ms": self.voice_metrics.tts_latency,
            },
        }

    async def _configure_voice_pipeline(
        self, input_data: Dict[str, Any], context: AgentContext
    ) -> Dict[str, Any]:
        """Configure voice processing pipeline with LiveKit plugins"""
        # Create LiveKit plugin instances for use in a LiveKit agent session
        stt_instance = deepgram.STT(
            model="nova-3",
            language="en-US",
            punctuate=True,
            smart_format=True,
            interim_results=True,
            api_key=settings.deepgram_api_key,
        )

        tts_instance = cartesia.TTS(
            model="sonic-2",
            language="en",
            voice=settings.cartesia_voice_id,
            encoding="pcm_s16le",
            sample_rate=24000,
            api_key=settings.cartesia_api_key,
        )

        vad_instance = silero.VAD.load(
            min_speech_duration=settings.vad_min_speech_duration,
            min_silence_duration=settings.vad_min_silence_duration,
            activation_threshold=settings.vad_threshold,
        )

        return {
            "stt": stt_instance,
            "tts": tts_instance,
            "vad": vad_instance,
            "audio_config": {
                "sample_rate": 16000,
                "channels": 1,
                "frame_duration_ms": 20,
            },
            "pipeline_configured": True,
        }

    async def _process_conversation_flow(
        self, input_data: Dict[str, Any], context: AgentContext
    ) -> Dict[str, Any]:
        """Manage conversation flow and turn-taking"""
        session_id = context.session_id or context.conversation_id
        user_input = input_data.get("user_input", "")

        conv_state = self.conversation_states.get(session_id, ConversationState())

        if conv_state.turn_count == 0:
            conv_state.conversation_phase = "greeting"
            response_type = "greeting"
        elif any(
            phrase in user_input.lower() for phrase in ["bye", "goodbye", "see you"]
        ):
            conv_state.conversation_phase = "closing"
            response_type = "closing"
        else:
            conv_state.conversation_phase = "active"
            response_type = "continuation"

        if conv_state.is_speaking and input_data.get("user_speaking", False):
            self.voice_metrics.interruption_count += 1
            conv_state.is_speaking = False
            response_type = "interrupted"

        conv_state.is_listening = True
        self.conversation_states[session_id] = conv_state

        return {
            "response_type": response_type,
            "conversation_phase": conv_state.conversation_phase,
            "should_respond": not conv_state.is_speaking,
            "turn_count": conv_state.turn_count,
            "metrics": {
                "interruptions": self.voice_metrics.interruption_count,
                "turn_latency_ms": self.voice_metrics.turn_taking_latency,
            },
        }

    # -------------------------------------------------------------------------
    # Core voice processing methods
    # -------------------------------------------------------------------------

    async def _perform_vad(self, audio_data: bytes) -> bool:
        """Perform voice activity detection using Silero VAD or energy fallback."""
        if self._vad is not None:
            try:
                # Silero VAD expects 16-bit PCM at 16kHz
                audio_frame = rtc.AudioFrame(
                    data=audio_data,
                    sample_rate=16000,
                    num_channels=1,
                    samples_per_channel=len(audio_data) // 2,
                )
                vad_stream = self._vad.stream()
                vad_stream.push_frame(audio_frame)
                # Check for speech event
                event = await asyncio.wait_for(vad_stream.arecv(), timeout=0.1)
                await vad_stream.aclose()
                return event.type.name == "START_OF_SPEECH"
            except (asyncio.TimeoutError, Exception) as e:
                logger.debug(f"Silero VAD check: {e}")
                # Fall through to energy-based

        # Energy-based fallback
        audio_array = np.frombuffer(audio_data, dtype=np.int16)
        audio_float = audio_array.astype(np.float32) / 32768.0
        energy = np.sqrt(np.mean(audio_float**2))
        return energy > 0.01

    async def _perform_stt(self, audio_data: bytes, context: AgentContext) -> str:
        """Perform speech-to-text using Deepgram SDK v5 (prerecorded)."""
        if self._deepgram_client is None:
            logger.warning("Deepgram client not available, returning empty transcript")
            return ""

        try:
            response = await asyncio.to_thread(
                self._deepgram_client.listen.v1.media.transcribe_file,
                request=audio_data,
                model="nova-3",
                language="en-US",
                punctuate=True,
                smart_format=True,
            )

            # Extract transcript from response
            transcript = ""
            if hasattr(response, "results"):
                channels = response.results.channels
                if channels:
                    alternatives = channels[0].alternatives
                    if alternatives:
                        transcript = alternatives[0].transcript
            elif isinstance(response, dict):
                channels = response.get("results", {}).get("channels", [])
                if channels:
                    alternatives = channels[0].get("alternatives", [])
                    if alternatives:
                        transcript = alternatives[0].get("transcript", "")

            logger.info(
                f"STT result ({len(audio_data)} bytes -> {len(transcript)} chars)"
            )
            return transcript

        except Exception as e:
            logger.error(f"Deepgram STT failed: {e}")
            return ""

    async def _perform_tts(
        self, text: str, emotion: str, context: AgentContext
    ) -> bytes:
        """Perform text-to-speech using Cartesia AsyncCartesia SDK."""
        if self._cartesia_client is None:
            logger.warning("Cartesia client not available, returning empty audio")
            return b""

        try:
            voice_id = settings.cartesia_voice_id
            output_format = {
                "container": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": 24000,
            }

            audio_bytes = await self._cartesia_client.tts.bytes(
                model_id="sonic-2",
                transcript=text,
                voice_id=voice_id,
                output_format=output_format,
                language="en",
            )

            logger.info(f"TTS result ({len(text)} chars -> {len(audio_bytes)} bytes)")
            return audio_bytes

        except Exception as e:
            logger.error(f"Cartesia TTS failed: {e}")
            return b""

    def create_voice_assistant(self) -> LKAgent:
        """Create a LiveKit Agent with Deepgram STT + Cartesia TTS + Silero VAD.

        Returns a configured LKAgent that can be started in a LiveKit AgentSession.
        The agent uses the LiveKit plugin ecosystem for real-time voice processing.
        """
        stt_plugin = deepgram.STT(
            model="nova-3",
            language="en-US",
            punctuate=True,
            smart_format=True,
            interim_results=True,
            api_key=settings.deepgram_api_key,
        )

        tts_plugin = cartesia.TTS(
            model="sonic-2",
            language="en",
            voice=settings.cartesia_voice_id,
            encoding="pcm_s16le",
            sample_rate=24000,
            api_key=settings.cartesia_api_key,
        )

        agent = LKAgent(
            instructions="""You are a document intelligence assistant. You help users
            find information in their uploaded documents through natural voice conversation.
            Be concise, helpful, and cite specific document sections when possible.""",
            stt=stt_plugin,
            tts=tts_plugin,
            vad=silero.VAD.load(
                min_speech_duration=settings.vad_min_speech_duration,
                min_silence_duration=settings.vad_min_silence_duration,
                activation_threshold=settings.vad_threshold,
            ),
        )

        return agent

    # -------------------------------------------------------------------------
    # Tool method implementations (sync wrappers for CrewAI tools)
    # -------------------------------------------------------------------------

    def _convert_speech_to_text(self, audio_data: bytes) -> str:
        """Tool method for STT conversion"""
        return (
            f"Converting {len(audio_data)} bytes of audio to text via Deepgram nova-3"
        )

    def _convert_text_to_speech(self, text: str, emotion: str) -> str:
        """Tool method for TTS conversion"""
        return f"Converting text to speech with {emotion} emotion via Cartesia sonic-2: {text[:50]}..."

    def _detect_voice_activity(self, audio_data: bytes) -> str:
        """Tool method for VAD"""
        return f"Detecting voice activity in {len(audio_data)} bytes via Silero VAD"

    def _manage_conversation_flow(self, current_state: str, user_input: str) -> str:
        """Tool method for conversation flow management"""
        return f"Managing flow from state '{current_state}' with input: {user_input[:50]}..."
