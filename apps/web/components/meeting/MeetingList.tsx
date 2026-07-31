'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Plus, Calendar, Users, Trash2, ChevronRight, Clock, Search,
  ClipboardList, MessageCircle, FileUp, Play,
} from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import CreateMeetingModal from './CreateMeetingModal';
import ConversationalSetup from './ConversationalSetup';
import UploadTranscriptSetup from './UploadTranscriptSetup';

const STATUS_CONFIG: Record<string, { bg: string; text: string; dot: string }> = {
  scheduled: { bg: 'bg-gray-50', text: 'text-gray-600', dot: 'bg-gray-400' },
  researching: { bg: 'bg-amber-50', text: 'text-amber-700', dot: 'bg-amber-400 animate-pulse' },
  ready: { bg: 'bg-emerald-50', text: 'text-emerald-700', dot: 'bg-emerald-400' },
  in_progress: { bg: 'bg-blue-50', text: 'text-blue-700', dot: 'bg-blue-500 animate-pulse' },
  completed: { bg: 'bg-violet-50', text: 'text-violet-700', dot: 'bg-violet-400' },
  cancelled: { bg: 'bg-red-50', text: 'text-red-700', dot: 'bg-red-400' },
};

/** "Meeting type: X" prefix written by the setup form → surfaced as a tag chip. */
function meetingTypeOf(description?: string): string | null {
  const m = /^Meeting type:\s*(.+)$/m.exec(description || '');
  return m ? m[1].trim() : null;
}

interface MeetingListProps {
  onSelectMeeting: (meetingId: string) => void;
}

/* PDF page 1 — "Let's get started!" three-option setup screen */
function GetStartedScreen({
  onStandardSetup,
  onConversationalSetup,
  onUploadTranscript,
}: {
  onStandardSetup: () => void;
  onConversationalSetup: () => void;
  onUploadTranscript: () => void;
}) {
  const options = [
    {
      icon: ClipboardList,
      title: 'Standard Setup',
      body: 'Fill out a form with your meeting details and upload materials.',
      enabled: true,
      onClick: onStandardSetup,
    },
    {
      icon: MessageCircle,
      title: 'Conversational Setup',
      body: 'Chat with Donna to set up your meeting naturally — she builds the plan as you talk.',
      enabled: true,
      onClick: onConversationalSetup,
    },
    {
      icon: FileUp,
      title: 'Upload Transcript',
      body: 'Analyze an existing meeting transcript to get insights and summaries.',
      enabled: true,
      onClick: onUploadTranscript,
    },
  ];

  return (
    <div className="bg-white rounded-2xl border border-gray-200/60 shadow-card py-16 px-8 text-center">
      <h3 className="text-2xl font-bold text-gray-900 mb-2">Let&apos;s get started!</h3>
      <p className="text-gray-500 mb-10">What would you like Donna to help you with today?</p>

      <div className="grid sm:grid-cols-3 gap-4 max-w-3xl mx-auto">
        {options.map((o) => (
          <button
            key={o.title}
            onClick={o.enabled ? o.onClick : undefined}
            disabled={!o.enabled}
            className={`relative p-6 rounded-2xl border text-left transition-all duration-200 ${
              o.enabled
                ? 'border-gray-200 hover:border-indigo-300 hover:shadow-card-hover hover:-translate-y-0.5 cursor-pointer bg-white'
                : 'border-gray-100 bg-gray-50/60 cursor-default'
            }`}
          >
            {!o.enabled && (
              <span className="absolute top-3 right-3 px-2 py-0.5 bg-gray-100 text-gray-400 rounded-full text-[10px] font-medium">
                Coming soon
              </span>
            )}
            <div className={`w-10 h-10 rounded-xl flex items-center justify-center mb-4 ${
              o.enabled ? 'bg-gradient-to-br from-indigo-500 to-violet-600 shadow-sm' : 'bg-gray-200'
            }`}>
              <o.icon className={`w-5 h-5 ${o.enabled ? 'text-white' : 'text-gray-400'}`} />
            </div>
            <h4 className={`font-semibold mb-1.5 ${o.enabled ? 'text-gray-900' : 'text-gray-400'}`}>
              {o.title}
            </h4>
            <p className={`text-[13px] leading-relaxed ${o.enabled ? 'text-gray-500' : 'text-gray-400'}`}>
              {o.body}
            </p>
          </button>
        ))}
      </div>

      <p className="text-xs text-gray-400 mt-8">
        Choose an option to continue. Donna will guide you through the rest of the process.
      </p>
    </div>
  );
}

export default function MeetingList({ onSelectMeeting }: MeetingListProps) {
  const [meetings, setMeetings] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [showConversational, setShowConversational] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [search, setSearch] = useState('');

  const fetchMeetings = useCallback(async () => {
    try {
      const data = await apiClient.listMeetings();
      setMeetings(data.meetings || []);
    } catch (error) {
      console.error('Failed to fetch meetings:', error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMeetings();
    const interval = setInterval(fetchMeetings, 30000);
    return () => clearInterval(interval);
  }, [fetchMeetings]);

  const handleDelete = async (e: React.MouseEvent, meetingId: string) => {
    e.stopPropagation();
    if (!confirm('Delete this meeting?')) return;
    try {
      await apiClient.deleteMeeting(meetingId);
      fetchMeetings();
    } catch (error) {
      console.error('Failed to delete:', error);
    }
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return meetings;
    return meetings.filter((m) => m.title?.toLowerCase().includes(q));
  }, [meetings, search]);

  if (loading) {
    return (
      <div className="grid sm:grid-cols-2 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-36 rounded-2xl animate-shimmer" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header — title, search, primary CTA */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Meetings</h2>
          <p className="text-gray-500 mt-0.5 text-sm">Research before, intelligence during, summaries after.</p>
        </div>
        <div className="flex items-center gap-3">
          {meetings.length > 0 && (
            <div className="relative">
              <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search meetings..."
                className="pl-9 pr-3.5 py-2 bg-white border border-gray-200 rounded-xl text-sm w-52 focus:ring-2 focus:ring-indigo-400 focus:border-indigo-400 outline-none transition-shadow"
              />
            </div>
          )}
          <button
            onClick={() => setShowConversational(true)}
            title="Set up conversationally with Donna"
            className="flex items-center gap-2 px-3.5 py-2.5 bg-white text-violet-600 border border-violet-200 rounded-xl hover:bg-violet-50 transition-all duration-200 text-sm font-medium"
          >
            <MessageCircle className="w-4 h-4" />
          </button>
          <button
            onClick={() => setShowUpload(true)}
            title="Analyze an existing transcript"
            className="flex items-center gap-2 px-3.5 py-2.5 bg-white text-indigo-600 border border-indigo-200 rounded-xl hover:bg-indigo-50 transition-all duration-200 text-sm font-medium"
          >
            <FileUp className="w-4 h-4" />
          </button>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 px-5 py-2.5 bg-gray-900 hover:bg-gray-800 text-white rounded-xl shadow-md hover:shadow-lg transition-all duration-200 active:scale-[0.98] text-sm font-medium"
          >
            <Play className="w-4 h-4" />
            Start Meeting
          </button>
        </div>
      </div>

      {/* Empty state — the PDF's "Let's get started!" screen */}
      {meetings.length === 0 ? (
        <GetStartedScreen
          onStandardSetup={() => setShowCreate(true)}
          onConversationalSetup={() => setShowConversational(true)}
          onUploadTranscript={() => setShowUpload(true)}
        />
      ) : (
        <div className="grid sm:grid-cols-2 gap-4">
          {filtered.map((meeting, idx) => {
            const cfg = STATUS_CONFIG[meeting.status] || STATUS_CONFIG.scheduled;
            const mType = meeting.meeting_type || meetingTypeOf(meeting.description);
            return (
              <div
                key={meeting.id}
                onClick={() => onSelectMeeting(meeting.id)}
                className="bg-white rounded-2xl border border-gray-200/60 p-5 shadow-card hover:shadow-card-hover hover:border-indigo-200 hover:-translate-y-0.5 transition-all duration-300 cursor-pointer group animate-fade-up flex flex-col"
                style={{ animationDelay: `${idx * 50}ms` }}
              >
                <div className="flex items-start justify-between gap-2 mb-3">
                  <span className="flex items-center gap-1.5">
                    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium ${cfg.bg} ${cfg.text}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
                      {meeting.status.replace('_', ' ')}
                    </span>
                    {meeting.my_role === 'participant' && (
                      <span className="px-2 py-0.5 bg-violet-50 text-violet-600 border border-violet-100 rounded-full text-[10px] font-medium">
                        Shared with you
                      </span>
                    )}
                  </span>
                  <button
                    onClick={(e) => handleDelete(e, meeting.id)}
                    className="p-1.5 text-gray-300 hover:text-red-500 rounded-lg opacity-0 group-hover:opacity-100 transition-all duration-200 hover:bg-red-50"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>

                <h3 className="text-base font-semibold text-gray-900 group-hover:text-indigo-700 transition-colors leading-snug mb-1">
                  {meeting.title}
                </h3>
                {mType && (
                  <span className="self-start px-2 py-0.5 bg-indigo-50 text-indigo-600 border border-indigo-100 rounded text-[10px] font-medium mb-2">
                    {mType}
                  </span>
                )}

                <div className="mt-auto pt-3 flex items-center justify-between">
                  <div className="flex items-center gap-3 text-xs text-gray-500">
                    {meeting.scheduled_at && (
                      <span className="flex items-center gap-1">
                        <Calendar className="w-3.5 h-3.5" />
                        {new Date(meeting.scheduled_at).toLocaleDateString('en-US', {
                          month: 'short', day: 'numeric',
                        })}
                      </span>
                    )}
                    {meeting.attendees?.length > 0 && (
                      <span className="flex items-center gap-1">
                        <Users className="w-3.5 h-3.5" />
                        {meeting.attendees.length}
                      </span>
                    )}
                    <span className="flex items-center gap-1 text-gray-400">
                      <Clock className="w-3.5 h-3.5" />
                      {new Date(meeting.created_at).toLocaleDateString()}
                    </span>
                  </div>
                  <ChevronRight className="w-[18px] h-[18px] text-gray-300 group-hover:text-indigo-500 group-hover:translate-x-0.5 transition-all duration-200" />
                </div>
              </div>
            );
          })}
          {filtered.length === 0 && (
            <div className="sm:col-span-2 text-center py-14 text-gray-400 text-sm">
              No meetings match &ldquo;{search}&rdquo;
            </div>
          )}
        </div>
      )}

      {showCreate && (
        <CreateMeetingModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); fetchMeetings(); }}
        />
      )}

      {showConversational && (
        <ConversationalSetup
          onClose={() => setShowConversational(false)}
          onCreated={() => { setShowConversational(false); fetchMeetings(); }}
        />
      )}

      {showUpload && (
        <UploadTranscriptSetup
          onClose={() => setShowUpload(false)}
          onCreated={() => { setShowUpload(false); fetchMeetings(); }}
        />
      )}
    </div>
  );
}
