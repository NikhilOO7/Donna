'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Mic, PhoneOff, Play, MessageSquare, Plus, Send, Sparkles,
  LayoutGrid, Pin, Radio, Download, Check, Volume2, VolumeX,
} from 'lucide-react';
import NudgeCard from './NudgeCard';
import LiveAudioCapture from './LiveAudioCapture';
import AssistantPanel from './AssistantPanel';
import CanvasBoard from './CanvasBoard';
import VoiceSetupWizard from './VoiceSetupWizard';
import { apiClient } from '@/lib/api-client';

interface MeetingRoomProps {
  meeting: any;
  onRefresh: () => void;
}

type Utterance = { speaker: string; text: string; timestamp?: string };
type Mode = 'live' | 'canvas' | 'pinned';

export default function MeetingRoom({ meeting, onRefresh }: MeetingRoomProps) {
  const [mode, setMode] = useState<Mode>('live');
  const [decisionText, setDecisionText] = useState('');
  const [showDecisionForm, setShowDecisionForm] = useState(false);
  // Optimistically hidden nudges (dismissed before the next refetch)
  const [hiddenNudges, setHiddenNudges] = useState<Set<string>>(new Set());
  // "Ask Donna" prompt injected from an insight card
  const [askPrompt, setAskPrompt] = useState<string | null>(null);
  const [exported, setExported] = useState(false);
  const [showVoiceSetup, setShowVoiceSetup] = useState(false);
  // Insight-type filter for the live feed (PDF sidebar "Agents" filter)
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const isLive = meeting.status === 'in_progress';
  const isLeader = meeting.my_role !== 'participant';
  const [voiceNudges, setVoiceNudges] = useState<boolean>(
    Boolean(meeting.voice_nudges_enabled),
  );

  const handleToggleVoiceNudges = async () => {
    const next = !voiceNudges;
    setVoiceNudges(next);
    try {
      await apiClient.toggleVoiceNudges(meeting.id, next);
    } catch {
      setVoiceNudges(!next);
    }
  };

  const visibleNudges = useMemo(
    () =>
      (meeting.nudges || []).filter(
        (n: any) => !n.dismissed_at && !hiddenNudges.has(n.id),
      ),
    [meeting.nudges, hiddenNudges],
  );

  const pinnedNudges = useMemo(
    () => visibleNudges.filter((n: any) => n.pinned_at),
    [visibleNudges],
  );

  const handleDismissNudge = async (nudgeId: string) => {
    setHiddenNudges((prev) => new Set(prev).add(nudgeId));
    try {
      await apiClient.dismissNudge(meeting.id, nudgeId);
    } catch (error) {
      console.error('Failed to dismiss nudge:', error);
      setHiddenNudges((prev) => {
        const next = new Set(prev);
        next.delete(nudgeId);
        return next;
      });
    }
  };

  const handlePinNudge = async (nudgeId: string) => {
    try {
      await apiClient.pinNudge(meeting.id, nudgeId);
      onRefresh();
    } catch (error) {
      console.error('Failed to pin nudge:', error);
    }
  };

  const handleAskDonna = (prompt: string) => {
    setMode('live'); // assistant rail lives in the live layout
    setAskPrompt(prompt);
  };

  const handleExportPinned = async () => {
    const lines = [
      `# Pinned Insights — ${meeting.title}`,
      '',
      ...pinnedNudges.map((n: any) => {
        const src = n.source_data || {};
        const source =
          src.document_title || src.source_title || src.source_url || '';
        return `- **[${n.type}] ${n.title}** — ${n.content}${source ? `\n  - Source: ${source}` : ''}`;
      }),
    ];
    try {
      await navigator.clipboard.writeText(lines.join('\n'));
      setExported(true);
      setTimeout(() => setExported(false), 2000);
    } catch (error) {
      console.error('Copy failed:', error);
    }
  };

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
      onRefresh();
    } catch (error) {
      console.error('Failed to add utterance:', error);
    } finally {
      setSending(false);
    }
  };

  const handleStartMeeting = async () => {
    try {
      await apiClient.startMeeting(meeting.id);
      onRefresh();
    } catch (error) {
      console.error('Failed to start meeting:', error);
    }
  };

  const handleEndMeeting = async () => {
    if (!confirm('End this meeting?')) return;
    try {
      await apiClient.endMeeting(meeting.id);
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

  // Not started yet — the orb screen ("Tap the orb to start your meeting")
  if (!isLive && meeting.status !== 'completed') {
    if (!isLeader) {
      return (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <div className="w-16 h-16 bg-indigo-50 rounded-2xl flex items-center justify-center mb-5">
            <Radio className="w-8 h-8 text-indigo-300" />
          </div>
          <h3 className="text-lg font-semibold text-gray-900 mb-1.5">Waiting for the leader</h3>
          <p className="text-gray-400 text-sm max-w-xs">
            You&apos;re on the shared board for this meeting. It opens as soon as the
            meeting leader starts the session.
          </p>
        </div>
      );
    }
    return (
      <div className="flex flex-col items-center justify-center py-16">
        {showVoiceSetup && (
          <VoiceSetupWizard
            meeting={meeting}
            onClose={() => setShowVoiceSetup(false)}
            onComplete={() => {
              setShowVoiceSetup(false);
              handleStartMeeting();
            }}
          />
        )}
        <button
          onClick={() => setShowVoiceSetup(true)}
          title="Set up voice & participants, then start"
          className="relative group mb-8 focus:outline-none"
        >
          {/* Soft aura */}
          <span className="absolute -inset-8 rounded-full bg-gradient-to-br from-indigo-200/50 via-violet-200/50 to-sky-200/50 blur-2xl group-hover:from-indigo-300/60 group-hover:via-violet-300/60 group-hover:to-sky-300/60 transition-all duration-500" />
          {/* Orb */}
          <span className="relative block w-36 h-36 rounded-full bg-gradient-to-br from-indigo-100 via-violet-100 to-sky-100 border border-white shadow-elevated group-hover:scale-105 group-active:scale-95 transition-transform duration-300">
            <span className="absolute inset-3 rounded-full bg-gradient-to-br from-white/80 to-violet-100/60 backdrop-blur-sm" />
            <span className="absolute inset-0 flex items-center justify-center">
              <Play className="w-8 h-8 text-indigo-500/80 group-hover:text-indigo-600 transition-colors translate-x-0.5" />
            </span>
          </span>
        </button>

        <h3 className="text-xl font-semibold text-gray-900 mb-1.5">Ready when you are</h3>
        <p className="text-gray-400 text-sm mb-6">
          Tap the orb to set up voice &amp; participants, then start your meeting
        </p>

        <button
          onClick={handleStartMeeting}
          className="text-xs text-gray-400 hover:text-gray-600 underline transition-colors mb-6"
        >
          Skip setup — start immediately
        </button>

        <div className="flex items-center gap-2 text-xs text-gray-400">
          <Mic className="w-3.5 h-3.5" />
          Live transcription, insight cards, and decision tracking begin when you start.
        </div>
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

  const modeTab = (m: Mode, label: string, Icon: React.ElementType, badge?: number) => (
    <button
      onClick={() => setMode(m)}
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200 ${
        mode === m
          ? 'bg-indigo-600 text-white shadow-sm'
          : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
      }`}
    >
      <Icon className="w-3.5 h-3.5" />
      {label}
      {badge !== undefined && badge > 0 && (
        <span className={`px-1.5 rounded-full text-[10px] font-semibold ${
          mode === m ? 'bg-white/20 text-white' : 'bg-emerald-100 text-emerald-700'
        }`}>
          {badge}
        </span>
      )}
    </button>
  );

  // Live meeting — Donna Meeting Assistant (PDF layout)
  return (
    <div className="space-y-4">
      {/* Header: brand + mode tabs + Donna Active + controls */}
      <div className="bg-white rounded-xl border border-gray-200/60 shadow-card px-4 py-3 flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-600 to-violet-600 flex items-center justify-center shadow-sm">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold text-gray-900 text-sm">
            Donna Meeting Assistant
          </span>
          <div className="flex items-center gap-1 bg-gray-50 border border-gray-200/60 rounded-xl p-1">
            {modeTab('live', 'Live Mode', Radio)}
            {modeTab('canvas', 'Canvas', LayoutGrid)}
            {modeTab('pinned', 'Pinned', Pin, pinnedNudges.length)}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5 text-xs font-medium text-emerald-600">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
            </span>
            Donna Active
          </span>
          {isLeader && (
            <button
              onClick={handleToggleVoiceNudges}
              title={voiceNudges ? 'Donna speaks high-signal nudges — click to mute' : 'Let Donna speak high-signal nudges aloud'}
              className={`p-2.5 rounded-xl border transition-all duration-200 ${
                voiceNudges
                  ? 'bg-violet-50 border-violet-200 text-violet-600'
                  : 'bg-white border-gray-200 text-gray-400 hover:text-gray-600'
              }`}
            >
              {voiceNudges ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
            </button>
          )}
          <LiveAudioCapture meetingId={meeting.id} speakerName={speaker || 'You'} />
          {isLeader && (
          <button
            onClick={handleEndMeeting}
            className="flex items-center gap-2 px-3.5 py-2 bg-red-500 text-white rounded-xl hover:bg-red-600 transition-all duration-200 shadow-sm active:scale-[0.97]"
          >
            <PhoneOff className="w-4 h-4" />
            <span className="text-sm font-medium">End</span>
          </button>
          )}
        </div>
      </div>

      {/* ---- CANVAS MODE ---- */}
      {mode === 'canvas' && (
        <div className="space-y-2">
          <p className="text-xs text-gray-400 px-1">
            Spatial arrangement of insights — drag cards to cluster related thinking.
          </p>
          <CanvasBoard
            meetingId={meeting.id}
            nudges={visibleNudges}
            onPin={isLeader ? handlePinNudge : undefined}
            onDismiss={isLeader ? handleDismissNudge : undefined}
            serverPositions={meeting.canvas_positions || {}}
            onPersist={
              isLeader
                ? (positions) => {
                    apiClient.updateCanvas(meeting.id, positions).catch(() => {});
                  }
                : undefined
            }
          />
        </div>
      )}

      {/* ---- PINNED MODE ---- */}
      {mode === 'pinned' && (
        <div className="bg-gradient-to-b from-gray-50 to-white rounded-xl border border-gray-200/60 shadow-card overflow-hidden">
          <div className="px-5 py-3.5 border-b border-gray-100 bg-gradient-to-r from-indigo-50/50 to-white flex items-center justify-between">
            <h3 className="text-xs font-bold text-indigo-600 uppercase tracking-wider">
              Pinned Insights ({pinnedNudges.length})
            </h3>
            <button
              onClick={handleExportPinned}
              disabled={pinnedNudges.length === 0}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-200 disabled:text-gray-400 text-white text-xs font-medium rounded-lg transition-colors"
            >
              {exported ? <Check className="w-3.5 h-3.5" /> : <Download className="w-3.5 h-3.5" />}
              {exported ? 'Copied!' : 'Export Summary'}
            </button>
          </div>
          <div className="p-4 min-h-[300px]">
            {pinnedNudges.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {pinnedNudges.map((nudge: any) => (
                  <NudgeCard
                    key={nudge.id}
                    nudge={nudge}
                    onLogDecision={isLeader ? (nudgeId, content) => handleAddDecision(content, nudgeId) : undefined}
                    onDismiss={isLeader ? handleDismissNudge : undefined}
                    onPin={isLeader ? handlePinNudge : undefined}
                    onAskDonna={handleAskDonna}
                  />
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-full text-gray-400 py-10">
                <Pin className="w-8 h-8 text-gray-200 mb-3" />
                <p className="text-sm font-medium text-gray-500">No pinned insights yet</p>
                <p className="text-xs text-gray-300 mt-1 text-center max-w-[240px]">
                  Pin the cards you want to keep — they get prominence in the summary.
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ---- AGENDA PROGRESS (PDF: agenda tracking) ---- */}
      {mode === 'live' && (meeting.agenda?.length || 0) > 0 && (
        <div className="bg-white rounded-xl border border-gray-200/60 shadow-card px-4 py-2.5 flex items-center gap-3 flex-wrap">
          <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wider flex-shrink-0">
            Agenda{' '}
            <span className="text-indigo-600">
              {meeting.agenda.filter((a: any) => a?.status === 'covered').length}/{meeting.agenda.length}
            </span>
          </span>
          <div className="flex items-center gap-1.5 flex-wrap">
            {meeting.agenda.map((item: any, i: number) => {
              const covered = item?.status === 'covered';
              const title = typeof item === 'string' ? item : item?.title;
              return (
                <span
                  key={i}
                  className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border transition-colors ${
                    covered
                      ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                      : 'bg-gray-50 border-gray-200 text-gray-500'
                  }`}
                >
                  {covered ? (
                    <Check className="w-3 h-3" />
                  ) : (
                    <span className="w-1.5 h-1.5 rounded-full bg-gray-300" />
                  )}
                  {title}
                </span>
              );
            })}
          </div>
        </div>
      )}

      {/* ---- LIVE MODE: Transcript | Live Insights Feed | Assistant + Decisions ---- */}
      {mode === 'live' && (
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.3fr_1fr] gap-4">
          {/* Transcript Panel */}
          <div className="bg-white rounded-xl border border-gray-200/60 shadow-card overflow-hidden flex flex-col min-h-[420px]">
            <div className="px-4 py-3.5 border-b border-gray-100 bg-gradient-to-r from-gray-50 to-white flex items-center justify-between">
              <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">
                Live Transcript
              </h3>
              <span className="text-[11px] text-gray-400">
                {transcriptUtterances.length} {transcriptUtterances.length === 1 ? 'utterance' : 'utterances'}
              </span>
            </div>

            <div
              ref={scrollRef}
              className="flex-1 overflow-y-auto px-4 py-3 space-y-2.5 max-h-[480px]"
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
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="font-semibold text-[#4f46e5]">{u.speaker}</span>
                      {u.timestamp && (
                        <span className="text-[10px] text-gray-300 flex-shrink-0">
                          {new Date(u.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      )}
                    </div>
                    <span className="text-gray-700">{u.text}</span>
                  </div>
                ))
              )}
              {/* Ghost text: live speech that hasn't finalized yet */}
              {meeting.partial_utterance?.text && (
                <div className="px-3 py-2 rounded-lg bg-indigo-50/40 border border-dashed border-indigo-100 text-sm">
                  <span className="font-semibold text-indigo-300">
                    {meeting.partial_utterance.speaker}
                  </span>
                  <span className="text-gray-400 italic ml-2">
                    {meeting.partial_utterance.text}
                    <span className="animate-pulse">▍</span>
                  </span>
                </div>
              )}
            </div>

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

          {/* Live Insights Feed */}
          <div className="bg-gradient-to-b from-gray-50 to-white rounded-xl border border-gray-200/60 shadow-card overflow-hidden flex flex-col">
            <div className="px-4 py-3 border-b border-gray-100 bg-gradient-to-r from-primary-50/50 to-white">
              <h3 className="text-xs font-bold text-primary-600 uppercase tracking-wider mb-2">
                {isLeader ? 'Live Insights Feed' : 'Shared Board'}
              </h3>
              <div className="flex items-center gap-1 flex-wrap">
                {[
                  { key: null, label: 'All', dot: 'bg-gray-400' },
                  { key: 'insight', label: 'Insight', dot: 'bg-amber-400' },
                  { key: 'context', label: 'Context', dot: 'bg-blue-400' },
                  { key: 'fact_check', label: 'Fact Check', dot: 'bg-emerald-400' },
                  { key: 'decision_prompt', label: 'Decision', dot: 'bg-violet-400' },
                  { key: 'knowledge_graph', label: 'Connection', dot: 'bg-indigo-400' },
                  { key: 'activation', label: 'Expertise', dot: 'bg-teal-400' },
                  { key: 'agenda', label: 'Agenda', dot: 'bg-rose-400' },
                ].map((f) => (
                  <button
                    key={f.label}
                    onClick={() => setTypeFilter(f.key)}
                    className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium border transition-colors ${
                      typeFilter === f.key
                        ? 'bg-white border-indigo-200 text-indigo-700 shadow-sm'
                        : 'border-transparent text-gray-400 hover:text-gray-600 hover:bg-white/60'
                    }`}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full ${f.dot}`} />
                    {f.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="p-4 flex-1 overflow-y-auto max-h-[540px] min-h-[350px]">
              {visibleNudges.length > 0 ? (
                <div className="space-y-3">
                  {visibleNudges
                    .filter((n: any) => !typeFilter || n.type === typeFilter)
                    .map((nudge: any) => (
                    <NudgeCard
                      key={nudge.id}
                      nudge={nudge}
                      onLogDecision={isLeader ? (nudgeId, content) => handleAddDecision(content, nudgeId) : undefined}
                      onDismiss={isLeader ? handleDismissNudge : undefined}
                      onPin={isLeader ? handlePinNudge : undefined}
                      onAskDonna={handleAskDonna}
                    />
                  ))}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center h-full text-gray-400">
                  <div className="w-12 h-12 bg-primary-50 rounded-xl flex items-center justify-center mb-3">
                    <MessageSquare className="w-6 h-6 text-primary-300" />
                  </div>
                  <p className="text-sm font-medium text-gray-500">Donna&apos;s listening</p>
                  <p className="text-xs text-gray-300 mt-1 text-center max-w-[200px]">
                    She&apos;ll jump in the moment something matters — a fact to check, a decision to log, a connection you should know.
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Right rail: Assistant + Decisions */}
          <div className="flex flex-col gap-4 min-h-[420px]">
            <div className="h-[330px]">
              <AssistantPanel
                meetingId={meeting.id}
                pendingPrompt={askPrompt}
                onPromptConsumed={() => setAskPrompt(null)}
              />
            </div>

            {/* Decisions Panel */}
            <div className="bg-white rounded-xl border border-gray-200/60 shadow-card overflow-hidden flex-1">
              <div className="px-4 py-3 border-b border-gray-100 bg-gradient-to-r from-emerald-50/50 to-white flex items-center justify-between">
                <h3 className="text-xs font-bold text-emerald-600 uppercase tracking-wider">
                  Decisions & Actions
                </h3>
                {isLeader && (
                <button
                  onClick={() => setShowDecisionForm(true)}
                  className="p-1.5 bg-emerald-100 text-emerald-600 rounded-lg hover:bg-emerald-200 transition-colors"
                >
                  <Plus className="w-3.5 h-3.5" />
                </button>
                )}
              </div>
              <div className="p-3 overflow-y-auto max-h-[280px]">
                {showDecisionForm && (
                  <div className="mb-3 p-3 bg-emerald-50 rounded-xl border border-emerald-100 animate-fade-up">
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
                          <button
                            onClick={
                              isLeader
                                ? async () => {
                                    const next =
                                      d.status === 'pending' ? 'in_progress'
                                      : d.status === 'in_progress' ? 'done'
                                      : 'pending';
                                    try {
                                      await apiClient.updateDecisionStatus(meeting.id, d.id, next);
                                      onRefresh();
                                    } catch (err) {
                                      console.error('Status update failed:', err);
                                    }
                                  }
                                : undefined
                            }
                            disabled={!isLeader}
                            title={isLeader ? 'Click to advance status' : undefined}
                            className={`px-1.5 py-0.5 rounded font-medium ${
                              d.status === 'done'
                                ? 'bg-emerald-100 text-emerald-700'
                                : d.status === 'in_progress'
                                  ? 'bg-amber-100 text-amber-700'
                                  : 'bg-gray-100 text-gray-600'
                            } ${isLeader ? 'cursor-pointer hover:ring-1 hover:ring-gray-300' : ''}`}
                          >
                            {d.status}
                          </button>
                        </div>
                        {d.context && (
                          <div className="mt-2 pl-2.5 border-l-2 border-emerald-300/60">
                            <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-600/70 mb-1">
                              Conversation trigger
                            </p>
                            {d.context.split('\n').map((line: string, i: number) => (
                              <p key={i} className="text-[11px] text-gray-500 italic leading-relaxed">
                                {line}
                              </p>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                ) : !showDecisionForm ? (
                  <div className="flex flex-col items-center justify-center text-gray-400 py-8">
                    <p className="text-sm">No decisions yet</p>
                    <p className="text-xs text-gray-300 mt-1">Click + to log a decision</p>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
