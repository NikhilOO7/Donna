'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Plus, Calendar, Users, Trash2, ChevronRight, Sparkles, Clock } from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import CreateMeetingModal from './CreateMeetingModal';

const STATUS_CONFIG: Record<string, { bg: string; text: string; dot: string }> = {
  scheduled: { bg: 'bg-gray-50', text: 'text-gray-600', dot: 'bg-gray-400' },
  researching: { bg: 'bg-amber-50', text: 'text-amber-700', dot: 'bg-amber-400 animate-pulse' },
  ready: { bg: 'bg-emerald-50', text: 'text-emerald-700', dot: 'bg-emerald-400' },
  in_progress: { bg: 'bg-blue-50', text: 'text-blue-700', dot: 'bg-blue-500 animate-pulse' },
  completed: { bg: 'bg-violet-50', text: 'text-violet-700', dot: 'bg-violet-400' },
  cancelled: { bg: 'bg-red-50', text: 'text-red-700', dot: 'bg-red-400' },
};

interface MeetingListProps {
  onSelectMeeting: (meetingId: string) => void;
}

export default function MeetingList({ onSelectMeeting }: MeetingListProps) {
  const [meetings, setMeetings] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);

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

  if (loading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-24 rounded-xl animate-shimmer" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Meetings</h2>
          <p className="text-gray-500 mt-0.5">Manage your meeting workflow — research, meet, summarize</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-5 py-2.5 bg-[#4f46e5] hover:bg-[#4338ca] text-white rounded-xl shadow-md hover:shadow-lg transition-all duration-200 active:scale-[0.98]"
        >
          <Plus className="w-4 h-4" />
          New Meeting
        </button>
      </div>

      {/* Empty State */}
      {meetings.length === 0 ? (
        <div className="text-center py-20 bg-gradient-to-b from-white to-primary-50/30 rounded-2xl border border-gray-200/60 shadow-card">
          <div className="w-16 h-16 bg-gradient-to-br from-primary-100 to-primary-200 rounded-2xl flex items-center justify-center mx-auto mb-5 shadow-sm">
            <Sparkles className="w-8 h-8 text-primary-600" />
          </div>
          <h3 className="text-xl font-semibold text-gray-900 mb-2">Create your first meeting</h3>
          <p className="text-gray-500 mb-6 max-w-sm mx-auto">
            Start by creating a meeting. We&apos;ll help you prepare with AI-powered research, real-time intelligence, and automated summaries.
          </p>
          <button
            onClick={() => setShowCreate(true)}
            className="px-6 py-3 bg-[#4f46e5] hover:bg-[#4338ca] text-white rounded-xl shadow-md hover:shadow-lg transition-all duration-200"
          >
            Create Meeting
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {meetings.map((meeting, idx) => {
            const cfg = STATUS_CONFIG[meeting.status] || STATUS_CONFIG.scheduled;
            return (
              <div
                key={meeting.id}
                onClick={() => onSelectMeeting(meeting.id)}
                className="bg-white rounded-xl border border-gray-200/60 p-5 shadow-card hover:shadow-card-hover hover:border-primary-200 transition-all duration-300 cursor-pointer group animate-fade-up"
                style={{ animationDelay: `${idx * 60}ms` }}
              >
                <div className="flex items-center justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 mb-2">
                      <h3 className="text-base font-semibold text-gray-900 truncate group-hover:text-primary-700 transition-colors">
                        {meeting.title}
                      </h3>
                      <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-medium ${cfg.bg} ${cfg.text}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
                        {meeting.status.replace('_', ' ')}
                      </span>
                    </div>

                    <div className="flex items-center gap-4 text-sm text-gray-500">
                      {meeting.scheduled_at && (
                        <div className="flex items-center gap-1.5">
                          <Calendar className="w-3.5 h-3.5" />
                          {new Date(meeting.scheduled_at).toLocaleDateString('en-US', {
                            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
                          })}
                        </div>
                      )}
                      {meeting.attendees?.length > 0 && (
                        <div className="flex items-center gap-1.5">
                          <Users className="w-3.5 h-3.5" />
                          {meeting.attendees.length}
                        </div>
                      )}
                      <div className="flex items-center gap-1.5 text-gray-400">
                        <Clock className="w-3.5 h-3.5" />
                        {new Date(meeting.created_at).toLocaleDateString()}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-1">
                    <button
                      onClick={(e) => handleDelete(e, meeting.id)}
                      className="p-2 text-gray-300 hover:text-red-500 rounded-lg opacity-0 group-hover:opacity-100 transition-all duration-200 hover:bg-red-50"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                    <ChevronRight className="w-5 h-5 text-gray-300 group-hover:text-primary-500 group-hover:translate-x-0.5 transition-all duration-200" />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {showCreate && (
        <CreateMeetingModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); fetchMeetings(); }}
        />
      )}
    </div>
  );
}
