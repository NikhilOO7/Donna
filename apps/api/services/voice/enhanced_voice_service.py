# apps/api/services/voice/enhanced_voice_service.py
"""
Production-ready Voice Service with Deepgram Nova-3 STT + Cartesia Sonic TTS + LiveKit
Optimized for ultra-low latency document intelligence conversations
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

# Provider integrations
import deepgram
import numpy as np
import openai
from cartesia import AsyncCartesia

# LiveKit imports
from livekit import agents, rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    VoiceAssistant,
    WorkerOptions,
    llm,
    stt,
    tts,
)
from silero import silero_vad

# Your app imports
from apps.api.core.config import settings
from apps.api.core.metrics import observe_voice_latency
from apps.api.services.rag.llamaindex_service import ModernRAGService

logger = logging.getLogger(__name__)


@dataclass
class ConversationContext:
    """Maintains conversation state and context"""

    messages: List[Dict[str, str]] = field(default_factory=list)
    current_documents: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)
    last_query: Optional[str] = None
    conversation_start: datetime = field(default_factory=datetime.now)

    def add_message(self, role: str, content: str):
        self.messages.append(
            {"role": role, "content": content, "timestamp": datetime.now().isoformat()}
        )

    def get_context_window(self, max_messages: int = 10) -> List[Dict[str, str]]:
        """Get recent conversation context"""
        return self.messages[-max_messages:]


@dataclass
class VoiceMetrics:
    """Track performance metrics"""

    vad_latency: float = 0
    stt_latency: float = 0
    llm_latency: float = 0
    tts_latency: float = 0
    rag_latency: float = 0
    total_latency: float = 0

    def log_metrics(self):
        """Log current metrics"""
        logger.info(
            f"Voice Pipeline Metrics - "
            f"VAD: {self.vad_latency:.2f}ms, "
            f"STT: {self.stt_latency:.2f}ms, "
            f"LLM: {self.llm_latency:.2f}ms, "
            f"TTS: {self.tts_latency:.2f}ms, "
            f"RAG: {self.rag_latency:.2f}ms, "
            f"Total: {self.total_latency:.2f}ms"
        )


class OptimizedDeepgramSTT(stt.STT):
    """Deepgram Nova-3 STT optimized for meetings and documents"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "nova-2-meeting",
        language: str = "en-US",
    ):
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=True, interim_results=True)
        )
        self.api_key = api_key or settings.deepgram_api_key
        self.model = model
        self.language = language
        self._client = None
        self._ws = None
        self._initialize_client()

    def _initialize_client(self):
        """Initialize Deepgram client"""
        self._client = deepgram.DeepgramClient(self.api_key)

    async def _ensure_connection(self):
        """Ensure WebSocket connection is active"""
        if not self._ws or self._ws.closed:
            self._ws = await self._client.transcription.live(
                {
                    "model": self.model,
                    "language": self.language,
                    "punctuate": True,
                    "profanity_filter": False,
                    "redact": False,
                    "diarize": True,
                    "multichannel": True,
                    "alternatives": 1,
                    "numerals": True,
                    "search": [
                        "document",
                        "report",
                        "meeting",
                        "action item",
                        "decision",
                    ],
                    "replace": {"zoom": "Zoom", "teams": "Teams", "slack": "Slack"},
                    "filler_words": False,
                    "smart_format": True,
                    "utterance_end_ms": 1000,
                    "vad_events": True,
                    "interim_results": True,
                    "end_of_speech_threshold": 800,
                }
            )

    async def stream(
        self, audio_stream: rtc.AudioStream, *, language: Optional[str] = None, **kwargs
    ) -> stt.SpeechStream:
        """Stream audio for real-time transcription"""

        await self._ensure_connection()

        class DeepgramSpeechStream(stt.SpeechStream):
            def __init__(self, ws, stt_instance):
                super().__init__()
                self._ws = ws
                self._stt = stt_instance
                self._closed = False
                self._start_time = time.time()

            async def aclose(self):
                if not self._closed:
                    self._closed = True
                    await self._ws.close()

            async def __anext__(self) -> stt.SpeechEvent:
                if self._closed:
                    raise StopAsyncIteration

                # Process audio frames
                async for frame in audio_stream:
                    if self._closed:
                        raise StopAsyncIteration

                    # Send audio to Deepgram
                    await self._ws.send(frame.data.tobytes())

                # Get transcription results
                result = await self._ws.recv()

                if result.type == "Results":
                    transcript = result.channel.alternatives[0].transcript
                    confidence = result.channel.alternatives[0].confidence
                    is_final = result.is_final

                    # Calculate latency
                    latency = (time.time() - self._start_time) * 1000
                    if is_final:
                        observe_voice_latency("stt", latency)

                    return stt.SpeechEvent(
                        type=stt.SpeechEventType.FINAL_TRANSCRIPT
                        if is_final
                        else stt.SpeechEventType.INTERIM_TRANSCRIPT,
                        alternatives=[
                            stt.SpeechData(
                                text=transcript,
                                confidence=confidence,
                                language=self._stt.language,
                            )
                        ],
                        metadata={
                            "latency_ms": latency,
                            "speaker_id": result.channel.alternatives[0]
                            .words[0]
                            .speaker
                            if result.channel.alternatives[0].words
                            else None,
                        },
                    )

                raise StopAsyncIteration

        return DeepgramSpeechStream(self._ws, self)


class OptimizedCartesiaTTS(tts.TTS):
    """Cartesia Sonic TTS with sub-40ms latency"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: Optional[str] = None,
        model: str = "sonic-turbo",
    ):
        super().__init__(capabilities=tts.TTSCapabilities(streaming=True))
        self.api_key = api_key or settings.cartesia_api_key
        self.voice_id = voice_id or settings.cartesia_voice_id
        self.model = model
        self._client = None
        self._initialize_client()

    def _initialize_client(self):
        """Initialize Cartesia client"""
        self._client = AsyncCartesia(api_key=self.api_key)

    async def synthesize(
        self, text: str, *, voice: Optional[str] = None, **kwargs
    ) -> tts.ChunkedStream:
        """Synthesize speech with ultra-low latency"""

        start_time = time.time()
        voice_id = voice or self.voice_id

        class CartesiaChunkedStream(tts.ChunkedStream):
            def __init__(self, client, text, voice_id, model):
                super().__init__()
                self._client = client
                self._text = text
                self._voice_id = voice_id
                self._model = model
                self._closed = False

            async def aclose(self):
                self._closed = True

            async def __anext__(self) -> tts.SynthesizedAudio:
                if self._closed:
                    raise StopAsyncIteration

                # Stream audio chunks from Cartesia
                async for chunk in self._client.tts.stream(
                    model_id=self._model,
                    transcript=self._text,
                    voice=self._voice_id,
                    output_format={
                        "container": "raw",
                        "encoding": "pcm_s16le",
                        "sample_rate": 24000,
                    },
                    stream=True,
                    speed=1.0,
                    emotion=["neutral"],
                    experimental_flags={"reduce_latency": True, "enable_ssml": True},
                ):
                    if chunk.audio:
                        # Calculate metrics — time to first audio chunk (TTS TTFB)
                        latency = (time.time() - start_time) * 1000
                        observe_voice_latency("tts", latency)

                        return tts.SynthesizedAudio(
                            text=self._text,
                            data=rtc.AudioFrame(
                                data=np.frombuffer(chunk.audio, dtype=np.int16),
                                sample_rate=24000,
                                num_channels=1,
                            ),
                            metadata={
                                "latency_ms": latency,
                                "chunk_size": len(chunk.audio),
                            },
                        )

                raise StopAsyncIteration

        return CartesiaChunkedStream(self._client, text, voice_id, self.model)


class DocumentIntelligenceLLM(llm.LLM):
    """Custom LLM that integrates with RAG for document intelligence"""

    def __init__(self, rag_service: ModernRAGService, model: str = "gpt-4-turbo"):
        super().__init__()
        self.rag_service = rag_service
        self.model = model
        self._client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

    async def chat(
        self,
        chat_ctx: llm.ChatContext,
        fnc_ctx: Optional[llm.FunctionContext] = None,
        temperature: float = 0.7,
        n: int = 1,
        parallel_tool_calls: bool = True,
        **kwargs,
    ) -> llm.LLMStream:
        """Process chat with document context"""

        start_time = time.time()

        # Extract last user message
        user_message = ""
        for msg in reversed(chat_ctx.messages):
            if msg.role == "user":
                user_message = msg.content
                break

        # Search for relevant documents
        rag_start = time.time()
        doc_context = await self.rag_service.search(
            query=user_message, top_k=3, filters={"type": "document"}
        )
        rag_latency = (time.time() - rag_start) * 1000

        # Build enhanced prompt with document context
        enhanced_messages = chat_ctx.messages.copy()

        if doc_context:
            context_text = "\n\n".join(
                [
                    f"Document: {doc['title']}\nContent: {doc['content'][:500]}..."
                    for doc in doc_context
                ]
            )

            # Insert document context
            enhanced_messages.insert(
                -1,
                llm.ChatMessage(
                    role="system", content=f"Relevant document context:\n{context_text}"
                ),
            )

        # Stream response from OpenAI
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": m.role, "content": m.content} for m in enhanced_messages
            ],
            temperature=temperature,
            n=n,
            stream=True,
            functions=[
                {
                    "name": "track_action_item",
                    "description": "Track an action item from the conversation",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "description": "The action item",
                            },
                            "assignee": {
                                "type": "string",
                                "description": "Who is responsible",
                            },
                            "due_date": {
                                "type": "string",
                                "description": "When it's due",
                            },
                        },
                        "required": ["action"],
                    },
                },
                {
                    "name": "search_documents",
                    "description": "Search for specific documents",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"},
                            "filters": {
                                "type": "object",
                                "description": "Optional filters",
                            },
                        },
                        "required": ["query"],
                    },
                },
            ]
            if fnc_ctx
            else None,
        )

        class DocumentLLMStream(llm.LLMStream):
            def __init__(self, stream, start_time, rag_latency):
                super().__init__()
                self._stream = stream
                self._start_time = start_time
                self._rag_latency = rag_latency

            async def aclose(self):
                pass

            async def __anext__(self) -> llm.ChatChunk:
                chunk = await self._stream.__anext__()

                if chunk.choices[0].delta.content:
                    return llm.ChatChunk(
                        choices=[
                            llm.Choice(
                                delta=llm.ChoiceDelta(
                                    role="assistant",
                                    content=chunk.choices[0].delta.content,
                                ),
                                index=0,
                            )
                        ],
                        metadata={
                            "llm_latency_ms": (time.time() - self._start_time) * 1000,
                            "rag_latency_ms": self._rag_latency,
                        },
                    )
                elif chunk.choices[0].delta.function_call:
                    # Handle function calls
                    return llm.ChatChunk(
                        choices=[
                            llm.Choice(
                                delta=llm.ChoiceDelta(
                                    role="assistant",
                                    content=None,
                                    tool_calls=[chunk.choices[0].delta.function_call],
                                ),
                                index=0,
                            )
                        ]
                    )

                raise StopAsyncIteration

        return DocumentLLMStream(stream, start_time, rag_latency)


class EnhancedVoiceService:
    """Production-ready voice service with document intelligence"""

    def __init__(self):
        self.rag_service = ModernRAGService()
        self.conversation_contexts: Dict[str, ConversationContext] = {}
        self.metrics = VoiceMetrics()

        # Initialize components
        self.stt = OptimizedDeepgramSTT()
        self.tts = OptimizedCartesiaTTS()
        self.llm = DocumentIntelligenceLLM(self.rag_service)
        self.vad = silero_vad.VAD.load()

    async def create_voice_assistant(
        self, ctx: JobContext, participant_identity: str = "user"
    ) -> VoiceAssistant:
        """Create an optimized voice assistant"""

        # Get or create conversation context
        room_name = ctx.room.name
        if room_name not in self.conversation_contexts:
            self.conversation_contexts[room_name] = ConversationContext()

        context = self.conversation_contexts[room_name]

        # Create voice assistant with optimized settings
        assistant = VoiceAssistant(
            vad=self.vad,
            stt=self.stt,
            llm=self.llm,
            tts=self.tts,
            chat_ctx=llm.ChatContext(
                messages=[
                    llm.ChatMessage(
                        role="system",
                        content=f"""You are an intelligent document assistant integrated with a comprehensive knowledge base.

Current context:
- Conversation started: {context.conversation_start}
- Documents accessed: {len(context.current_documents)}
- Action items tracked: {len(context.action_items)}

Your capabilities:
1. Search and analyze documents using natural language
2. Track action items and decisions
3. Provide summaries and insights
4. Answer questions with specific document references

Guidelines:
- Keep responses concise (1-2 sentences) unless asked for details
- Always cite specific documents when relevant
- Proactively identify and announce action items
- Use natural, conversational language
- Confirm understanding before taking actions

Remember: You have access to the entire document repository. Always search for relevant information before responding.""",
                    )
                ]
            ),
            fnc_ctx=llm.FunctionContext(
                functions=[
                    self._create_action_tracker(context),
                    self._create_document_searcher(context),
                ]
            ),
            interrupt_speech=True,
            turn_detection=agents.turn_detection.EOUModel(
                min_end_of_utterance_delay=0.8,
                max_end_of_utterance_delay=1.5,
                prefix_punctuations={"?": 0.5, ".": 1.0, "!": 1.0},
            ),
        )

        # Set up event handlers for metrics
        assistant.on("user_speech_committed", self._on_user_speech)
        assistant.on("agent_speech_committed", self._on_agent_speech)
        assistant.on("function_call", self._on_function_call)

        return assistant

    def _create_action_tracker(self, context: ConversationContext) -> Callable:
        """Create function for tracking action items"""

        async def track_action_item(
            action: str, assignee: Optional[str] = None, due_date: Optional[str] = None
        ) -> Dict[str, Any]:
            action_item = {
                "action": action,
                "assignee": assignee or "Unassigned",
                "due_date": due_date or "No due date",
                "created_at": datetime.now().isoformat(),
            }

            context.action_items.append(json.dumps(action_item))

            return {
                "status": "tracked",
                "action_item": action_item,
                "total_actions": len(context.action_items),
            }

        return track_action_item

    def _create_document_searcher(self, context: ConversationContext) -> Callable:
        """Create function for searching documents"""

        async def search_documents(
            query: str, filters: Optional[Dict[str, Any]] = None
        ) -> Dict[str, Any]:
            # Perform search
            results = await self.rag_service.search(
                query=query, top_k=5, filters=filters
            )

            # Update context
            for result in results:
                doc_id = result.get("id", "")
                if doc_id not in context.current_documents:
                    context.current_documents.append(doc_id)

            return {
                "status": "found",
                "count": len(results),
                "documents": [
                    {
                        "title": r.get("title", "Untitled"),
                        "snippet": r.get("content", "")[:200] + "...",
                        "relevance": r.get("score", 0),
                    }
                    for r in results
                ],
            }

        return search_documents

    async def _on_user_speech(self, text: str):
        """Handle user speech events"""
        logger.info(f"User said: {text}")

        # Update metrics
        self.metrics.stt_latency = getattr(self, "_last_stt_latency", 0)

        # Send transcription to participants
        await self._broadcast_transcription("user", text, True)

    async def _on_agent_speech(self, text: str):
        """Handle agent speech events"""
        logger.info(f"Assistant said: {text}")

        # Update metrics
        self.metrics.tts_latency = getattr(self, "_last_tts_latency", 0)
        # End-to-end perceived latency (STT + LLM + TTS) — the sub-200ms SLA target.
        self.metrics.total_latency = (
            self.metrics.stt_latency
            + self.metrics.llm_latency
            + self.metrics.tts_latency
        )
        if self.metrics.total_latency > 0:
            observe_voice_latency("end_to_end", self.metrics.total_latency)
        self.metrics.log_metrics()

        # Send transcription to participants
        await self._broadcast_transcription("assistant", text, True)

    async def _on_function_call(self, function_name: str, args: Dict[str, Any]):
        """Handle function calls"""
        logger.info(f"Function called: {function_name} with args: {args}")

        # Broadcast action to participants
        await self._broadcast_action(
            {"type": "function_call", "function": function_name, "args": args}
        )

    async def _broadcast_transcription(self, speaker: str, text: str, is_final: bool):
        """Broadcast transcription to all participants"""
        if hasattr(self, "_room"):
            data = {
                "type": "transcription",
                "speaker": speaker,
                "text": text,
                "isFinal": is_final,
                "timestamp": datetime.now().isoformat(),
            }

            await self._room.local_participant.publish_data(
                json.dumps(data).encode("utf-8"), reliable=True
            )

    async def _broadcast_action(self, action: Dict[str, Any]):
        """Broadcast action to all participants"""
        if hasattr(self, "_room"):
            await self._room.local_participant.publish_data(
                json.dumps(action).encode("utf-8"), reliable=True
            )

    async def _broadcast_metrics(self):
        """Broadcast performance metrics"""
        if hasattr(self, "_room"):
            metrics_data = {
                "type": "metrics",
                "metrics": {
                    "latency": self.metrics.total_latency,
                    "audioLevel": 0,
                    "connectionQuality": "excellent"
                    if self.metrics.total_latency < 100
                    else "good",
                },
            }

            await self._room.local_participant.publish_data(
                json.dumps(metrics_data).encode("utf-8"), reliable=False
            )


# Worker entry point
async def entrypoint(ctx: JobContext):
    """Enhanced LiveKit agent entry point"""

    logger.info(f"Starting enhanced voice agent for room: {ctx.room.name}")

    # Initialize service
    voice_service = EnhancedVoiceService()
    voice_service._room = ctx.room

    # Auto-subscribe to audio only
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Create and start assistant
    assistant = await voice_service.create_voice_assistant(ctx)
    assistant.start(ctx.room)

    # Send initial greeting
    await asyncio.sleep(0.5)
    await assistant.say(
        "Hello! I'm your AI assistant with access to your document library. "
        "I can help you search, analyze, and track information. How can I help?",
        allow_interruptions=True,
    )

    # Broadcast metrics periodically
    async def metrics_loop():
        while True:
            await asyncio.sleep(5)
            await voice_service._broadcast_metrics()

    # Start metrics broadcasting
    asyncio.create_task(metrics_loop())

    # Handle participant events
    @ctx.room.on("participant_connected")
    async def on_participant_connected(participant: rtc.RemoteParticipant):
        logger.info(f"Participant connected: {participant.identity}")
        await assistant.say(
            f"Welcome {participant.identity}!", allow_interruptions=True
        )

    @ctx.room.on("data_received")
    async def on_data_received(data: bytes, participant: rtc.RemoteParticipant):
        """Handle data from participants"""
        try:
            message = json.loads(data.decode("utf-8"))

            if message.get("type") == "command":
                command = message.get("command", "")

                if command == "summary":
                    # Generate conversation summary
                    context = voice_service.conversation_contexts.get(ctx.room.name)
                    if context:
                        summary = (
                            f"Summary: {len(context.messages)} messages exchanged, "
                        )
                        summary += f"{len(context.action_items)} action items tracked, "
                        summary += (
                            f"{len(context.current_documents)} documents referenced."
                        )
                        await assistant.say(summary)

                elif command == "action_items":
                    # List action items
                    context = voice_service.conversation_contexts.get(ctx.room.name)
                    if context and context.action_items:
                        await assistant.say(
                            f"I've tracked {len(context.action_items)} action items. "
                            "Would you like me to list them?"
                        )
        except Exception as e:
            logger.error(f"Error processing participant data: {e}")

    # Keep the agent running
    await asyncio.Event().wait()


# Create worker options
def create_worker_options() -> WorkerOptions:
    """Create optimized worker options"""
    return WorkerOptions(
        entrypoint_fnc=entrypoint,
        max_idle_time=30,
        num_idle_processes=2,
        shutdown_process_timeout=10,
        port_range=(10000, 10100),
        host="0.0.0.0",
    )
