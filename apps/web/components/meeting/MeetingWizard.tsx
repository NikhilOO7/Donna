'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  ArrowLeft, ArrowRight, Calendar, Users, Search, Mic, FileText, FolderOpen,
  Loader2, AlertTriangle, Send, Mail, CheckCircle2, SkipForward,
} from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import WizardStepper, { WizardStepMeta, WizardStepState } from './WizardStepper';
import KnowledgeBaseStep from './KnowledgeBaseStep';
import ResearchBriefView from './ResearchBriefView';
import LiveMeetingStage from './LiveMeetingStage';
import AssistantPanel from './AssistantPanel';

interface Props {
  meetingId: string;
  onBack: () => void;
}

const STEP_KB = 0;
const STEP_RESEARCH = 1;
const STEP_LIVE = 2;
const STEP_SUMMARY = 3;

// Summary generation is a background job over the full transcript, decisions,
// pinned cards and research — tens of seconds, not the ~20ms the POST takes to
// acknowledge it. Poll for it rather than guessing a fixed delay.
const SUMMARY_POLL_MS = 2500;
const SUMMARY_TIMEOUT_MS = 150_000;

/**
 * The meeting journey, one screen at a time.
 *
 * Replaces the accordion in which all four phases lived on a single page. The
 * problem with the accordion was not density — it was that nothing told the
 * user what to do next. Four collapsible panels of equal weight present four
 * equally-plausible actions; a wizard presents one.
 *
 * Rules this follows:
 *  - One step fills the screen. The rail shows where you are and what's left.
 *  - Forward movement is *soft-gated*: documents and research are genuinely
 *    optional, so those steps offer "Skip for now" rather than blocking.
 *    Only the summary is hard-locked, because it cannot exist before the
 *    meeting has ended.
 *  - Completed steps stay reachable. Journeys allow going back.
 *  - The system auto-advances on real state changes (meeting goes live, or
 *    ends), because at that moment the user's task has genuinely changed.
 */
export default function MeetingWizard({ meetingId, onBack }: Props) {
  const [meeting, setMeeting] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [step, setStep] = useState<number>(STEP_KB);
  // Set once the user (or the system) has moved deliberately, so background
  // refreshes never yank the screen out from under someone mid-task.
  const [userNavigated, setUserNavigated] = useState(false);

  const [researchLoading, setResearchLoading] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [emailSending, setEmailSending] = useState(false);
  const [emailSent, setEmailSent] = useState(false);
  const [researchAsk, setResearchAsk] = useState<string | null>(null);
  const [showResearchChat, setShowResearchChat] = useState(false);
  const [cost, setCost] = useState<any>(null);
  const [outreach, setOutreach] = useState<string | null>(null);

  const fetchMeeting = useCallback(async () => {
    try {
      const data = await apiClient.getMeeting(meetingId);
      setMeeting(data);
      return data;
    } catch (err) {
      console.error('Failed to load meeting:', err);
      return null;
    } finally {
      setLoading(false);
    }
  }, [meetingId]);

  // Land the user on the step that matches reality — but only before they
  // start steering themselves.
  useEffect(() => {
    if (!meeting || userNavigated) return;
    if (meeting.status === 'completed') setStep(STEP_SUMMARY);
    else if (meeting.status === 'in_progress') setStep(STEP_LIVE);
    else if (meeting.research?.status) setStep(STEP_RESEARCH);
  }, [meeting, userNavigated]);

  useEffect(() => {
    fetchMeeting();

    const cleanupWS = apiClient.connectMeetingWS(meetingId, (msg) => {
      if (msg.type === 'nudge_created' && msg.nudge) {
        setMeeting((prev: any) => {
          if (!prev) return prev;
          if (prev.my_role === 'participant') {
            const sd = msg.nudge.source_data || {};
            const email = (sd.person_email || '').toLowerCase();
            const person = (sd.person || '').toLowerCase();
            // Addressed by email; name only as a fallback for legacy nudges.
            const mine =
              msg.nudge.type === 'activation' &&
              (email
                ? !!prev.my_email && email === prev.my_email.toLowerCase()
                : !!prev.my_name && person === prev.my_name.toLowerCase());
            if (!mine) return prev;
          }
          const existing = prev.nudges || [];
          if (existing.some((n: any) => n.id === msg.nudge.id)) return prev;
          return { ...prev, nudges: [msg.nudge, ...existing] };
        });
      } else if (msg.type === 'utterance_partial' && msg.text) {
        setMeeting((prev: any) =>
          prev ? { ...prev, partial_utterance: { speaker: msg.speaker, text: msg.text } } : prev,
        );
      } else if (msg.type === 'flow_update' && Array.isArray(msg.talk_time)) {
        setMeeting((prev: any) => (prev ? { ...prev, talk_time: msg.talk_time } : prev));
      } else if (msg.type === 'agenda_progress' && Array.isArray(msg.agenda)) {
        setMeeting((prev: any) => (prev ? { ...prev, agenda: msg.agenda } : prev));
      } else if (msg.type === 'canvas_updated' && msg.positions) {
        setMeeting((prev: any) => (prev ? { ...prev, canvas_positions: msg.positions } : prev));
      } else if (msg.type === 'utterance_added' && msg.utterance) {
        setMeeting((prev: any) => {
          if (!prev) return prev;
          const t = prev.transcript || { utterances: [], utterance_count: 0 };
          return {
            ...prev,
            partial_utterance: null,
            transcript: {
              ...t,
              utterances: [...(t.utterances || []), msg.utterance],
              utterance_count: msg.utterance_count ?? (t.utterance_count || 0) + 1,
            },
          };
        });
      }
    });

    apiClient.getMeetingCost(meetingId).then(setCost).catch(() => {});
    const interval = setInterval(fetchMeeting, 30000);
    return () => {
      clearInterval(interval);
      cleanupWS();
    };
  }, [fetchMeeting, meetingId]);

  const goTo = (n: number) => {
    setUserNavigated(true);
    setStep(n);
    // A new screen starts at the top — carrying scroll across steps makes the
    // transition feel like a jump rather than a move.
    if (typeof window !== 'undefined') window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleRunResearch = async () => {
    // Guard re-entry. The POST returns in ~20ms but the pipeline runs for a
    // minute or more, so without this a user who sees no immediate change
    // clicks again and queues duplicate jobs.
    if (researchLoading) return;
    setResearchLoading(true);
    try {
      await apiClient.triggerResearch(meetingId);
      // Hold the loading state until the refetch actually lands. Clearing it
      // as soon as the POST resolves would drop the UI straight back to the
      // previous (failed) state, which reads as "the button did nothing".
      await new Promise((r) => setTimeout(r, 1500));
      await fetchMeeting();
    } catch (err) {
      console.error('Research failed:', err);
    } finally {
      setResearchLoading(false);
    }
  };

  const handleGenerateSummary = async () => {
    // Generation runs as a background task, so the POST returns in
    // milliseconds while the work takes tens of seconds. Clearing the loading
    // state when the POST resolved dropped the spinner instantly and put the
    // "Generate the summary" screen straight back — the button looked dead,
    // and the single refetch three seconds later almost always ran before the
    // summary existed. The only way to see it was a manual page refresh.
    //
    // So: hold the loading state and poll until the summary actually lands.
    if (summaryLoading) return;
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      const res = await apiClient.generateSummary(meetingId);

      // Already generated — nothing to wait for.
      if (res?.status === 'already_exists') {
        await fetchMeeting();
        return;
      }

      const deadline = Date.now() + SUMMARY_TIMEOUT_MS;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, SUMMARY_POLL_MS));
        const data = await fetchMeeting();
        if (data?.summary) return;
      }

      // Bounded rather than indefinite: a spinner with no end is worse than an
      // honest message telling you the work may still be running.
      setSummaryError(
        'This is taking longer than expected. The summary may still be generating — reload in a moment.',
      );
    } catch (err) {
      console.error('Summary generation failed:', err);
      setSummaryError('Could not generate the summary. Try again in a moment.');
    } finally {
      setSummaryLoading(false);
    }
  };

  const handleSendEmail = async () => {
    setEmailSending(true);
    try {
      await apiClient.sendSummaryEmail(meetingId);
      setEmailSent(true);
      fetchMeeting();
    } catch (err) {
      console.error('Email send failed:', err);
    } finally {
      setEmailSending(false);
    }
  };

  const handleActionStatusCycle = async (item: any) => {
    const next =
      item.status === 'open' ? 'in_progress' : item.status === 'in_progress' ? 'done' : 'open';
    try {
      await apiClient.updateActionItemStatus(meetingId, item.id, next);
      fetchMeeting();
    } catch (err) {
      console.error('Action item status update failed:', err);
    }
  };

  const handleOutreach = async (kind: 'invite' | 'preread' | 'followups' | 'ics') => {
    setOutreach(kind);
    try {
      if (kind === 'invite') await apiClient.sendInvites(meetingId);
      else if (kind === 'preread') await apiClient.sendPreread(meetingId);
      else if (kind === 'followups') await apiClient.sendFollowups(meetingId);
      else await apiClient.downloadCalendar(meetingId);
    } catch (err) {
      console.error(`${kind} failed:`, err);
    } finally {
      setTimeout(() => setOutreach(null), 1500);
    }
  };

  // ---- derived state -----------------------------------------------------
  const hasResearch = meeting?.research?.status === 'completed';
  const isResearching = meeting?.research?.status === 'researching';
  const researchFailed = meeting?.research?.status === 'failed';
  const hasSummary = !!meeting?.summary;
  const isLive = meeting?.status === 'in_progress';
  const isEnded = meeting?.status === 'completed';
  const isLeader = meeting?.my_role !== 'participant';
  const docCount = meeting?.documents?.length ?? 0;

  const steps: WizardStepMeta[] = useMemo(() => {
    const state = (id: number): WizardStepState => {
      if (id === step) return 'current';
      switch (id) {
        case STEP_KB:
          return docCount > 0 ? 'done' : 'available';
        case STEP_RESEARCH:
          return hasResearch ? 'done' : 'available';
        case STEP_LIVE:
          return isEnded ? 'done' : 'available';
        case STEP_SUMMARY:
          // The only genuine lock: a summary cannot exist before the meeting ends.
          return hasSummary ? 'done' : isEnded ? 'available' : 'locked';
        default:
          return 'available';
      }
    };

    return [
      {
        id: STEP_KB,
        title: 'Knowledge Base',
        hint: 'Give Donna the documents this meeting is about',
        status: state(STEP_KB),
        statusLabel: docCount > 0 ? `${docCount} document${docCount === 1 ? '' : 's'}` : 'optional',
        icon: <FolderOpen className="w-5 h-5" />,
      },
      {
        id: STEP_RESEARCH,
        title: 'Research',
        hint: 'Brief the room before anyone walks in',
        status: state(STEP_RESEARCH),
        statusLabel: hasResearch
          ? `${meeting?.research?.source_count ?? 0} sources`
          : isResearching
            ? 'running…'
            : researchFailed
              ? 'failed'
              : 'optional',
        icon: <Search className="w-5 h-5" />,
      },
      {
        id: STEP_LIVE,
        title: 'Live Meeting',
        hint: 'Voice, transcript, and live nudge cards',
        status: state(STEP_LIVE),
        statusLabel: isEnded ? 'ended' : isLive ? 'live now' : 'not started',
        icon: <Mic className="w-5 h-5" />,
      },
      {
        id: STEP_SUMMARY,
        title: 'Summary',
        hint: 'Decisions, action items, and follow-up email',
        status: state(STEP_SUMMARY),
        statusLabel: hasSummary ? 'ready' : isEnded ? 'ready to generate' : 'after the meeting',
        icon: <FileText className="w-5 h-5" />,
        lockedReason: 'Available once the meeting has ended',
      },
    ];
  }, [step, docCount, hasResearch, isResearching, researchFailed, isLive, isEnded, hasSummary, meeting]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-4 border-primary-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!meeting) {
    return (
      <div className="text-center py-16">
        <AlertTriangle className="w-12 h-12 text-red-500 mx-auto mb-3" />
        <p className="text-red-600">Meeting not found</p>
        <button onClick={onBack} className="mt-4 text-primary-600 hover:underline">Back</button>
      </div>
    );
  }

  const current = steps[step];
  const canGoBack = step > STEP_KB;
  const nextStep = steps[step + 1];
  const canGoNext = !!nextStep && nextStep.status !== 'locked';

  // "Skip" vs "Continue": on optional steps that the user hasn't completed,
  // the honest label is skip — pretending it's completion is a small lie the
  // user will notice on the summary screen.
  const stepIsSatisfied =
    (step === STEP_KB && docCount > 0) ||
    (step === STEP_RESEARCH && hasResearch) ||
    (step === STEP_LIVE && isEnded) ||
    step === STEP_SUMMARY;

  return (
    <div>
      {/* ---- Meeting header ---- */}
      <div className="mb-6">
        <button
          onClick={onBack}
          className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 mb-3"
        >
          <ArrowLeft className="w-4 h-4" />
          All Meetings
        </button>

        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-2xl font-bold text-gray-900">{meeting.title}</h1>
          {meeting.meeting_type && (
            <span className="px-2.5 py-1 bg-indigo-50 text-indigo-600 border border-indigo-100 rounded-full text-xs font-medium">
              {meeting.meeting_type}
            </span>
          )}
          {isLive && (
            <span className="flex items-center gap-1.5 px-2.5 py-1 bg-red-50 text-red-600 border border-red-100 rounded-full text-xs font-semibold">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
              LIVE
            </span>
          )}
        </div>

        <div className="flex items-center gap-4 mt-2 text-sm text-gray-500 flex-wrap">
          {meeting.scheduled_at && (
            <span className="flex items-center gap-1">
              <Calendar className="w-4 h-4" />
              {new Date(meeting.scheduled_at).toLocaleString()}
            </span>
          )}
          {meeting.attendees?.length > 0 && (
            <span className="flex items-center gap-1">
              <Users className="w-4 h-4" />
              {meeting.attendees.length} attendees
            </span>
          )}
          {isLeader && cost && cost.total_tokens > 0 && (
            <span
              className="px-2 py-0.5 bg-gray-100 border border-gray-200 rounded-full text-xs text-gray-500"
              title={`${cost.calls} LLM calls · ${cost.total_tokens.toLocaleString()} tokens`}
            >
              AI cost ≈ ${cost.estimated_usd.toFixed(2)}
            </span>
          )}
        </div>
      </div>

      {/* ---- Progress rail ---- */}
      <WizardStepper steps={steps} onSelect={goTo} />

      {/* ---- The one screen ---- */}
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden animate-fade-up">
        <div className="px-6 sm:px-8 py-5 border-b border-gray-100 bg-gradient-to-r from-gray-50/80 to-white">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-500 text-white grid place-items-center shadow-sm flex-shrink-0">
              {current.icon}
            </div>
            <div className="min-w-0">
              <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-indigo-500">
                Step {step + 1} of {steps.length}
              </div>
              <h2 className="text-lg font-bold text-gray-900 leading-tight">{current.title}</h2>
              <p className="text-sm text-gray-500 mt-0.5">{current.hint}</p>
            </div>
          </div>
        </div>

        <div className="px-6 sm:px-8 py-6 min-h-[380px]">
          {step === STEP_KB && (
            <KnowledgeBaseScreen meetingId={meetingId} isLeader={isLeader} />
          )}

          {step === STEP_RESEARCH && (
            <ResearchScreen
              meeting={meeting}
              meetingId={meetingId}
              isLeader={isLeader}
              hasResearch={hasResearch}
              isResearching={isResearching}
              researchFailed={researchFailed}
              researchLoading={researchLoading}
              onRunResearch={handleRunResearch}
              outreach={outreach}
              onOutreach={handleOutreach}
              showResearchChat={showResearchChat}
              researchAsk={researchAsk}
              onDiscuss={(prompt: string) => {
                setShowResearchChat(true);
                setResearchAsk(prompt);
              }}
              onPromptConsumed={() => setResearchAsk(null)}
            />
          )}

          {step === STEP_LIVE && (
            <LiveMeetingStage meeting={meeting} onRefresh={fetchMeeting} />
          )}

          {step === STEP_SUMMARY && (
            <SummaryScreen
              meeting={meeting}
              isLeader={isLeader}
              hasSummary={hasSummary}
              isEnded={isEnded}
              summaryLoading={summaryLoading}
              summaryError={summaryError}
              onGenerate={handleGenerateSummary}
              emailSending={emailSending}
              emailSent={emailSent}
              onSendEmail={handleSendEmail}
              outreach={outreach}
              onOutreach={handleOutreach}
              onActionStatusCycle={handleActionStatusCycle}
            />
          )}
        </div>

        {/* ---- Journey controls ---- */}
        <div className="px-6 sm:px-8 py-4 border-t border-gray-100 bg-gray-50/60 flex items-center justify-between gap-3">
          <button
            onClick={() => canGoBack && goTo(step - 1)}
            disabled={!canGoBack}
            className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-gray-600 rounded-lg hover:bg-white hover:text-gray-900 disabled:opacity-0 disabled:pointer-events-none transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Back
          </button>

          {nextStep ? (
            <div className="flex items-center gap-2">
              {!canGoNext && (
                <span className="text-xs text-gray-400">{nextStep.lockedReason}</span>
              )}
              <button
                onClick={() => canGoNext && goTo(step + 1)}
                disabled={!canGoNext}
                className={[
                  'inline-flex items-center gap-1.5 px-5 py-2.5 text-sm font-semibold rounded-xl transition-all duration-200 active:scale-[0.98]',
                  canGoNext
                    ? stepIsSatisfied
                      ? 'bg-indigo-600 hover:bg-indigo-700 text-white shadow-md hover:shadow-lg'
                      : 'bg-white border border-gray-200 text-gray-600 hover:border-indigo-300 hover:text-indigo-600'
                    : 'bg-gray-100 text-gray-400 cursor-not-allowed',
                ].join(' ')}
              >
                {stepIsSatisfied ? (
                  <>
                    Continue to {nextStep.title}
                    <ArrowRight className="w-4 h-4" />
                  </>
                ) : (
                  <>
                    <SkipForward className="w-4 h-4" />
                    Skip for now
                  </>
                )}
              </button>
            </div>
          ) : (
            <span className="text-xs text-gray-400">You&apos;ve reached the end of the journey</span>
          )}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Step screens                                                        */
/* ------------------------------------------------------------------ */

function KnowledgeBaseScreen({ meetingId, isLeader }: { meetingId: string; isLeader: boolean }) {
  if (!isLeader) {
    return (
      <EmptyState
        icon={<FolderOpen className="w-7 h-7 text-gray-400" />}
        title="Managed by the meeting leader"
        body="Documents attached to this meeting are uploaded by whoever created it."
      />
    );
  }
  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600 max-w-2xl">
        Anything you upload here is attached to this meeting, and Donna ranks it{' '}
        <span className="font-medium text-gray-900">ahead of your general knowledge base</span> when
        she pulls context during the conversation. This step is optional — skip it if the meeting
        doesn&apos;t have supporting material.
      </p>
      <KnowledgeBaseStep meetingId={meetingId} />
    </div>
  );
}

function ResearchScreen(props: any) {
  const {
    meeting, meetingId, isLeader, hasResearch, isResearching, researchFailed,
    researchLoading, onRunResearch, outreach, onOutreach, showResearchChat,
    researchAsk, onDiscuss, onPromptConsumed,
  } = props;

  if (hasResearch && meeting.research) {
    return (
      <div className="space-y-5">
        {isLeader && (
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => onOutreach('preread')}
              disabled={outreach === 'preread'}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white text-xs font-medium rounded-lg transition-colors"
            >
              <Mail className="w-3.5 h-3.5" />
              {outreach === 'preread' ? 'Sent!' : 'Send pre-read to attendees'}
            </button>
            <button
              onClick={() => onOutreach('invite')}
              disabled={outreach === 'invite'}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-gray-200 hover:border-indigo-300 text-gray-600 text-xs font-medium rounded-lg transition-colors"
            >
              <Users className="w-3.5 h-3.5" />
              {outreach === 'invite' ? 'Invites sent!' : 'Email invites'}
            </button>
            <button
              onClick={() => onOutreach('ics')}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-gray-200 hover:border-indigo-300 text-gray-600 text-xs font-medium rounded-lg transition-colors"
            >
              <Calendar className="w-3.5 h-3.5" />
              Add to calendar (.ics)
            </button>
          </div>
        )}
        <ResearchBriefView
          research={meeting.research}
          onDiscuss={(prompt: string) => onDiscuss(prompt)}
        />
        {showResearchChat && (
          <div className="h-[380px] animate-fade-up">
            <AssistantPanel
              meetingId={meetingId}
              pendingPrompt={researchAsk}
              onPromptConsumed={onPromptConsumed}
            />
          </div>
        )}
      </div>
    );
  }

  // researchLoading is included so the switch to this screen is immediate on
  // click, rather than waiting for the server round-trip to report the new
  // status. Otherwise the first second and a half looks like a dead button.
  if (isResearching || researchLoading) {
    return (
      <div className="max-w-lg mx-auto py-10 text-center">
        <div className="w-14 h-14 rounded-2xl bg-amber-100 grid place-items-center mx-auto mb-4">
          <Loader2 className="w-7 h-7 text-amber-600 animate-spin" />
        </div>
        <h3 className="text-lg font-semibold text-gray-900 mb-2">Research is running</h3>
        <p className="text-sm text-gray-500 mb-5">
          Extracting topics, searching the web, validating sources by credibility tier, then
          synthesizing a brief. This usually takes a minute or two.
        </p>
        <div className="w-full bg-amber-100 rounded-full h-1.5 overflow-hidden">
          <div className="bg-amber-500 h-1.5 rounded-full animate-pulse" style={{ width: '55%' }} />
        </div>
        <p className="text-xs text-gray-400 mt-4">
          You can move on — the brief will be here when it&apos;s done.
        </p>
      </div>
    );
  }

  if (researchFailed) {
    return (
      <div className="max-w-lg mx-auto py-10 text-center">
        <div className="w-14 h-14 rounded-2xl bg-red-100 grid place-items-center mx-auto mb-4">
          <AlertTriangle className="w-7 h-7 text-red-600" />
        </div>
        <h3 className="text-lg font-semibold text-gray-900 mb-2">Research didn&apos;t complete</h3>
        <p className="text-sm text-gray-500 mb-5">
          {meeting.research?.executive_summary ||
            'The research pipeline failed. This is usually a missing EXA_API_KEY or an exhausted API quota.'}
        </p>
        {isLeader && (
          <button
            onClick={onRunResearch}
            disabled={researchLoading}
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-red-600 hover:bg-red-700 disabled:opacity-60 disabled:cursor-not-allowed text-white text-sm font-medium rounded-xl transition-colors"
          >
            {researchLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Search className="w-4 h-4" />
            )}
            {researchLoading ? 'Starting…' : 'Try again'}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="max-w-lg mx-auto py-10 text-center">
      <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-100 to-violet-100 grid place-items-center mx-auto mb-4">
        <Search className="w-7 h-7 text-indigo-600" />
      </div>
      <h3 className="text-lg font-semibold text-gray-900 mb-2">Brief the room before it starts</h3>
      <p className="text-sm text-gray-500 mb-6">
        {isLeader
          ? 'Four agents extract the searchable topics, sweep the live web, rank every source by credibility tier, and synthesize a brief with findings, data gaps and blind spots.'
          : 'The meeting leader has not run pre-meeting research yet.'}
      </p>
      {isLeader && (
        <button
          onClick={onRunResearch}
          disabled={researchLoading}
          className="inline-flex items-center gap-2 px-6 py-3 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-300 text-white font-semibold rounded-xl shadow-md hover:shadow-lg transition-all active:scale-[0.98]"
        >
          {researchLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
          Run research
        </button>
      )}
    </div>
  );
}

function SummaryScreen(props: any) {
  const {
    meeting, isLeader, hasSummary, isEnded, summaryLoading, summaryError, onGenerate,
    emailSending, emailSent, onSendEmail, outreach, onOutreach, onActionStatusCycle,
  } = props;

  if (!isEnded) {
    return (
      <EmptyState
        icon={<FileText className="w-7 h-7 text-gray-400" />}
        title="Available after the meeting"
        body="Once the meeting ends, Donna synthesizes the transcript, decisions, pinned cards and research into a summary you can send."
      />
    );
  }

  if (!hasSummary) {
    // While it runs, the screen commits to "working" rather than continuing to
    // offer the button that was already pressed. A minute of silence under an
    // unchanged call to action is what made this look broken.
    if (summaryLoading) {
      return (
        <div className="max-w-lg mx-auto py-10 text-center">
          <div className="w-14 h-14 rounded-2xl bg-indigo-100 grid place-items-center mx-auto mb-4">
            <Loader2 className="w-7 h-7 text-indigo-600 animate-spin" />
          </div>
          <h3 className="text-lg font-semibold text-gray-900 mb-2">Writing the summary…</h3>
          <p className="text-sm text-gray-500 mb-5">
            Reading the transcript, matching decisions to the quotes that triggered them, and
            pulling in the research. Usually under a minute.
          </p>
          <div className="w-full bg-indigo-100 rounded-full h-1.5 overflow-hidden">
            <div className="bg-indigo-500 h-1.5 rounded-full animate-pulse" style={{ width: '60%' }} />
          </div>
          <p className="text-xs text-gray-400 mt-4">It'll appear here on its own — no need to refresh.</p>
        </div>
      );
    }

    return (
      <div className="max-w-lg mx-auto py-10 text-center">
        <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-100 to-violet-100 grid place-items-center mx-auto mb-4">
          <FileText className="w-7 h-7 text-indigo-600" />
        </div>
        <h3 className="text-lg font-semibold text-gray-900 mb-2">Generate the summary</h3>
        <p className="text-sm text-gray-500 mb-6">
          The transcript, every logged decision with the quote that triggered it, pinned insight
          cards, and the pre-meeting research — synthesized into one report, with action items
          persisted as trackable rows.
        </p>

        {summaryError && (
          <p className="text-sm text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2 mb-5 text-left">
            {summaryError}
          </p>
        )}

        {isLeader && (
          <button
            onClick={onGenerate}
            disabled={summaryLoading}
            className="inline-flex items-center gap-2 px-6 py-3 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-semibold rounded-xl shadow-md hover:shadow-lg transition-all active:scale-[0.98]"
          >
            <Send className="w-5 h-5" />
            {summaryError ? 'Try again' : 'Generate summary'}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-5 animate-fade-up">
      <div className="bg-gradient-to-br from-primary-50 via-white to-violet-50/30 rounded-xl border border-primary-200/60 p-6 shadow-card">
        <h4 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
          <FileText className="w-4 h-4 text-primary-500" />
          Executive Summary
        </h4>
        <p className="text-gray-700 whitespace-pre-wrap leading-relaxed text-[14px]">
          {meeting.summary.summary_text}
        </p>
      </div>

      {meeting.summary.decisions_summary?.length > 0 && (
        <section>
          <h4 className="text-sm font-semibold text-gray-700 mb-3">
            Decisions ({meeting.summary.decisions_summary.length})
          </h4>
          <div className="space-y-2">
            {meeting.summary.decisions_summary.map((d: any, idx: number) => (
              <div key={idx} className="p-3 bg-gradient-to-r from-emerald-50 to-green-50 border border-emerald-100 rounded-xl">
                <p className="text-sm font-medium text-gray-900">{d.decision}</p>
                <div className="flex items-center gap-2 mt-1.5 text-[11px] text-gray-500">
                  {d.owner && <span className="bg-white px-1.5 py-0.5 rounded border border-gray-200">{d.owner}</span>}
                  {d.deadline && <span>{d.deadline}</span>}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {meeting.action_items?.length > 0 && (
        <section>
          <h4 className="text-sm font-semibold text-gray-700 mb-3">
            Action Items ({meeting.action_items.length})
          </h4>
          <div className="space-y-2">
            {meeting.action_items.map((a: any) => (
              <div key={a.id} className="p-3 bg-gradient-to-r from-sky-50 to-blue-50 border border-sky-100 rounded-xl">
                <p className={`text-sm font-medium ${a.status === 'done' ? 'text-gray-400 line-through' : 'text-gray-900'}`}>
                  {a.description}
                </p>
                <div className="flex items-center gap-2 mt-1.5 text-[11px] text-gray-500">
                  <span className="bg-white px-1.5 py-0.5 rounded border border-gray-200">
                    {a.assignee || 'Unassigned'}
                  </span>
                  {a.status && (
                    <button
                      onClick={isLeader ? () => onActionStatusCycle(a) : undefined}
                      disabled={!isLeader}
                      title={isLeader ? 'Click to advance status' : undefined}
                      className={`px-1.5 py-0.5 rounded font-medium ${
                        a.status === 'done'
                          ? 'bg-emerald-100 text-emerald-700'
                          : a.status === 'in_progress'
                            ? 'bg-amber-100 text-amber-700'
                            : 'bg-gray-100 text-gray-600'
                      } ${isLeader ? 'cursor-pointer hover:ring-1 hover:ring-gray-300' : ''}`}
                    >
                      {a.status}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="flex items-center gap-3 pt-2 flex-wrap">
        {meeting.summary.email_sent_at || emailSent ? (
          <div className="flex items-center gap-2 px-4 py-2.5 bg-emerald-50 border border-emerald-200 rounded-xl text-sm text-emerald-700">
            <CheckCircle2 className="w-4 h-4" />
            Summary emailed
          </div>
        ) : isLeader ? (
          <button
            onClick={onSendEmail}
            disabled={emailSending}
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-[#4f46e5] hover:bg-[#4338ca] text-white rounded-xl shadow-md hover:shadow-lg transition-all active:scale-[0.98] disabled:opacity-50"
          >
            {emailSending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Mail className="w-4 h-4" />}
            Send to Attendees
          </button>
        ) : null}
        {isLeader && (
          <>
            <button
              onClick={() => onOutreach('followups')}
              disabled={outreach === 'followups'}
              className="inline-flex items-center gap-2 px-4 py-2.5 bg-white border border-gray-200 hover:border-indigo-300 text-gray-600 rounded-xl text-sm transition-colors"
            >
              <Send className="w-4 h-4" />
              {outreach === 'followups' ? 'Sent!' : 'Email assignees their items'}
            </button>
            <button
              onClick={() => onOutreach('ics')}
              className="inline-flex items-center gap-2 px-4 py-2.5 bg-white border border-gray-200 hover:border-indigo-300 text-gray-600 rounded-xl text-sm transition-colors"
            >
              <Calendar className="w-4 h-4" />
              Deadlines → calendar (.ics)
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function EmptyState({ icon, title, body }: { icon: React.ReactNode; title: string; body: string }) {
  return (
    <div className="max-w-md mx-auto py-14 text-center">
      <div className="w-14 h-14 rounded-2xl bg-gray-100 grid place-items-center mx-auto mb-4">
        {icon}
      </div>
      <h3 className="text-base font-semibold text-gray-700 mb-1.5">{title}</h3>
      <p className="text-sm text-gray-500">{body}</p>
    </div>
  );
}
