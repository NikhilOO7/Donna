'use client';

/**
 * LiveAudioCapture
 *
 * Joins the meeting's LiveKit room and publishes the user's microphone
 * track. A backend LiveKit Agent (`meeting_voice_worker.py`) auto-joins
 * the same room, transcribes audio via Deepgram, and posts utterances
 * to the backend — which then runs the meeting agent dispatcher.
 *
 * Falls back to a clear error message when the worker isn't running.
 */

import React, { useState, useRef, useCallback } from 'react';
import { Mic, MicOff, Loader2, AlertCircle } from 'lucide-react';
import { Room, RoomEvent, LocalAudioTrack, createLocalAudioTrack } from 'livekit-client';
import { apiClient } from '@/lib/api-client';

interface LiveAudioCaptureProps {
  meetingId: string;
  speakerName: string;
  /** Lets the stage tell the truth about whether audio is actually flowing. */
  onStatusChange?: (status: Status) => void;
}

export type Status = 'idle' | 'connecting' | 'live' | 'error';

export default function LiveAudioCapture({
  meetingId,
  speakerName,
  onStatusChange,
}: LiveAudioCaptureProps) {
  const [status, setStatusRaw] = useState<Status>('idle');

  const setStatus = useCallback(
    (next: Status) => {
      setStatusRaw(next);
      onStatusChange?.(next);
    },
    [onStatusChange],
  );

  const [conference, setConference] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isMuted, setIsMuted] = useState(false);
  const roomRef = useRef<Room | null>(null);
  const trackRef = useRef<LocalAudioTrack | null>(null);

  const handleStart = useCallback(async () => {
    setStatus('connecting');
    setError(null);

    try {
      // Fetch a meeting-scoped LiveKit token
      const { token, url } = await apiClient.getMeetingVoiceToken(
        meetingId,
        speakerName || 'You',
        conference,
      );
      if (!token || !url) throw new Error('Token response missing token/url');

      // Create + publish mic
      const room = new Room({ adaptiveStream: true, dynacast: true });
      roomRef.current = room;

      room.on(RoomEvent.Disconnected, () => {
        setStatus('idle');
        trackRef.current = null;
        roomRef.current = null;
      });

      await room.connect(url, token);

      const track = await createLocalAudioTrack({
        echoCancellation: true,
        noiseSuppression: true,
      });
      trackRef.current = track;
      await room.localParticipant.publishTrack(track);

      setStatus('live');
    } catch (e: any) {
      console.error('LiveAudioCapture connect failed:', e);
      setError(
        e?.response?.data?.detail
          ?? e?.message
          ?? 'Failed to connect to voice room',
      );
      setStatus('error');
      try {
        await roomRef.current?.disconnect();
      } catch {}
      roomRef.current = null;
      trackRef.current = null;
    }
  }, [meetingId, speakerName, conference]);

  const handleStop = useCallback(async () => {
    try {
      if (trackRef.current) {
        trackRef.current.stop();
        trackRef.current = null;
      }
      await roomRef.current?.disconnect();
    } catch (e) {
      console.warn('disconnect error:', e);
    } finally {
      roomRef.current = null;
      setStatus('idle');
      setIsMuted(false);
    }
  }, []);

  const handleToggleMute = useCallback(async () => {
    const track = trackRef.current;
    if (!track) return;
    try {
      if (isMuted) {
        await track.unmute();
      } else {
        await track.mute();
      }
      setIsMuted(!isMuted);
    } catch (e) {
      console.warn('mute toggle failed:', e);
    }
  }, [isMuted]);

  // --- UI ---

  // NOTE: this component renders on a WHITE stage. Earlier revisions styled it
  // for a dark surface (text-white on bg-white/10), which left "Enable Mic"
  // technically present but invisible — the meeting looked like it had hung
  // while waiting for a click nobody could see.

  if (status === 'idle' || status === 'error') {
    return (
      <div className="flex flex-col items-center gap-3">
        <button
          onClick={handleStart}
          className="flex items-center gap-2 px-6 py-3 rounded-full bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold shadow-md hover:shadow-lg transition-all active:scale-[0.98]"
          title="Enable microphone for live transcription"
        >
          <Mic className="w-4 h-4" />
          <span>{status === 'error' ? 'Retry microphone' : 'Enable microphone'}</span>
        </button>

        <label
          className="flex items-center gap-1.5 text-[11px] text-gray-500 hover:text-gray-700 cursor-pointer select-none"
          title="Several people share one microphone — Donna separates speakers acoustically"
        >
          <input
            type="checkbox"
            checked={conference}
            onChange={(e) => setConference(e.target.checked)}
            className="w-3 h-3 accent-indigo-500"
          />
          Conference room
        </label>

        {status === 'error' && error && (
          <div
            className="flex items-start gap-1.5 text-[11px] text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2 max-w-sm"
            title={error}
          >
            <AlertCircle className="w-3.5 h-3.5 flex-shrink-0 mt-px" />
            <span>{error}</span>
          </div>
        )}
      </div>
    );
  }

  if (status === 'connecting') {
    return (
      <button
        disabled
        className="flex items-center gap-2 px-6 py-3 rounded-full bg-gray-100 text-gray-500 text-sm font-semibold cursor-wait"
      >
        <Loader2 className="w-4 h-4 animate-spin" />
        <span>Connecting…</span>
      </button>
    );
  }

  // status === 'live'
  return (
    <div className="flex items-center gap-2">
      <button
        onClick={handleToggleMute}
        className={`p-2.5 rounded-full border transition-all ${
          isMuted
            ? 'bg-red-50 border-red-200 text-red-600 hover:bg-red-100'
            : 'bg-emerald-50 border-emerald-200 text-emerald-700 hover:bg-emerald-100'
        }`}
        title={isMuted ? 'Unmute' : 'Mute'}
      >
        {isMuted ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
      </button>
      <button
        onClick={handleStop}
        className="px-4 py-2 rounded-full border border-gray-200 bg-white hover:bg-gray-50 text-gray-600 text-sm transition-colors"
        title="Stop transcription"
      >
        Stop mic
      </button>
    </div>
  );
}
