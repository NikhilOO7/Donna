'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Search, Sparkles, X, Loader2, Square, FileText, Send, Volume2, VolumeX } from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import MeetingOrb, { OrbState } from './MeetingOrb';
import NudgeCard from './NudgeCard';
import InsightCanvas from './InsightCanvas';
import AssistantPanel from './AssistantPanel';
import LiveAudioCapture, { type Status as CaptureStatus } from './LiveAudioCapture';

interface Props {
  meeting: any;
  onRefresh: () => void;
}

const NUDGE_LABEL: Record<string, string> = {
  context: 'Found relevant context',
  fact_check: 'Checking a claim',
  decision_prompt: 'Detected a decision',
  activation: 'Your expertise is relevant',
  connection: 'Found a connection',
  memory: 'Recalling a past decision',
  insight: 'Surfacing research',
  agenda: 'Agenda update',
  flow: 'Meeting flow',
};

/**
 * The live meeting screen: one orb, two buttons, and insights that announce
 * themselves and get out of the way.
 *
 * Design intent — during a meeting the user is talking to people, not
 * operating software. The previous view was a dashboard (transcript feed,
 * nudge list, filters, controls) and every element of it competed with the
 * conversation for attention. Here:
 *
 *  - The orb carries state. Idle is warm and still; live is cool and breathing.
 *  - New insights arrive as a toast, then retire into a counter. Nothing
 *    accumulates on screen demanding to be read.
 *  - "Ask" and "Insights" are the only two affordances, and both are
 *    deliberate taps that open a panel over the calm — never inline clutter.
 */
export default function LiveMeetingStage({ meeting, onRefresh }: Props) {
  const [panel, setPanel] = useState<null | 'ask' | 'insights' | 'transcript'>(null);
  const [captureStatus, setCaptureStatus] = useState<CaptureStatus>('idle');
  // The insight currently open in the canvas, plus the trail that led there so
  // following a related card can be walked back.
  const [openInsight, setOpenInsight] = useState<string | null>(null);
  const [insightTrail, setInsightTrail] = useState<string[]>([]);
  // A question handed to the assistant from an insight, consumed on delivery.
  const [askPrompt, setAskPrompt] = useState<string | null>(null);
  const [speaking, setSpeaking] = useState<boolean>(!!meeting.voice_nudges_enabled);
  const [speakingBusy, setSpeakingBusy] = useState(false);

  // useState's initializer runs once, but `meeting` arrives from a fetch after
  // mount — so the toggle initialized from `undefined` (off) and then never
  // resynced. It drifted out of step with the server and sent the wrong value
  // when clicked, which is how spoken nudges ended up disabled while the button
  // still read "Donna speaks up". Skip while a write is in flight so the
  // optimistic value isn't clobbered by a stale refetch.
  useEffect(() => {
    if (speakingBusy) return;
    setSpeaking(!!meeting.voice_nudges_enabled);
  }, [meeting.voice_nudges_enabled, speakingBusy]);
  const [utterance, setUtterance] = useState('');
  const [sending, setSending] = useState(false);
  const [starting, setStarting] = useState(false);
  const [ending, setEnding] = useState(false);
  const [toast, setToast] = useState<any | null>(null);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const seenRef = useRef<Set<string>>(new Set());
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isLive = meeting.status === 'in_progress';
  const isEnded = meeting.status === 'completed';
  const isLeader = meeting.my_role !== 'participant';

  const nudges = useMemo(
    () => (meeting.nudges || []).filter((n: any) => !dismissed.has(n.id)),
    [meeting.nudges, dismissed],
  );

  // Announce genuinely-new insights, once each, then let them retire into the
  // counter. Seeding on first render stops a page refresh mid-meeting from
  // replaying every insight the meeting has ever produced.
  useEffect(() => {
    const incoming = meeting.nudges || [];
    if (seenRef.current.size === 0) {
      incoming.forEach((n: any) => seenRef.current.add(n.id));
      return;
    }
    const fresh = incoming.find((n: any) => !seenRef.current.has(n.id));
    if (!fresh) return;
    incoming.forEach((n: any) => seenRef.current.add(n.id));
    setToast(fresh);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 6000);
  }, [meeting.nudges]);

  useEffect(() => () => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
  }, []);

  const orbState: OrbState = isEnded ? 'ended' : isLive ? (toast ? 'thinking' : 'listening') : 'idle';

  const handleStart = async () => {
    if (!isLeader || starting) return;
    setStarting(true);
    try {
      await apiClient.startMeeting(meeting.id);
      onRefresh();
    } catch (e) {
      console.error('Failed to start meeting:', e);
    } finally {
      setStarting(false);
    }
  };

  const handleEnd = async () => {
    if (!isLeader || ending) return;
    setEnding(true);
    try {
      await apiClient.endMeeting(meeting.id);
      onRefresh();
    } catch (e) {
      console.error('Failed to end meeting:', e);
    } finally {
      setEnding(false);
    }
  };

  // Typing an utterance is how you exercise the agents without a microphone —
  // essential for testing, and the fallback when the voice worker is down.
  const handleSendUtterance = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const text = utterance.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      // No client-side 'You' fallback: that label is relative to whoever is
      // looking, and it gets persisted into a transcript other people read.
      // Sending it empty lets the server attribute it to the authenticated user.
      await apiClient.addUtterance(meeting.id, meeting.my_name || '', text);
      setUtterance('');
      onRefresh();
    } catch (err) {
      console.error('Failed to send utterance:', err);
    } finally {
      setSending(false);
    }
  };

  // Governs UNPROMPTED speech only: fact-checks, decision prompts and
  // high-relevance context, above 0.8, at most once every two minutes.
  // Interrupting a room is expensive, so that bar is deliberately high.
  // Answers to direct questions ignore this entirely — being asked something
  // and staying silent reads as broken, not as configured.
  const handleToggleSpeaking = async () => {
    if (speakingBusy) return;
    const next = !speaking;
    setSpeakingBusy(true);
    setSpeaking(next); // optimistic — the toggle should feel instant
    try {
      await apiClient.toggleVoiceNudges(meeting.id, next);
    } catch (e) {
      console.error('Failed to toggle voice nudges:', e);
      setSpeaking(!next); // roll back so the switch never lies about server state
    } finally {
      setSpeakingBusy(false);
    }
  };

  const handleDismiss = async (id: string) => {
    setDismissed((prev) => new Set(prev).add(id));
    try {
      await apiClient.dismissNudge(meeting.id, id);
    } catch (e) {
      console.error('Dismiss failed:', e);
    }
  };

  const handlePin = async (id: string) => {
    try {
      await apiClient.pinNudge(meeting.id, id);
      onRefresh();
    } catch (e) {
      console.error('Pin failed:', e);
    }
  };

  // A started meeting is not the same as a meeting Donna can hear. Claiming
  // "Listening…" while the microphone is still off is what made a meeting
  // awaiting a click look like one that had hung.
  const micLive = captureStatus === 'live';

  const headline = isEnded
    ? 'Meeting ended'
    : isLive
      ? micLive
        ? 'Listening to your meeting…'
        : 'Turn on your microphone'
      : 'Ready when you are';

  const subhead = isEnded
    ? 'Continue to the summary to capture decisions and action items.'
    : isLive
      ? micLive
        ? 'Donna will surface relevant insights automatically'
        : captureStatus === 'connecting'
          ? 'Connecting to the meeting room…'
          : 'The meeting is running, but Donna cannot hear it yet.'
      : isLeader
        ? 'Tap the orb to start your meeting'
        : 'Waiting for the meeting leader to start';

  return (
    <div className="relative">
      {/* Status bar */}
      <div className="flex items-center justify-between mb-2 text-[11px]">
        <div className="flex items-center gap-2">
          <span className="font-bold tracking-tight text-gray-800">Donna</span>
          <span className="flex items-center gap-1.5 text-gray-400">
            <span
              className={[
                'w-1.5 h-1.5 rounded-full',
                isLive && micLive
                  ? 'bg-emerald-500 animate-pulse'
                  : isEnded
                    ? 'bg-gray-300'
                    : 'bg-amber-400',
              ].join(' ')}
            />
            {isEnded
              ? 'Ended'
              : isLive
                ? micLive
                  ? 'AI Listening'
                  : 'Mic off'
                : 'Standing by'}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setPanel('transcript')}
            className="flex items-center gap-1 text-gray-400 hover:text-gray-700 transition-colors"
          >
            <FileText className="w-3 h-3" />
            Transcript
            {meeting.transcript?.utterance_count > 0 && ` (${meeting.transcript.utterance_count})`}
          </button>
          <button
            onClick={() => setPanel('insights')}
            className="text-gray-400 hover:text-gray-700 transition-colors"
          >
            {nudges.length} insight{nudges.length === 1 ? '' : 's'}
          </button>
        </div>
      </div>

      {/* Stage */}
      <div className="relative rounded-2xl bg-gradient-to-b from-white to-gray-50/60 border border-gray-100 py-14 px-6 min-h-[440px] flex flex-col items-center justify-center">
        <MeetingOrb
          state={orbState}
          onClick={!isLive && !isEnded && isLeader ? handleStart : undefined}
          disabled={starting}
        />

        <div className="mt-9 text-center">
          <h2 className="text-[22px] font-semibold text-gray-900 tracking-tight">
            {starting ? 'Starting…' : headline}
          </h2>
          <p className="text-sm text-gray-500 mt-1.5 max-w-sm mx-auto">{subhead}</p>
        </div>

        {isLive && (
          <div className="mt-8">
            <LiveAudioCapture
              meetingId={meeting.id}
              speakerName={meeting.my_name || ''}
              onStatusChange={setCaptureStatus}
            />

            {/* A real switch, not a label that changes.
              *
              * "Donna speaks up" / "Donna stays silent" described the current
              * state, but a button captioned with a sentence reads as the
              * action it will perform — so the same pixel could mean "she is
              * speaking" or "click to make her speak", and there was no way to
              * tell which. The label is now constant and the switch carries
              * the state, which is the one arrangement that cannot be read
              * both ways. */}
            {isLeader && (
              <button
                role="switch"
                aria-checked={speaking}
                onClick={handleToggleSpeaking}
                disabled={speakingBusy}
                className="mt-5 mx-auto flex items-center gap-2.5 px-3.5 py-2 rounded-full border border-gray-200 bg-white hover:border-gray-300 transition-colors disabled:opacity-60"
                title="Unprompted insights are spoken aloud. Direct questions are always answered, whatever this is set to."
              >
                {speaking ? (
                  <Volume2 className="w-3.5 h-3.5 text-indigo-600" />
                ) : (
                  <VolumeX className="w-3.5 h-3.5 text-gray-400" />
                )}
                <span className="text-xs font-medium text-gray-700">
                  Speak insights aloud
                </span>
                <span
                  className={[
                    'relative w-8 h-[18px] rounded-full transition-colors flex-shrink-0',
                    speaking ? 'bg-indigo-600' : 'bg-gray-300',
                  ].join(' ')}
                >
                  <span
                    className={[
                      'absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white shadow-sm transition-all',
                      speaking ? 'left-[16px]' : 'left-[2px]',
                    ].join(' ')}
                  />
                </span>
                <span
                  className={[
                    'text-[11px] font-semibold w-6 text-left',
                    speaking ? 'text-indigo-600' : 'text-gray-400',
                  ].join(' ')}
                >
                  {speaking ? 'On' : 'Off'}
                </span>
              </button>
            )}
          </div>
        )}

        {isLive && isLeader && (
          <button
            onClick={handleEnd}
            disabled={ending}
            className="mt-7 inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium text-gray-500 hover:text-red-600 border border-gray-200 hover:border-red-200 rounded-full bg-white/80 transition-colors disabled:opacity-50"
          >
            {ending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Square className="w-3 h-3" />}
            End meeting
          </button>
        )}

        {/* Insight toast — announces, then retires into the counter */}
        {toast && (
          <div className="absolute bottom-5 right-5 max-w-[300px] animate-toast-in">
            <button
              onClick={() => { setToast(null); setPanel('insights'); }}
              className="w-full text-left bg-white rounded-xl shadow-lg border border-gray-100 px-3.5 py-3 hover:border-indigo-200 transition-colors"
            >
              <div className="flex items-center gap-1.5 mb-1">
                <Search className="w-3 h-3 text-indigo-500 flex-shrink-0" />
                <span className="text-[11px] font-semibold text-gray-800">
                  {NUDGE_LABEL[toast.type] || 'New insight'}
                </span>
              </div>
              <p className="text-[11.5px] text-gray-500 leading-snug line-clamp-2">
                {toast.title || toast.content}
              </p>
            </button>
          </div>
        )}
      </div>

      {/* The only two affordances */}
      <div className="flex items-center justify-center gap-3 mt-6">
        <button
          onClick={() => setPanel('ask')}
          className="inline-flex items-center gap-2 px-7 py-3 bg-gray-900 hover:bg-black text-white text-sm font-semibold rounded-full shadow-md hover:shadow-lg transition-all active:scale-[0.98]"
        >
          <Sparkles className="w-4 h-4" />
          Ask Donna
        </button>
        <button
          onClick={() => setPanel('insights')}
          className="inline-flex items-center gap-2 px-7 py-3 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-sm font-semibold rounded-full transition-colors active:scale-[0.98]"
        >
          Insights
          {nudges.length > 0 && (
            <span className="min-w-[20px] h-5 px-1.5 grid place-items-center bg-white text-indigo-600 text-[11px] font-bold rounded-full">
              {nudges.length}
            </span>
          )}
        </button>
      </div>

      {/* Slide-over: the detail lives here, never on the stage */}
      {panel && (
        <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
          <div
            className="absolute inset-0 bg-gray-900/20 backdrop-blur-[2px]"
            onClick={() => setPanel(null)}
          />
          <aside className="relative w-full max-w-md bg-white h-full shadow-2xl flex flex-col animate-slide-in">
            <header className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
              <h3 className="font-semibold text-gray-900">
                {panel === 'ask'
                  ? 'Ask Donna'
                  : panel === 'transcript'
                    ? 'Transcript'
                    : `Insights (${nudges.length})`}
              </h3>
              <button
                onClick={() => setPanel(null)}
                className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </header>

            <div className="flex-1 overflow-y-auto">
              {panel === 'ask' ? (
                <div className="h-full">
                  <AssistantPanel
                    meetingId={meeting.id}
                    pendingPrompt={askPrompt}
                    onPromptConsumed={() => setAskPrompt(null)}
                  />
                </div>
              ) : panel === 'transcript' ? (
                <TranscriptPanel
                  meeting={meeting}
                  isLive={isLive}
                  utterance={utterance}
                  setUtterance={setUtterance}
                  sending={sending}
                  onSend={handleSendUtterance}
                />
              ) : nudges.length === 0 ? (
                <div className="text-center py-16 px-6">
                  <div className="w-12 h-12 rounded-2xl bg-gray-100 grid place-items-center mx-auto mb-3">
                    <Sparkles className="w-5 h-5 text-gray-400" />
                  </div>
                  <p className="text-sm text-gray-500">
                    {isLive
                      ? 'Nothing yet — Donna surfaces insights as the conversation gives her something to work with.'
                      : 'Insights appear once the meeting starts.'}
                  </p>
                </div>
              ) : (
                <div className="p-4 space-y-3">
                  {nudges.map((n: any) => (
                    <NudgeCard
                      key={n.id}
                      nudge={n}
                      onDismiss={() => handleDismiss(n.id)}
                      onPin={() => handlePin(n.id)}
                      onOpen={(id) => {
                        setInsightTrail([]);
                        setOpenInsight(id);
                      }}
                    />
                  ))}
                </div>
              )}
            </div>
          </aside>
        </div>
      )}

      {openInsight && (
        <InsightCanvas
          meetingId={meeting.id}
          nudgeId={openInsight}
          onClose={() => {
            setOpenInsight(null);
            setInsightTrail([]);
          }}
          onOpenRelated={(id) => {
            setInsightTrail((prev) => [...prev, openInsight]);
            setOpenInsight(id);
          }}
          onBack={
            insightTrail.length
              ? () => {
                  setOpenInsight(insightTrail[insightTrail.length - 1]);
                  setInsightTrail((prev) => prev.slice(0, -1));
                }
              : undefined
          }
          onAskDonna={(prompt) => {
            setOpenInsight(null);
            setInsightTrail([]);
            setPanel('ask');
            setAskPrompt(prompt);
          }}
          onDismiss={handleDismiss}
          onPin={handlePin}
        />
      )}
    </div>
  );
}


/**
 * Transcript, agenda progress and manual utterance entry.
 *
 * Deliberately behind a tap rather than on the stage: reading a scrolling
 * transcript during a live conversation is precisely the attention tax the
 * orb design exists to remove. But it must remain *reachable* — and the text
 * input is the only way to drive the agents without a working microphone,
 * which makes it the difference between a demo and a testable system.
 */
function TranscriptPanel({ meeting, isLive, utterance, setUtterance, sending, onSend }: any) {
  const utterances = meeting.transcript?.utterances || [];
  const agenda = meeting.agenda || [];
  const covered = agenda.filter((a: any) => a?.status === 'covered').length;

  return (
    <div className="flex flex-col h-full">
      {agenda.length > 0 && (
        <div className="px-4 py-3 border-b border-gray-100 bg-gray-50/60">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-bold uppercase tracking-widest text-gray-400">
              Agenda
            </span>
            <span className="text-[11px] text-gray-500">
              {covered}/{agenda.length} covered
            </span>
          </div>
          <div className="space-y-1">
            {agenda.map((item: any, i: number) => (
              <div key={i} className="flex items-center gap-2 text-[12px]">
                <span
                  className={[
                    'w-1.5 h-1.5 rounded-full flex-shrink-0',
                    item?.status === 'covered' ? 'bg-emerald-500' : 'bg-gray-300',
                  ].join(' ')}
                />
                <span className={item?.status === 'covered' ? 'text-gray-400 line-through' : 'text-gray-600'}>
                  {item.title}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {utterances.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-10">
            Nothing spoken yet.
          </p>
        ) : (
          utterances.map((u: any, i: number) => (
            <div key={i} className="text-sm">
              <span className="font-medium text-gray-900">{u.speaker}</span>
              <p className="text-gray-600 leading-relaxed">{u.text}</p>
            </div>
          ))
        )}
        {meeting.partial_utterance && (
          <div className="text-sm opacity-60">
            <span className="font-medium text-gray-700">{meeting.partial_utterance.speaker}</span>
            <p className="text-gray-500 italic leading-relaxed">
              {meeting.partial_utterance.text}…
            </p>
          </div>
        )}
      </div>

      {isLive && (
        <form onSubmit={onSend} className="p-3 border-t border-gray-100 flex gap-2">
          <input
            value={utterance}
            onChange={(e: any) => setUtterance(e.target.value)}
            placeholder="Type what was said…"
            className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:border-indigo-300"
          />
          <button
            type="submit"
            disabled={sending || !utterance.trim()}
            className="px-3 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-200 text-white rounded-lg transition-colors"
          >
            {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </form>
      )}

    </div>
  );
}
