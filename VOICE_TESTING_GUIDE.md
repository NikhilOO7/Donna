# Voice Message Flow Validation Guide

This guide helps you validate that voice messages from your frontend are reaching the backend and being processed correctly.

## Architecture Overview

```
┌─────────────┐     ┌──────────────┐     ┌───────────────┐     ┌─────────────────┐
│  Frontend   │────▶│   FastAPI    │────▶│   LiveKit     │────▶│  Voice Worker   │
│  (Browser)  │     │   Backend    │     │    Server     │     │  (Agent)        │
└─────────────┘     └──────────────┘     └───────────────┘     └─────────────────┘
      │                    │                     │                      │
      │                    │                     │                      ├─▶ Deepgram STT
      │                    │                     │                      ├─▶ OpenAI LLM
      │                    │                     │                      └─▶ Cartesia TTS
      │                    │                     │
      └────────────────────┴─────────────────────┴────────────────▶ Audio Stream
```

## Step-by-Step Validation

### 1. Verify Infrastructure Services

First, ensure all required services are running:

```bash
# Check Docker containers
docker ps

# You should see:
# - voice-doc-livekit (port 7880) - MUST be healthy
# - voice-doc-redis (port 6379) - MUST be healthy
# - voice-doc-postgres (port 5432)
# - voice-doc-qdrant (port 6333)
```

**Test LiveKit Server:**
```bash
curl http://localhost:7880/
# Should return: OK
```

### 2. Check Backend API Health

```bash
# Check FastAPI server health
curl http://localhost:8000/health | jq

# Should return:
# {
#   "status": "healthy",
#   "database": "connected",
#   "services": {
#     "voice_worker": "running" or "disabled"
#   }
# }
```

**Test Voice-specific health endpoint:**
```bash
curl http://localhost:8000/api/v1/voice/health | jq

# Should return:
# {
#   "status": "healthy",
#   "services": {
#     "livekit": "healthy",
#     "deepgram": "configured",
#     "cartesia": "configured"
#   },
#   "active_rooms": 0
# }
```

### 3. Test Voice Room Creation

Create a test room via API:

```bash
curl -X POST http://localhost:8000/api/v1/voice/create-room \
  -H "Content-Type: application/json" \
  -d '{
    "participant_name": "TestUser",
    "enable_transcription": true
  }' | jq

# Expected response:
# {
#   "room_name": "voice-room-xxxxx",
#   "token": "eyJhbGc...",  # JWT token
#   "url": "ws://localhost:7880",
#   "participant_name": "TestUser",
#   "session_id": "uuid",
#   "expires_at": "2025-11-17T..."
# }
```

**Save the response values:**
- `room_name`: You'll need this for testing
- `token`: Required for frontend connection
- `session_id`: For tracking the session

### 4. Verify Room Exists in LiveKit

Check that the room was created:

```bash
# Replace {room_name} with actual room name from previous step
curl http://localhost:8000/api/v1/voice/room/{room_name}/status | jq

# Expected response:
# {
#   "room_name": "voice-room-xxxxx",
#   "is_active": true,
#   "participant_count": 0,  # Nobody joined yet
#   "agent_connected": false,
#   "duration_seconds": X
# }
```

### 5. Check Voice Worker Logs

Monitor the voice worker to see if it detects the room:

```bash
# If running worker separately:
tail -f enhanced_voice_agent.log

# Look for:
# - "agent joined room: voice-room-xxxxx"
# - "participant connected: TestUser"
```

### 6. Test WebSocket Connection

Test the real-time WebSocket endpoint:

```javascript
// In browser console or Node.js:
const ws = new WebSocket('ws://localhost:8000/api/v1/voice/ws/{room_name}');

ws.onopen = () => {
    console.log('✅ WebSocket connected');
    ws.send(JSON.stringify({ type: 'ping' }));
};

ws.onmessage = (event) => {
    console.log('📨 Received:', JSON.parse(event.data));
};

ws.onerror = (error) => {
    console.error('❌ WebSocket error:', error);
};
```

Expected messages:
```json
{
  "type": "connected",
  "room_name": "voice-room-xxxxx",
  "session_id": "uuid"
}
{
  "type": "pong"
}
```

### 7. Frontend Integration Test

Here's a complete frontend test script using LiveKit SDK:

**Create test file: `test-voice-connection.html`**

```html
<!DOCTYPE html>
<html>
<head>
    <title>Voice Connection Test</title>
    <script src="https://unpkg.com/livekit-client/dist/livekit-client.umd.min.js"></script>
</head>
<body>
    <h1>Voice Message Flow Test</h1>
    <button id="createRoom">1. Create Room</button>
    <button id="connectRoom" disabled>2. Connect to Room</button>
    <button id="startAudio" disabled>3. Start Audio</button>
    <button id="sendMessage" disabled>4. Send Test Message</button>

    <div id="status"></div>
    <div id="logs"></div>

    <script>
        const API_BASE = 'http://localhost:8000';
        let roomName, token, room;

        function log(message, type = 'info') {
            const logs = document.getElementById('logs');
            const time = new Date().toLocaleTimeString();
            const color = type === 'error' ? 'red' : type === 'success' ? 'green' : 'black';
            logs.innerHTML += `<p style="color: ${color}">[${time}] ${message}</p>`;
            console.log(message);
        }

        // Step 1: Create Room
        document.getElementById('createRoom').onclick = async () => {
            try {
                log('Creating voice room...');
                const response = await fetch(`${API_BASE}/api/v1/voice/create-room`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        participant_name: 'TestUser',
                        enable_transcription: true
                    })
                });

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${await response.text()}`);
                }

                const data = await response.json();
                roomName = data.room_name;
                token = data.token;

                log(`✅ Room created: ${roomName}`, 'success');
                log(`Session ID: ${data.session_id}`);
                document.getElementById('connectRoom').disabled = false;
            } catch (error) {
                log(`❌ Failed to create room: ${error.message}`, 'error');
            }
        };

        // Step 2: Connect to Room
        document.getElementById('connectRoom').onclick = async () => {
            try {
                log('Connecting to LiveKit room...');
                room = new LivekitClient.Room();

                // Event handlers
                room.on('connected', () => {
                    log('✅ Connected to LiveKit room', 'success');
                    document.getElementById('startAudio').disabled = false;
                });

                room.on('participantConnected', (participant) => {
                    log(`👤 Participant joined: ${participant.identity}`);
                });

                room.on('trackSubscribed', (track, publication, participant) => {
                    log(`🎵 Track subscribed from ${participant.identity}: ${track.kind}`);
                    if (track.kind === 'audio') {
                        const audioElement = document.createElement('audio');
                        audioElement.autoplay = true;
                        track.attach(audioElement);
                        document.body.appendChild(audioElement);
                        log('✅ Audio track attached and playing', 'success');
                    }
                });

                room.on('dataReceived', (payload, participant) => {
                    const decoder = new TextDecoder();
                    const message = decoder.decode(payload);
                    log(`📨 Data received from ${participant.identity}: ${message}`);
                });

                room.on('disconnected', () => {
                    log('🔌 Disconnected from room');
                });

                // Connect
                await room.connect('ws://localhost:7880', token);

            } catch (error) {
                log(`❌ Connection failed: ${error.message}`, 'error');
            }
        };

        // Step 3: Start Audio
        document.getElementById('startAudio').onclick = async () => {
            try {
                log('Requesting microphone access...');
                await room.localParticipant.setMicrophoneEnabled(true);
                log('✅ Microphone enabled', 'success');
                document.getElementById('sendMessage').disabled = false;
            } catch (error) {
                log(`❌ Microphone access failed: ${error.message}`, 'error');
            }
        };

        // Step 4: Send Test Message
        document.getElementById('sendMessage').onclick = async () => {
            try {
                const testMessage = 'Hello, this is a test message from the frontend';
                const encoder = new TextEncoder();
                await room.localParticipant.publishData(encoder.encode(testMessage));
                log(`✅ Sent message: "${testMessage}"`, 'success');
                log('💡 Now speak into your microphone - the agent should respond');
            } catch (error) {
                log(`❌ Failed to send message: ${error.message}`, 'error');
            }
        };
    </script>
</body>
</html>
```

### 8. Validate Voice Processing Pipeline

Once connected and speaking, check these logs:

**Backend Logs (FastAPI):**
```bash
# Look for:
INFO: WebSocket connected for room: voice-room-xxxxx
INFO: Room created: voice-room-xxxxx
```

**LiveKit Server Logs:**
```bash
docker logs voice-doc-livekit -f

# Look for:
# - Room created: voice-room-xxxxx
# - Participant joined: TestUser
# - Agent joined: agent-xxxxx
# - Track published: audio
```

**Voice Worker Logs:**
```bash
# Look for in enhanced_voice_agent.log:
INFO: agent joined room: voice-room-xxxxx
INFO: participant connected: TestUser
DEBUG: STT processing audio chunk...
DEBUG: Detected speech: "hello"
DEBUG: LLM processing query...
DEBUG: TTS generating response...
INFO: Response sent to participant
```

### 9. Check Metrics

Monitor latency and performance:

```bash
# Get session metrics
curl http://localhost:8000/api/v1/voice/session/{session_id}/metrics | jq

# Expected response:
# {
#   "session_id": "uuid",
#   "metrics": {
#     "vad_latency_ms": 10,
#     "stt_latency_ms": 85,
#     "llm_latency_ms": 120,
#     "tts_latency_ms": 45,
#     "total_latency_ms": 260
#   },
#   "quality_score": 95.0
# }
```

**Prometheus Metrics (if enabled):**
```bash
curl http://localhost:9091/metrics | grep voice_
```

### 10. Get Transcript

After conversation, retrieve the transcript:

```bash
curl http://localhost:8000/api/v1/voice/session/{session_id}/transcript | jq

# Expected response:
# {
#   "session_id": "uuid",
#   "transcript": [
#     {
#       "speaker": "user",
#       "text": "Hello, can you help me?",
#       "timestamp": "2025-11-17T..."
#     },
#     {
#       "speaker": "assistant",
#       "text": "Of course! How can I assist you?",
#       "timestamp": "2025-11-17T..."
#     }
#   ],
#   "action_items": [],
#   "key_decisions": []
# }
```

## Common Issues and Solutions

### Issue 1: "Cannot connect to LiveKit"
**Symptoms:** Frontend shows connection error
**Check:**
```bash
curl http://localhost:7880/
docker ps | grep livekit
docker logs voice-doc-livekit
```
**Solution:** Ensure LiveKit container is running and healthy

### Issue 2: "Room not found"
**Symptoms:** 404 error when checking room status
**Check:**
```bash
curl http://localhost:8000/api/v1/voice/health | jq '.active_rooms'
```
**Solution:** Room might have expired or been deleted. Create a new room.

### Issue 3: "Agent not joining"
**Symptoms:** `agent_connected: false` in room status
**Check:**
```bash
# Check if worker is running
ps aux | grep enhanced_voice_agent_worker
tail -f enhanced_voice_agent.log
```
**Solution:** Start the voice worker or check worker logs for errors

### Issue 4: "No audio received"
**Symptoms:** Can't hear agent responses
**Check:**
- Browser microphone permissions granted?
- Audio tracks subscribed in frontend?
- Check browser console for errors
**Solution:**
```javascript
// In browser console:
room.remoteParticipants.forEach(p => {
    console.log(`Participant ${p.identity} tracks:`, p.audioTracks);
});
```

### Issue 5: "High latency"
**Symptoms:** Slow responses, quality_score < 80
**Check:**
```bash
curl http://localhost:8000/api/v1/voice/session/{session_id}/metrics | jq '.metrics'
```
**Solution:**
- Check network connectivity
- Verify API keys are valid (Deepgram, Cartesia)
- Optimize RAG queries if `rag_latency_ms > 200`

## Debugging Commands Reference

```bash
# Check all services
docker-compose -f infrastructure/local/docker-compose.yml ps

# View LiveKit logs
docker logs voice-doc-livekit -f

# View Redis logs
docker logs voice-doc-redis --tail 50

# Check API health
curl http://localhost:8000/health | jq

# Check voice health
curl http://localhost:8000/api/v1/voice/health | jq

# List active rooms
curl http://localhost:8000/api/v1/voice/health | jq '.active_rooms'

# Monitor worker
tail -f enhanced_voice_agent.log

# Check Prometheus metrics
curl http://localhost:9091/metrics | grep voice_

# Test audio with LiveKit CLI (if installed)
livekit-cli join-room --url ws://localhost:7880 --api-key [key] --api-secret [secret]
```

## Integration Checklist

- [ ] LiveKit server running and healthy
- [ ] Backend API responding
- [ ] Voice health endpoint shows all services configured
- [ ] Can create room via API
- [ ] Room appears in LiveKit
- [ ] WebSocket connection succeeds
- [ ] Frontend can connect to room
- [ ] Microphone permission granted
- [ ] Audio tracks published
- [ ] Agent joins room automatically
- [ ] Agent receives audio
- [ ] Agent responds with audio
- [ ] Transcript recorded correctly
- [ ] Metrics collected properly

## Next Steps

After validation:
1. **Production Setup:** Use production LiveKit URL and credentials
2. **Security:** Implement authentication on API endpoints
3. **Monitoring:** Set up Grafana dashboards for metrics
4. **Testing:** Add automated E2E tests
5. **Error Handling:** Implement reconnection logic in frontend

## Useful Links

- LiveKit Docs: https://docs.livekit.io/
- Deepgram API: https://developers.deepgram.com/
- Cartesia API: https://docs.cartesia.ai/
- Frontend SDK: https://github.com/livekit/client-sdk-js
