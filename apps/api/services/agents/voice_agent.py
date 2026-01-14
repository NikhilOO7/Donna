# apps/api/services/agents/voice_agent.py
"""
Voice Agent - Handles voice conversation interface with Deepgram STT + Cartesia TTS
Manages real-time voice interactions and conversation flow
"""

import asyncio
import json
import logging
from typing import Dict, Any, List, Optional, Callable, AsyncIterator
from datetime import datetime
from dataclasses import dataclass, field

from crewai.tools import tool
import numpy as np

from apps.api.services.agents.base_agent import BaseAgent, AgentContext
from apps.api.core.config import settings

# LiveKit imports
from livekit import rtc, api
from livekit.agents import (
    Agent as VoiceAssistant,  # Renamed in newer livekit-agents
    stt, tts, llm,
    AutoSubscribe, JobContext
)
from livekit.plugins import deepgram, cartesia, silero

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
        """Log current voice metrics"""
        logger.info(f"Voice Metrics - "
                   f"VAD: {self.vad_latency:.2f}ms, "
                   f"STT: {self.stt_latency:.2f}ms, "
                   f"TTS: {self.tts_latency:.2f}ms, "
                   f"Turn-taking: {self.turn_taking_latency:.2f}ms, "
                   f"Interruptions: {self.interruption_count}")

@dataclass
class ConversationState:
    """Maintain conversation state"""
    is_speaking: bool = False
    is_listening: bool = True
    current_transcript: str = ""
    last_user_speech: Optional[str] = None
    last_agent_response: Optional[str] = None
    conversation_phase: str = "greeting"  # greeting, active, closing
    turn_count: int = 0

class VoiceAgent(BaseAgent):
    """
    Voice Agent - Conversation interface specialist
    
    Responsibilities:
    - Real-time speech-to-text conversion with Deepgram Nova-3
    - Natural text-to-speech with Cartesia Sonic
    - Voice activity detection and turn management
    - Audio stream management and optimization
    - Natural conversation flow control
    """
    
    def __init__(self):
        super().__init__(
            name="voice_agent",
            role="Voice Conversation Specialist",
            goal="Provide seamless voice interaction with natural conversation flow and minimal latency",
            backstory="""I am an expert in voice interaction and natural conversation management. 
            I excel at understanding spoken language, managing conversation turns, and providing 
            natural-sounding responses that make users feel heard and understood."""
        )
        
    def _initialize(self):
        """Initialize voice components"""
        self.voice_metrics = VoiceMetrics()
        self.conversation_states: Dict[str, ConversationState] = {}
        
        # Voice processing configuration
        self.voice_config = {
            # Deepgram STT settings
            "stt": {
                "model": "nova-2-meeting",
                "language": "en-US",
                "punctuate": True,
                "profanity_filter": False,
                "diarize": True,
                "smart_format": True,
                "filler_words": False,
                "utterance_end_ms": 1000,
                "interim_results": True,
                "end_pointing": True
            },
            # Cartesia TTS settings
            "tts": {
                "voice": settings.cartesia_voice_id or "sonic-english",
                "model": "sonic-turbo",
                "language": "en",
                "speed": 1.0,
                "emotion": ["neutral"],
                "encoding": "pcm_s16le",
                "sample_rate": 16000
            },
            # VAD settings
            "vad": {
                "min_speech_duration": 0.1,
                "min_silence_duration": 0.3,
                "pre_speech_pad_ms": 100,
                "post_speech_pad_ms": 100
            }
        }
        
        # Audio buffer for smooth streaming
        self.audio_buffer_size = 4096
        self.audio_queues: Dict[str, asyncio.Queue] = {}
        
        # Register tools
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
    
    async def process(self, input_data: Dict[str, Any], context: AgentContext) -> Dict[str, Any]:
        """
        Process voice interaction
        
        Input:
            - action: Voice action type (listen, speak, configure)
            - audio_data: Raw audio data for STT
            - text: Text to convert to speech
            - room: LiveKit room reference
            - participant: Target participant
            
        Output:
            - transcript: Converted text from speech
            - audio_stream: Audio stream for TTS
            - conversation_state: Current conversation state
            - metrics: Voice processing metrics
        """
        try:
            action = input_data.get("action", "listen")
            
            if action == "listen":
                # Process incoming speech
                result = await self.measure_operation(
                    lambda: self._process_speech_input(input_data, context)
                )
                return result
                
            elif action == "speak":
                # Generate speech output
                result = await self.measure_operation(
                    lambda: self._generate_speech_output(input_data, context)
                )
                return result
                
            elif action == "configure":
                # Configure voice pipeline
                result = await self.measure_operation(
                    lambda: self._configure_voice_pipeline(input_data, context)
                )
                return result
                
            elif action == "manage_flow":
                # Manage conversation flow
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
        self, 
        input_data: Dict[str, Any], 
        context: AgentContext
    ) -> Dict[str, Any]:
        """Process incoming speech and convert to text"""
        
        audio_data = input_data.get("audio_data")
        if not audio_data:
            raise ValueError("No audio data provided")
        
        session_id = context.session_id or context.conversation_id
        
        # Get or create conversation state
        conv_state = self.conversation_states.get(
            session_id, 
            ConversationState()
        )
        
        # Perform VAD
        vad_start = datetime.now()
        has_speech = await self._perform_vad(audio_data)
        self.voice_metrics.vad_latency = (datetime.now() - vad_start).total_seconds() * 1000
        
        if not has_speech:
            return {
                "transcript": "",
                "has_speech": False,
                "conversation_state": conv_state.__dict__
            }
        
        # Perform STT
        stt_start = datetime.now()
        transcript = await self._perform_stt(audio_data, context)
        self.voice_metrics.stt_latency = (datetime.now() - stt_start).total_seconds() * 1000
        
        # Update conversation state
        conv_state.last_user_speech = transcript
        conv_state.is_listening = False
        conv_state.turn_count += 1
        
        # Store updated state
        self.conversation_states[session_id] = conv_state
        
        return {
            "transcript": transcript,
            "has_speech": True,
            "conversation_state": conv_state.__dict__,
            "metrics": {
                "vad_latency_ms": self.voice_metrics.vad_latency,
                "stt_latency_ms": self.voice_metrics.stt_latency
            }
        }
    
    async def _generate_speech_output(
        self, 
        input_data: Dict[str, Any], 
        context: AgentContext
    ) -> Dict[str, Any]:
        """Generate speech from text"""
        
        text = input_data.get("text", "")
        if not text:
            raise ValueError("No text provided for TTS")
        
        emotion = input_data.get("emotion", "neutral")
        session_id = context.session_id or context.conversation_id
        
        # Get conversation state
        conv_state = self.conversation_states.get(
            session_id, 
            ConversationState()
        )
        
        # Perform TTS
        tts_start = datetime.now()
        audio_stream = await self._perform_tts(text, emotion, context)
        self.voice_metrics.tts_latency = (datetime.now() - tts_start).total_seconds() * 1000
        
        # Update conversation state
        conv_state.last_agent_response = text
        conv_state.is_speaking = True
        conv_state.is_listening = False
        
        # Store updated state
        self.conversation_states[session_id] = conv_state
        
        return {
            "audio_stream": audio_stream,
            "text": text,
            "emotion": emotion,
            "conversation_state": conv_state.__dict__,
            "metrics": {
                "tts_latency_ms": self.voice_metrics.tts_latency,
                "audio_duration_estimate_ms": len(text) * 50  # Rough estimate
            }
        }
    
    async def _configure_voice_pipeline(
        self, 
        input_data: Dict[str, Any], 
        context: AgentContext
    ) -> Dict[str, Any]:
        """Configure voice processing pipeline"""
        
        room = input_data.get("room")
        if not room:
            raise ValueError("LiveKit room required for configuration")
        
        # Create STT instance
        stt_instance = deepgram.STT(
            api_key=settings.deepgram_api_key,
            **self.voice_config["stt"]
        )
        
        # Create TTS instance
        tts_instance = cartesia.TTS(
            api_key=settings.cartesia_api_key,
            **self.voice_config["tts"]
        )
        
        # Create VAD instance
        vad_instance = silero.VAD.load(**self.voice_config["vad"])
        
        # Configure audio processing
        audio_config = {
            "sample_rate": 16000,
            "channels": 1,
            "frame_duration_ms": 20
        }
        
        return {
            "stt": stt_instance,
            "tts": tts_instance,
            "vad": vad_instance,
            "audio_config": audio_config,
            "pipeline_configured": True
        }
    
    async def _process_conversation_flow(
        self, 
        input_data: Dict[str, Any], 
        context: AgentContext
    ) -> Dict[str, Any]:
        """Manage conversation flow and turn-taking"""
        
        session_id = context.session_id or context.conversation_id
        user_input = input_data.get("user_input", "")
        
        # Get conversation state
        conv_state = self.conversation_states.get(
            session_id, 
            ConversationState()
        )
        
        # Determine conversation phase
        if conv_state.turn_count == 0:
            conv_state.conversation_phase = "greeting"
            response_type = "greeting"
        elif any(phrase in user_input.lower() for phrase in ["bye", "goodbye", "see you"]):
            conv_state.conversation_phase = "closing"
            response_type = "closing"
        else:
            conv_state.conversation_phase = "active"
            response_type = "continuation"
        
        # Check for interruptions
        if conv_state.is_speaking and input_data.get("user_speaking", False):
            self.voice_metrics.interruption_count += 1
            conv_state.is_speaking = False
            response_type = "interrupted"
        
        # Calculate turn-taking latency
        if conv_state.last_user_speech:
            turn_latency = (datetime.now() - datetime.now()).total_seconds() * 1000
            self.voice_metrics.turn_taking_latency = turn_latency
        
        # Update state
        conv_state.is_listening = True
        self.conversation_states[session_id] = conv_state
        
        return {
            "response_type": response_type,
            "conversation_phase": conv_state.conversation_phase,
            "should_respond": not conv_state.is_speaking,
            "turn_count": conv_state.turn_count,
            "metrics": {
                "interruptions": self.voice_metrics.interruption_count,
                "turn_latency_ms": self.voice_metrics.turn_taking_latency
            }
        }
    
    async def _perform_vad(self, audio_data: bytes) -> bool:
        """Perform voice activity detection"""
        # Convert audio data to numpy array
        audio_array = np.frombuffer(audio_data, dtype=np.int16)
        
        # Normalize audio
        audio_float = audio_array.astype(np.float32) / 32768.0
        
        # Simple energy-based VAD (placeholder for actual Silero VAD)
        energy = np.sqrt(np.mean(audio_float ** 2))
        
        # Threshold for voice activity
        voice_threshold = 0.01
        
        return energy > voice_threshold
    
    async def _perform_stt(self, audio_data: bytes, context: AgentContext) -> str:
        """Perform speech-to-text conversion"""
        # Placeholder for actual Deepgram API call
        # In production, this would use the Deepgram SDK
        
        # Simulate STT processing
        await asyncio.sleep(0.1)  # Simulate network latency
        
        # Return simulated transcript
        return "This is a simulated transcript from the voice input"
    
    async def _perform_tts(
        self, 
        text: str, 
        emotion: str, 
        context: AgentContext
    ) -> AsyncIterator[bytes]:
        """Perform text-to-speech conversion"""
        # Placeholder for actual Cartesia API call
        # In production, this would use the Cartesia SDK
        
        # Simulate TTS processing
        async def generate_audio():
            # Simulate streaming audio generation
            chunk_size = 1024
            total_chunks = max(1, len(text) // 10)  # Rough estimate
            
            for i in range(total_chunks):
                await asyncio.sleep(0.05)  # Simulate processing time
                
                # Generate dummy audio data
                audio_chunk = np.random.randint(
                    -1000, 1000, 
                    size=chunk_size, 
                    dtype=np.int16
                ).tobytes()
                
                yield audio_chunk
        
        return generate_audio()
    
    def create_voice_assistant(self, room: rtc.Room) -> VoiceAssistant:
        """Create a LiveKit VoiceAssistant instance"""
        # This would be called when setting up the actual voice pipeline
        # Returns a configured VoiceAssistant for LiveKit integration
        pass
    
    # Tool method implementations
    def _convert_speech_to_text(self, audio_data: bytes) -> str:
        """Tool method for STT conversion"""
        return f"Converting {len(audio_data)} bytes of audio to text"
    
    def _convert_text_to_speech(self, text: str, emotion: str) -> str:
        """Tool method for TTS conversion"""
        return f"Converting text to speech with {emotion} emotion: {text[:50]}..."
    
    def _detect_voice_activity(self, audio_data: bytes) -> str:
        """Tool method for VAD"""
        return f"Detecting voice activity in {len(audio_data)} bytes of audio"
    
    def _manage_conversation_flow(self, current_state: str, user_input: str) -> str:
        """Tool method for conversation flow management"""
        return f"Managing flow from state '{current_state}' with input: {user_input[:50]}..."