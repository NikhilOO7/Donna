'use client';

import React, { useState, useEffect, useCallback } from 'react';
import {
  ArrowLeft, Calendar, Users, Search, Mic, FileText, FolderOpen,
  Loader2, AlertTriangle, Send, Mail, CheckCircle2
} from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import TimelineStep, { StepStatus } from './TimelineStep';
import KnowledgeBaseStep from './KnowledgeBaseStep';
import ResearchBriefView from './ResearchBriefView';
import MeetingRoom from './MeetingRoom';
import AssistantPanel from './AssistantPanel';

interface MeetingTimelineProps {
  meetingId: string;
  onBack: () => void;
}

export default function MeetingTimeline({ meetingId, onBack }: MeetingTimelineProps) {
  const [meeting, setMeeting] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [expandedStep, setExpandedStep] = useState<number>(0);
  const [researchLoading, setResearchLoading] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [emailSending, setEmailSending] = useState(false);
  const [emailSent, setEmailSent] = useState(false);
  // "Discuss This" on a research finding — seeds the inline Donna assistant
  const [researchAsk, setResearchAsk] = useState<string | null>(null);
  const [showResearchChat, setShowResearchChat] = useState(false);
  const [cost, setCost] = useState<any>(null);
  // Role-aware UI: participants get a read-only view of leader controls

  const fetchMeeting = useCallback(async () => {
    try {
      const data = await apiClient.getMeeting(meetingId);
      setMeeting(data);

      // Auto-expand active step
      if (data.status === 'in_progress') setExpandedStep(2);
      else if (data.status === 'completed') setExpandedStep(3);
      else if (data.research?.status === 'completed') setExpandedStep(1);
      else if (data.research?.status === 'researching') setExpandedStep(1);
    } catch (err) {
      console.error('Failed to load meeting:', err);
    } finally {
      setLoading(false);
    }
  }, [meetingId]);

  useEffect(() => {
    fetchMeeting();

    // Live channel: optimistic updates avoid re-fetching the whole meeting tree
    const cleanupWS = apiClient.connectMeetingWS(meetingId, (msg) => {
      if (msg.type === 'nudge_created' && msg.nudge) {
        setMeeting((prev: any) => {
          if (!prev) return prev;
          // Participants only surface shared-board items live: activation
          // nudges addressed to them (pins arrive via the refetch heartbeat).
          if (prev.my_role === 'participant') {
            const person = (msg.nudge.source_data?.person || '').toLowerCase();
            const mine =
              msg.nudge.type === 'activation' &&
              prev.my_name &&
              person === prev.my_name.toLowerCase();
            if (!mine) return prev;
          }
          const existing = prev.nudges || [];
          if (existing.some((n: any) => n.id === msg.nudge.id)) return prev;
          return { ...prev, nudges: [msg.nudge, ...existing] };
        });
      } else if (msg.type === 'utterance_partial' && msg.text) {
        // Ghost text: in-progress speech, replaced by the final utterance
        setMeeting((prev: any) =>
          prev ? { ...prev, partial_utterance: { speaker: msg.speaker, text: msg.text } } : prev,
        );
      } else if (msg.type === 'agenda_progress' && Array.isArray(msg.agenda)) {
        setMeeting((prev: any) =>
          prev ? { ...prev, agenda: msg.agenda } : prev,
        );
      } else if (msg.type === 'canvas_updated' && msg.positions) {
        setMeeting((prev: any) =>
          prev ? { ...prev, canvas_positions: msg.positions } : prev,
        );
      } else if (msg.type === 'utterance_added' && msg.utterance) {
        setMeeting((prev: any) => {
          if (!prev) return prev;
          const t = prev.transcript || { utterances: [], utterance_count: 0 };
          return {
            ...prev,
            partial_utterance: null, // the final replaces any ghost text
            transcript: {
              ...t,
              utterances: [...(t.utterances || []), msg.utterance],
              utterance_count: msg.utterance_count ?? (t.utterance_count || 0) + 1,
            },
          };
        });
      }
    });

    // Leader-only cost meter (best-effort; 404s for participants are fine)
    apiClient.getMeetingCost(meetingId).then(setCost).catch(() => {});

    // 30s heartbeat — catches status changes (research/summary completion) that
    // aren't pushed over the meeting WS.
    const interval = setInterval(fetchMeeting, 30000);
    return () => {
      clearInterval(interval);
      cleanupWS();
    };
  }, [fetchMeeting, meetingId]);

  const handleRunResearch = async () => {
    setResearchLoading(true);
    try {
      await apiClient.triggerResearch(meetingId);
      setExpandedStep(1);
      setTimeout(fetchMeeting, 2000);
    } catch (err) {
      console.error('Research failed:', err);
    } finally {
      setResearchLoading(false);
    }
  };

  const handleGenerateSummary = async () => {
    setSummaryLoading(true);
    try {
      await apiClient.generateSummary(meetingId);
      setExpandedStep(3);
      setTimeout(fetchMeeting, 3000);
    } catch (err) {
      console.error('Summary generation failed:', err);
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
      item.status === 'open' ? 'in_progress'
      : item.status === 'in_progress' ? 'done'
      : 'open';
    try {
      await apiClient.updateActionItemStatus(meetingId, item.id, next);
      fetchMeeting();
    } catch (err) {
      console.error('Action item status update failed:', err);
    }
  };

  const [outreach, setOutreach] = useState<string | null>(null);
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

  const toggleStep = (step: number) => {
    setExpandedStep(expandedStep === step ? -1 : step);
  };

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

  // Derive step statuses
  const hasResearch = meeting.research?.status === 'completed';
  const isLeader = meeting?.my_role !== 'participant';
  const isResearching = meeting.research?.status === 'researching';
  const researchFailed = meeting.research?.status === 'failed';
  const hasSummary = !!meeting.summary;
  const isLive = meeting.status === 'in_progress';
  const isEnded = meeting.status === 'completed';

  const kbStatus: StepStatus = 'completed'; // Always available
  const researchStatus: StepStatus = hasResearch
    ? 'completed'
    : researchFailed
      ? 'error'
      : isResearching
        ? 'active'
        : 'pending';
  const meetingStatus: StepStatus = isEnded
    ? 'completed'
    : isLive
      ? 'active'
      : 'pending';
  const summaryStatus: StepStatus = hasSummary
    ? 'completed'
    : isEnded
      ? 'active'
      : 'pending';

  return (
    <div>
      {/* Meeting Header */}
      <div className="mb-8">
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
        </div>
        {meeting.description && (
          <p className="text-gray-500 mt-1 max-w-2xl">{meeting.description}</p>
        )}
        {meeting.agenda?.length > 0 && (
          <div className="mt-3 flex items-center gap-2 flex-wrap">
            <span className="text-[10px] font-bold uppercase tracking-widest text-gray-400">Agenda</span>
            {meeting.agenda.map((a: any, i: number) => (
              <span key={i} className="px-2 py-0.5 bg-gray-50 border border-gray-200 rounded-lg text-xs text-gray-600">
                {i + 1}. {a.title}
              </span>
            ))}
          </div>
        )}
        <div className="flex items-center gap-4 mt-2 text-sm text-gray-500">
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

      {/* Vertical Timeline */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 lg:p-8">
        {/* Step 0: Knowledge Base */}
        <TimelineStep
          stepNumber={0}
          title="Knowledge Base"
          subtitle="Upload documents for meeting context"
          status={kbStatus}
          statusLabel="ready"
          icon={<FolderOpen className="w-5 h-5" />}
          isExpanded={expandedStep === 0}
          onClick={() => toggleStep(0)}
        >
          {isLeader ? (
            <KnowledgeBaseStep meetingId={meetingId} />
          ) : (
            <p className="text-sm text-gray-400 py-6 text-center">
              The knowledge base is managed by the meeting leader.
            </p>
          )}
        </TimelineStep>

        {/* Step 1: Pre-Meeting Research */}
        <TimelineStep
          stepNumber={1}
          title="Pre-Meeting Research"
          subtitle="Web research, source validation, executive summary"
          status={researchStatus}
          statusLabel={
            hasResearch
              ? `${meeting.research.source_count} sources`
              : isResearching
                ? 'researching...'
                : researchFailed
                  ? 'failed'
                  : 'not started'
          }
          icon={<Search className="w-5 h-5" />}
          isExpanded={expandedStep === 1}
          onClick={() => toggleStep(1)}
        >
          {hasResearch && meeting.research ? (
            <div className="space-y-4">
              {isLeader && (
                <div className="flex items-center gap-2 flex-wrap">
                  <button
                    onClick={() => handleOutreach('preread')}
                    disabled={outreach === 'preread'}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white text-xs font-medium rounded-lg transition-colors"
                  >
                    <Mail className="w-3.5 h-3.5" />
                    {outreach === 'preread' ? 'Sent!' : 'Send pre-read to attendees'}
                  </button>
                  <button
                    onClick={() => handleOutreach('invite')}
                    disabled={outreach === 'invite'}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-gray-200 hover:border-indigo-300 text-gray-600 text-xs font-medium rounded-lg transition-colors"
                  >
                    <Users className="w-3.5 h-3.5" />
                    {outreach === 'invite' ? 'Invites sent!' : 'Email invites'}
                  </button>
                  <button
                    onClick={() => handleOutreach('ics')}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-gray-200 hover:border-indigo-300 text-gray-600 text-xs font-medium rounded-lg transition-colors"
                  >
                    <Calendar className="w-3.5 h-3.5" />
                    Add to calendar (.ics)
                  </button>
                </div>
              )}
              <ResearchBriefView
                research={meeting.research}
                onDiscuss={(prompt) => {
                  setShowResearchChat(true);
                  setResearchAsk(prompt);
                }}
              />
              {showResearchChat && (
                <div className="h-[380px] animate-fade-up">
                  <AssistantPanel
                    meetingId={meetingId}
                    pendingPrompt={researchAsk}
                    onPromptConsumed={() => setResearchAsk(null)}
                  />
                </div>
              )}
            </div>
          ) : isResearching ? (
            <div className="bg-yellow-50 rounded-xl p-6">
              <div className="flex items-center gap-3 mb-3">
                <Loader2 className="w-5 h-5 text-yellow-600 animate-spin" />
                <span className="font-medium text-yellow-800">Research pipeline running...</span>
              </div>
              <div className="w-full bg-yellow-200 rounded-full h-1.5">
                <div className="bg-yellow-500 h-1.5 rounded-full animate-pulse" style={{ width: '50%' }} />
              </div>
              <p className="text-sm text-yellow-700 mt-3">
                Extracting topics, searching web, validating sources, synthesizing...
              </p>
            </div>
          ) : researchFailed ? (
            <div className="bg-red-50 rounded-xl p-6">
              <p className="text-red-700 text-sm mb-3">{meeting.research?.executive_summary || 'Research failed'}</p>
              {isLeader && (
              <button
                onClick={handleRunResearch}
                className="px-4 py-2 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700"
              >
                Retry Research
              </button>
              )}
            </div>
          ) : (
            <div className="text-center py-8">
              <p className="text-gray-500 mb-4">
                {isLeader
                  ? 'Run the 4-agent research pipeline to gather intelligence for your meeting.'
                  : 'The meeting leader has not run pre-meeting research yet.'}
              </p>
              {isLeader && (
              <button
                onClick={handleRunResearch}
                disabled={researchLoading}
                className="inline-flex items-center gap-2 px-5 py-2.5 bg-primary-600 text-white rounded-xl hover:bg-primary-700 disabled:bg-gray-300 transition-colors"
              >
                {researchLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                Run Research Pipeline
              </button>
              )}
            </div>
          )}
        </TimelineStep>

        {/* Step 2: Live Meeting */}
        <TimelineStep
          stepNumber={2}
          title="Live Meeting"
          subtitle="Voice, transcription, nudge cards, decisions"
          status={meetingStatus}
          statusLabel={
            isEnded
              ? 'ended'
              : isLive
                ? 'live now'
                : 'not started'
          }
          icon={<Mic className="w-5 h-5" />}
          isExpanded={expandedStep === 2}
          onClick={() => toggleStep(2)}
        >
          <MeetingRoom meeting={meeting} onRefresh={fetchMeeting} />
        </TimelineStep>

        {/* Step 3: Post-Meeting */}
        <TimelineStep
          stepNumber={3}
          title="Post-Meeting Summary"
          subtitle="AI summary, decisions, action items, email"
          status={summaryStatus}
          statusLabel={
            hasSummary
              ? 'completed'
              : isEnded
                ? 'ready to generate'
                : 'waiting for meeting'
          }
          icon={<FileText className="w-5 h-5" />}
          isExpanded={expandedStep === 3}
          isLast={true}
          onClick={() => toggleStep(3)}
        >
          {hasSummary ? (
            <div className="space-y-5 animate-fade-up">
              {/* Executive Summary */}
              <div className="bg-gradient-to-br from-primary-50 via-white to-violet-50/30 rounded-xl border border-primary-200/60 p-6 shadow-card">
                <h4 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
                  <FileText className="w-4 h-4 text-primary-500" />
                  Executive Summary
                </h4>
                <p className="text-gray-700 whitespace-pre-wrap leading-relaxed text-[14px]">
                  {meeting.summary.summary_text}
                </p>
              </div>

              {/* Decisions from summary */}
              {meeting.summary.decisions_summary?.length > 0 && (
                <div>
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
                </div>
              )}

              {/* Action Items */}
              {meeting.action_items?.length > 0 && (
                <div>
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
                          {a.priority && (
                            <span className={`px-1.5 py-0.5 rounded font-medium ${
                              a.priority === 'high'
                                ? 'bg-red-100 text-red-700'
                                : a.priority === 'low'
                                  ? 'bg-gray-100 text-gray-600'
                                  : 'bg-amber-100 text-amber-700'
                            }`}>
                              {a.priority}
                            </span>
                          )}
                          {a.status && (
                            <button
                              onClick={isLeader ? () => handleActionStatusCycle(a) : undefined}
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
                </div>
              )}

              {/* AI Insights */}
              {meeting.summary.key_insights?.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold text-gray-700 mb-3">AI Insights Used</h4>
                  <div className="space-y-2">
                    {meeting.summary.key_insights.map((i: any, idx: number) => (
                      <div key={idx} className="p-3 bg-amber-50 border border-amber-100 rounded-xl text-sm">
                        <p className="text-gray-900">{i.insight}</p>
                        {i.impact && <p className="text-gray-500 text-xs mt-1">Impact: {i.impact}</p>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Email Actions */}
              <div className="flex items-center gap-3 pt-2">
                {meeting.summary.email_sent_at || emailSent ? (
                  <div className="flex items-center gap-2 px-4 py-2.5 bg-emerald-50 border border-emerald-200 rounded-xl text-sm text-emerald-700">
                    <CheckCircle2 className="w-4 h-4" />
                    Summary emailed
                    {meeting.summary.email_sent_at && (
                      <span className="text-emerald-500">
                        at {new Date(meeting.summary.email_sent_at).toLocaleString()}
                      </span>
                    )}
                  </div>
                ) : isLeader ? (
                  <button
                    onClick={handleSendEmail}
                    disabled={emailSending}
                    className="inline-flex items-center gap-2 px-5 py-2.5 bg-[#4f46e5] hover:bg-[#4338ca] text-white rounded-xl shadow-md hover:shadow-lg transition-all duration-200 active:scale-[0.98] disabled:opacity-50"
                  >
                    {emailSending ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Mail className="w-4 h-4" />
                    )}
                    Send to Attendees
                  </button>
                ) : null}
                {isLeader && (
                  <>
                    <button
                      onClick={() => handleOutreach('followups')}
                      disabled={outreach === 'followups'}
                      className="inline-flex items-center gap-2 px-4 py-2.5 bg-white border border-gray-200 hover:border-indigo-300 text-gray-600 rounded-xl text-sm transition-colors"
                    >
                      <Send className="w-4 h-4" />
                      {outreach === 'followups' ? 'Sent!' : 'Email assignees their items'}
                    </button>
                    <button
                      onClick={() => handleOutreach('ics')}
                      className="inline-flex items-center gap-2 px-4 py-2.5 bg-white border border-gray-200 hover:border-indigo-300 text-gray-600 rounded-xl text-sm transition-colors"
                    >
                      <Calendar className="w-4 h-4" />
                      Deadlines → calendar (.ics)
                    </button>
                  </>
                )}
              </div>
            </div>
          ) : isEnded ? (
            <div className="text-center py-10">
              <div className="w-14 h-14 bg-gradient-to-br from-primary-100 to-violet-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
                <FileText className="w-7 h-7 text-primary-600" />
              </div>
              <h4 className="text-lg font-semibold text-gray-900 mb-2">Generate Meeting Summary</h4>
              <p className="text-gray-500 mb-6 max-w-sm mx-auto text-sm">
                AI will synthesize the transcript, decisions, nudge cards, and pre-meeting research into a comprehensive summary.
              </p>
              {isLeader && (
              <button
                onClick={handleGenerateSummary}
                disabled={summaryLoading}
                className="inline-flex items-center gap-2 px-6 py-3 bg-[#4f46e5] hover:bg-[#4338ca] text-white rounded-xl shadow-md hover:shadow-lg transition-all duration-200 active:scale-[0.98] disabled:opacity-50"
              >
                {summaryLoading ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    <Send className="w-5 h-5" />
                    Generate Summary
                  </>
                )}
              </button>
              )}
            </div>
          ) : (
            <div className="text-center py-10">
              <p className="text-gray-400 text-sm">
                The meeting summary will be available after the meeting ends.
              </p>
            </div>
          )}

          {/* Meeting Decisions (always visible if present) */}
          {!hasSummary && meeting.decisions?.length > 0 && (
            <div className="mt-6">
              <h4 className="text-sm font-semibold text-gray-700 mb-3">
                Decisions ({meeting.decisions.length})
              </h4>
              <div className="space-y-2">
                {meeting.decisions.map((d: any) => (
                  <div key={d.id} className="p-3 bg-emerald-50 border border-emerald-100 rounded-xl">
                    <p className="text-sm font-medium text-gray-900">{d.decision_text}</p>
                    <div className="flex items-center gap-2 mt-1 text-xs text-gray-500">
                      {d.owner && <span>Owner: {d.owner}</span>}
                      {d.deadline && <span>Due: {new Date(d.deadline).toLocaleDateString()}</span>}
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
            </div>
          )}
        </TimelineStep>
      </div>
    </div>
  );
}
