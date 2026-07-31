'use client';

import React, { useState, useEffect } from 'react';
import { Mic, MicOff, Phone, PhoneOff, Volume2, VolumeX } from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import '@livekit/components-styles';
import {
  LiveKitRoom,
  RoomAudioRenderer,
  useVoiceAssistant,
  BarVisualizer,
  VoiceAssistantControlBar,
} from '@livekit/components-react';
import type { VoiceToken } from '@/types';

function VoiceAssistantUI() {
  const { state, audioTrack } = useVoiceAssistant();

  return (
    <div className="flex flex-col items-center gap-6 p-6">
      {/* Status */}
      <div className="text-center">
        <div className={`
          inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium
          ${state === 'listening' ? 'bg-green-100 text-green-800' :
            state === 'thinking' ? 'bg-blue-100 text-blue-800' :
            state === 'speaking' ? 'bg-purple-100 text-purple-800' :
            'bg-gray-100 text-gray-800'}
        `}>
          {state === 'listening' && <Mic className="w-4 h-4" />}
          {state === 'thinking' && (
            <div className="w-4 h-4 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
          )}
          {state === 'speaking' && <Volume2 className="w-4 h-4" />}
          <span className="capitalize">{state}</span>
        </div>
      </div>

      {/* Visualizer */}
      <div className="w-full max-w-md">
        {audioTrack && (
          <BarVisualizer
            state={state}
            barCount={20}
            trackRef={audioTrack}
            className="h-32"
          />
        )}
      </div>

      {/* Instructions */}
      <div className="text-center max-w-md">
        <p className="text-sm text-gray-600">
          {(state === 'disconnected' || state === 'connecting') &&
            'Click the microphone to start talking'}
          {state === 'listening' && 'Speak your question...'}
          {state === 'thinking' && 'Processing your query...'}
          {state === 'speaking' && 'Playing response...'}
        </p>
      </div>

      {/* Controls */}
      <VoiceAssistantControlBar />
    </div>
  );
}

export default function VoiceInterface() {
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [token, setToken] = useState<VoiceToken | null>(null);
  const [error, setError] = useState<string | null>(null);

  const connect = async () => {
    try {
      setConnecting(true);
      setError(null);

      const voiceToken = await apiClient.getVoiceToken();
      setToken(voiceToken);
      setConnected(true);
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to connect to voice service');
      console.error('Voice connection error:', err);
    } finally {
      setConnecting(false);
    }
  };

  const disconnect = () => {
    setToken(null);
    setConnected(false);
  };

  if (!connected) {
    return (
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-8">
        <div className="text-center max-w-md mx-auto">
          <div className="w-16 h-16 bg-primary-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <Mic className="w-8 h-8 text-primary-600" />
          </div>

          <h2 className="text-xl font-semibold text-gray-900 mb-2">
            Voice Assistant
          </h2>

          <p className="text-gray-600 mb-6">
            Connect to the voice assistant to ask questions about your documents using your voice.
          </p>

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-4">
              <p className="text-sm text-red-800">{error}</p>
            </div>
          )}

          <button
            onClick={connect}
            disabled={connecting}
            className={`
              px-6 py-3 rounded-lg font-medium inline-flex items-center gap-2
              ${connecting
                ? 'bg-gray-300 cursor-not-allowed text-gray-600'
                : 'bg-primary-600 hover:bg-primary-700 text-white'
              }
            `}
          >
            {connecting ? (
              <>
                <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Connecting...
              </>
            ) : (
              <>
                <Phone className="w-5 h-5" />
                Connect to Voice Assistant
              </>
            )}
          </button>

          <div className="mt-6 p-4 bg-gray-50 rounded-lg text-left">
            <p className="text-xs font-medium text-gray-700 mb-2">Features:</p>
            <ul className="text-xs text-gray-600 space-y-1">
              <li>• Ultra-low latency speech recognition (Deepgram Nova-3)</li>
              <li>• Natural voice synthesis (Cartesia Sonic)</li>
              <li>• Contextual document search</li>
              <li>• Real-time conversation</li>
            </ul>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200">
      {/* Header */}
      <div className="border-b border-gray-200 p-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Voice Assistant</h2>
          <p className="text-sm text-gray-500">Connected to LiveKit</p>
        </div>

        <button
          onClick={disconnect}
          className="px-4 py-2 bg-red-50 text-red-700 rounded-lg hover:bg-red-100 transition-colors inline-flex items-center gap-2 text-sm font-medium"
        >
          <PhoneOff className="w-4 h-4" />
          Disconnect
        </button>
      </div>

      {/* Voice Assistant */}
      {token && (
        <LiveKitRoom
          token={token.token}
          serverUrl={token.url}
          connect={true}
          audio={true}
          video={false}
          onDisconnected={disconnect}
          onError={(error) => {
            console.error('LiveKit error:', error);
            setError(error.message);
          }}
        >
          <VoiceAssistantUI />
          <RoomAudioRenderer />
        </LiveKitRoom>
      )}
    </div>
  );
}
