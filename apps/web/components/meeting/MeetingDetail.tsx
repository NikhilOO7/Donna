'use client';

import React, { useState, useEffect, useCallback } from 'react';
import {
  ArrowLeft, Calendar, Users, Search, CheckCircle, Clock,
  AlertTriangle, Loader2, Trash2, FileText
} from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import ResearchBriefView from './ResearchBriefView';

interface MeetingDetailProps {
  meetingId: string;
  onBack: () => void;
}

const STATUS_COLORS: Record<string, string> = {
  scheduled: 'bg-gray-100 text-gray-700',
  researching: 'bg-yellow-100 text-yellow-700',
  ready: 'bg-green-100 text-green-700',
  in_progress: 'bg-blue-100 text-blue-700',
  completed: 'bg-purple-100 text-purple-700',
};

export default function MeetingDetail({ meetingId, onBack }: MeetingDetailProps) {
  const [meeting, setMeeting] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [researchLoading, setResearchLoading] = useState(false);
  const [error, setError] = useState('');

  const fetchMeeting = useCallback(async () => {
    try {
      const data = await apiClient.getMeeting(meetingId);
      setMeeting(data);
    } catch (err) {
      setError('Failed to load meeting');
    } finally {
      setLoading(false);
    }
  }, [meetingId]);

  useEffect(() => {
    fetchMeeting();
    // Poll while researching
    const interval = setInterval(() => {
      fetchMeeting();
    }, 5000);
    return () => clearInterval(interval);
  }, [fetchMeeting]);

  const handleRunResearch = async () => {
    setResearchLoading(true);
    try {
      await apiClient.triggerResearch(meetingId);
      // Start polling
      setTimeout(fetchMeeting, 2000);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to start research');
    } finally {
      setResearchLoading(false);
    }
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
        <p className="text-red-600">{error || 'Meeting not found'}</p>
        <button onClick={onBack} className="mt-4 text-primary-600 hover:underline">
          Back to meetings
        </button>
      </div>
    );
  }

  const researchStatus = meeting.research?.status;
  const isResearching = researchStatus === 'researching';
  const hasResearch = researchStatus === 'completed';

  return (
    <div className="space-y-6">
      {/* Back Button + Header */}
      <div>
        <button
          onClick={onBack}
          className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 mb-4"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to meetings
        </button>

        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <h1 className="text-2xl font-bold text-gray-900">{meeting.title}</h1>
              <span className={`px-3 py-1 rounded-full text-xs font-medium ${STATUS_COLORS[meeting.status] || STATUS_COLORS.scheduled}`}>
                {meeting.status.replace('_', ' ')}
              </span>
            </div>

            {meeting.description && (
              <p className="text-gray-600 mb-3 max-w-2xl">{meeting.description}</p>
            )}

            <div className="flex items-center gap-4 text-sm text-gray-500">
              {meeting.scheduled_at && (
                <div className="flex items-center gap-1">
                  <Calendar className="w-4 h-4" />
                  {new Date(meeting.scheduled_at).toLocaleString()}
                </div>
              )}
              {meeting.attendees?.length > 0 && (
                <div className="flex items-center gap-1">
                  <Users className="w-4 h-4" />
                  {meeting.attendees.map((a: any) => a.email || a.name).join(', ')}
                </div>
              )}
            </div>
          </div>

          {/* Research Button */}
          {!hasResearch && !isResearching && (
            <button
              onClick={handleRunResearch}
              disabled={researchLoading}
              className="flex items-center gap-2 px-5 py-2.5 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:bg-gray-300 transition-colors"
            >
              {researchLoading ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Search className="w-5 h-5" />
              )}
              Run Research
            </button>
          )}
        </div>
      </div>

      {/* Research Status / Brief */}
      {isResearching && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6">
          <div className="flex items-center gap-3 mb-3">
            <Loader2 className="w-6 h-6 text-yellow-600 animate-spin" />
            <h3 className="text-lg font-semibold text-yellow-800">Research in Progress</h3>
          </div>
          <div className="space-y-2 text-sm text-yellow-700">
            <div className="flex items-center gap-2">
              <CheckCircle className="w-4 h-4" /> Extracting research topics...
            </div>
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4" /> Searching web sources...
            </div>
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4" /> Validating and scoring...
            </div>
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4" /> Generating executive summary...
            </div>
          </div>
        </div>
      )}

      {hasResearch && meeting.research && (
        <ResearchBriefView research={meeting.research} />
      )}

      {researchStatus === 'failed' && meeting.research && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-6">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="w-5 h-5 text-red-500" />
            <h3 className="font-semibold text-red-800">Research Failed</h3>
          </div>
          <p className="text-sm text-red-700">{meeting.research.executive_summary}</p>
          <button
            onClick={handleRunResearch}
            className="mt-3 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 text-sm"
          >
            Retry Research
          </button>
        </div>
      )}

      {/* Decisions */}
      {meeting.decisions?.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">
            Decisions ({meeting.decisions.length})
          </h3>
          <div className="space-y-3">
            {meeting.decisions.map((d: any) => (
              <div key={d.id} className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg">
                <CheckCircle className="w-5 h-5 text-green-500 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="font-medium text-gray-900">{d.decision_text}</p>
                  <div className="flex items-center gap-3 mt-1 text-sm text-gray-500">
                    {d.owner && <span>Owner: {d.owner}</span>}
                    {d.deadline && <span>Due: {new Date(d.deadline).toLocaleDateString()}</span>}
                    <span className="px-2 py-0.5 bg-gray-200 rounded text-xs">{d.status}</span>
                  </div>
                  {d.action_items?.length > 0 && (
                    <ul className="mt-2 space-y-1">
                      {d.action_items.map((a: any) => (
                        <li key={a.id} className="text-sm text-gray-600 flex items-center gap-2">
                          <FileText className="w-3 h-3" />
                          {a.description}
                          {a.assignee && <span className="text-gray-400">({a.assignee})</span>}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Summary */}
      {meeting.summary && (
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Meeting Summary</h3>
          <div className="prose prose-sm max-w-none">
            <p className="whitespace-pre-wrap">{meeting.summary.summary_text}</p>
          </div>
        </div>
      )}
    </div>
  );
}
