'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Mic, PhoneOff, Play, MessageSquare, Plus, Radio, Send,
} from 'lucide-react';
import NudgeCard from './NudgeCard';
import LiveAudioCapture from './LiveAudioCapture';
import { apiClient } from '@/lib/api-client';

interface MeetingRoomProps {
  meeting: any;
  onRefresh: () => void;
}

type Utterance = { speaker: string; text: string; timestamp?: string };

export default function MeetingRoom({ meeting, onRefresh }: MeetingRoomProps) {
  const [decisionText, setDecisionText] = useState('');
  const [showDecisionForm, setShowDecisionForm] = useState(false);
  const isLive = meeting.status === 'in_progress';

  // Transcript state
  const transcriptUtterances: Utterance[] = useMemo(
    () => meeting.transcript?.utterances || [],
    [meeting.transcript?.utterances],
  );

  // Build a speaker list: meeting attendees + "You" fallback
  const speakerOptions = useMemo<string[]>(() => {
    const fromAttendees: string[] = (meeting.attendees || [])
      .map((a: any) => a?.name || a?.email)
      .filter(Boolean);
    const known = new Set(fromAttendees);
    transcriptUtterances.forEach((u) => {
      if (u.speaker) known.add(u.speaker);
    });
    const list = Array.from(known);
    if (list.length === 0) list.push('You');
    return list;
  }, [meeting.attendees, transcriptUtterances]);

  const [speaker, setSpeaker] = useState<string>('');
  useEffect(() => {
    if (!speaker && speakerOptions[0]) setSpeaker(speakerOptions[0]);
  }, [speakerOptions, speaker]);

  const [utteranceText, setUtteranceText] = useState('');
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll transcript to latest
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [transcriptUtterances.length]);

  const handleSendUtterance = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const text = utteranceText.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      await apiClient.addUtterance(meeting.id, speaker || 'You', text);
      setUtteranceText('');
      // Trigger refresh — parent will repoll and pick up new utterance + nudges
      onRefresh();
    } catch (error) {
      console.error('Failed to add utterance:', error);
    } finally {
      setSending(false);
    }
  };

  const handleStartMeeting = async () => {
    try {
      await apiClient.client.post(`/api/v1/meetings/${meeting.id}/start`);
      onRefresh();
    } catch (error) {
      console.error('Failed to start meeting:', error);
    }
  };

  const handleEndMeeting = async () => {
    if (!confirm('End this meeting?')) return;
    try {
      await apiClient.client.post(`/api/v1/meetings/${meeting.id}/end`);
      onRefresh();
    } catch (error) {
      console.error('Failed to end meeting:', error);
    }
  };

  const handleAddDecision = async (text?: string, sourceNudgeId?: string) => {
    const decision = text || decisionText;
    if (!decision.trim()) return;
    try {
      await apiClient.addDecision(meeting.id, {
        decision_text: decision,
        ...(sourceNudgeId ? { source_nudge_id: sourceNudgeId } : {}),
      });
      setDecisionText('');
      setShowDecisionForm(false);
      onRefresh();
    } catch (error) {
      console.error('Failed to add decision:', error);
    }
  };

  // Not started yet
  if (!isLive && meeting.status !== 'completed') {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <div className="w-20 h-20 bg-gradient-to-br from-primary-100 to-primary-200 rounded-2xl flex items-center justify-center mb-6 shadow-sm">
          <Mic className="w-10 h-10 text-primary-600" />
        </div>
        <h3 className="text-lg font-semibold text-gray-900 mb-2">Ready to Start</h3>
        <p className="text-gray-500 mb-6 text-center max-w-sm text-sm">
          Start the live session to enable transcription, AI nudge cards, and decision tracking.
        </p>
        <button
          onClick={handleStartMeeting}
          className="flex items-center gap-2 px-6 py-3 bg-[#4f46e5] hover:bg-[#4338ca] text-white rounded-xl shadow-md hover:shadow-lg transition-all duration-200 active:scale-[0.98]"
        >
          <Play className="w-5 h-5" />
          Start Meeting
        </button>
      </div>
    );
  }

  // Meeting completed
  if (meeting.status === 'completed') {
    return (
      <div className="text-center py-10">
        <div className="w-14 h-14 bg-gradient-to-br from-emerald-100 to-emerald-200 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <PhoneOff className="w-7 h-7 text-emerald-600" />
        </div>
        <h3 className="text-lg font-semibold text-gray-900 mb-1">Meeting Ended</h3>
        {meeting.started_at && meeting.ended_at && (
          <p className="text-sm text-gray-500">
            Duration: {Math.round((new Date(meeting.ended_at).getTime() - new Date(meeting.started_at).getTime()) / 60000)} min
          </p>
        )}
        <p className="text-xs text-gray-400 mt-2">
          Proceed to Post-Meeting to generate your summary.
        </p>
      </div>
    );
  }

  // Live meeting
  return (
    <div className="space-y-4">
      {/* Controls Bar */}
      <div className="bg-gradient-to-r from-gray-900 to-gray-800 rounded-xl p-4 flex items-center justify-between shadow-elevated">
        <div className="flex items-center gap-3">
          <div className="relative">
            <Radio className="w-5 h-5 text-red-400" />
            <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 bg-red-500 rounded-full animate-glow" />
          </div>
          <div>
            <span className="font-semibold text-white text-sm">Live Meeting</span>
            {meeting.started_at && (
              <span className="text-gray-400 text-xs ml-2">
                Since {new Date(meeting.started_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <LiveAudioCapture meetingId={meeting.id} speakerName={speaker || 'You'} />
          <button
            onClick={handleEndMeeting}
            className="flex items-center gap-2 px-4 py-2.5 bg-red-500 text-white rounded-xl hover:bg-red-600 transition-all duration-200 shadow-sm active:scale-[0.97]"
          >
            <PhoneOff className="w-4 h-4" />
            <span className="text-sm font-medium">End</span>
          </button>
        </div>
      </div>

      {/* 3-Panel Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Transcript Panel */}
        <div className="bg-white rounded-xl border border-gray-200/60 shadow-card overflow-hidden flex flex-col min-h-[420px]">
          <div className="px-5 py-3.5 border-b border-gray-100 bg-gradient-to-r from-gray-50 to-white flex items-center justify-between">
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">
              Live Transcript
            </h3>
            <span className="text-[11px] text-gray-400">
              {transcriptUtterances.length} {transcriptUtterances.length === 1 ? 'utterance' : 'utterances'}
            </span>
          </div>

          {/* Scrollable utterance list */}
          <div
            ref={scrollRef}
            className="flex-1 overflow-y-auto px-4 py-3 space-y-2.5 max-h-[420px]"
          >
            {transcriptUtterances.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-gray-400 py-8">
                <div className="w-12 h-12 bg-gray-100 rounded-xl flex items-center justify-center mb-3">
                  <Mic className="w-6 h-6 text-gray-300" />
                </div>
                <p className="text-sm font-medium">No utterances yet</p>
                <p className="text-xs text-gray-300 mt-1">Add one below to start the conversation</p>
              </div>
            ) : (
              transcriptUtterances.map((u, i) => (
                <div
                  key={i}
                  className="px-3 py-2 rounded-lg bg-gray-50/80 border border-gray-100 text-sm animate-fade-up"
                >
                  <span className="font-semibold text-[#4f46e5]">{u.speaker}:</span>{' '}
                  <span className="text-gray-700">{u.text}</span>
                </div>
              ))
            )}
          </div>

          {/* Input form */}
          <form
            onSubmit={handleSendUtterance}
            className="border-t border-gray-100 bg-gray-50/40 p-3 flex items-center gap-2"
          >
            <select
              value={speaker}
              onChange={(e) => setSpeaker(e.target.value)}
              className="text-xs bg-white border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-[#4f46e5]/30 max-w-[110px]"
            >
              {speakerOptions.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <input
              type="text"
              value={utteranceText}
              onChange={(e) => setUtteranceText(e.target.value)}
              placeholder="What was said..."
              className="flex-1 text-sm bg-white border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-[#4f46e5]/30"
              disabled={sending}
            />
            <button
              type="submit"
              disabled={sending || !utteranceText.trim()}
              className="p-2 rounded-lg bg-[#4f46e5] hover:bg-[#4338ca] text-white disabled:bg-gray-300 transition-colors"
              title="Send utterance"
            >
              <Send className="w-4 h-4" />
            </button>
          </form>
        </div>

        {/* Nudge Cards Panel */}
        <div className="bg-gradient-to-b from-gray-50 to-white rounded-xl border border-gray-200/60 shadow-card overflow-hidden">
          <div className="px-5 py-3.5 border-b border-gray-100 bg-gradient-to-r from-primary-50/50 to-white">
            <h3 className="text-xs font-bold text-primary-600 uppercase tracking-wider">
              From Donna
            </h3>
          </div>
          <div className="p-4 min-h-[350px]">
            {meeting.nudges?.length > 0 ? (
              <div className="space-y-3">
                {meeting.nudges.map((nudge: any) => (
                  <NudgeCard
                    key={nudge.id}
                    nudge={nudge}
                    onLogDecision={(nudgeId, content) => handleAddDecision(content, nudgeId)}
                  />
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-full text-gray-400">
                <div className="w-12 h-12 bg-primary-50 rounded-xl flex items-center justify-center mb-3">
                  <MessageSquare className="w-6 h-6 text-primary-300" />
                </div>
                <p className="text-sm font-medium text-gray-500">Donna's listening</p>
                <p className="text-xs text-gray-300 mt-1 text-center max-w-[200px]">
                  She'll jump in the moment something matters — a fact to check, a decision to log, a connection you should know.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Decisions Panel */}
        <div className="bg-white rounded-xl border border-gray-200/60 shadow-card overflow-hidden">
          <div className="px-5 py-3.5 border-b border-gray-100 bg-gradient-to-r from-emerald-50/50 to-white flex items-center justify-between">
            <h3 className="text-xs font-bold text-emerald-600 uppercase tracking-wider">
              Decisions & Actions
            </h3>
            <button
              onClick={() => setShowDecisionForm(true)}
              className="p-1.5 bg-emerald-100 text-emerald-600 rounded-lg hover:bg-emerald-200 transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
          </div>
          <div className="p-4 min-h-[350px]">
            {/* Quick Decision Form */}
            {showDecisionForm && (
              <div className="mb-4 p-3 bg-emerald-50 rounded-xl border border-emerald-100 animate-fade-up">
                <textarea
                  value={decisionText}
                  onChange={(e) => setDecisionText(e.target.value)}
                  placeholder="What was decided?"
                  rows={2}
                  className="w-full px-3 py-2 border border-emerald-200 rounded-lg text-sm focus:ring-2 focus:ring-emerald-400 focus:border-emerald-400 resize-none bg-white"
                  autoFocus
                />
                <div className="flex items-center gap-2 mt-2">
                  <button
                    onClick={() => handleAddDecision()}
                    disabled={!decisionText.trim()}
                    className="px-3 py-1.5 bg-emerald-600 text-white text-xs font-medium rounded-lg hover:bg-emerald-700 disabled:bg-gray-300 transition-colors"
                  >
                    Save Decision
                  </button>
                  <button
                    onClick={() => { setShowDecisionForm(false); setDecisionText(''); }}
                    className="px-3 py-1.5 text-gray-500 text-xs rounded-lg hover:bg-gray-100 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {meeting.decisions?.length > 0 ? (
              <div className="space-y-2.5">
                {meeting.decisions.map((d: any, idx: number) => (
                  <div
                    key={d.id}
                    className="p-3 bg-gradient-to-r from-emerald-50 to-green-50 border border-emerald-100 rounded-xl animate-slide-in"
                    style={{ animationDelay: `${idx * 100}ms` }}
                  >
                    <p className="text-sm font-medium text-gray-900">{d.decision_text}</p>
                    <div className="flex items-center gap-2 mt-1.5 text-[11px] text-gray-500">
                      {d.owner && <span className="bg-white px-1.5 py-0.5 rounded border border-gray-200">Owner: {d.owner}</span>}
                      <span className="px-1.5 py-0.5 bg-emerald-100 text-emerald-700 rounded font-medium">{d.status}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : !showDecisionForm ? (
              <div className="flex flex-col items-center justify-center h-full text-gray-400">
                <p className="text-sm">No decisions yet</p>
                <p className="text-xs text-gray-300 mt-1">Click + to log a decision</p>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
