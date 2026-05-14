'use client';

import React, { useState, useEffect } from 'react';
import { X, Calendar, Users, Sparkles } from 'lucide-react';
import { apiClient } from '@/lib/api-client';

interface CreateMeetingModalProps {
  onClose: () => void;
  onCreated: () => void;
}

export default function CreateMeetingModal({ onClose, onCreated }: CreateMeetingModalProps) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [scheduledAt, setScheduledAt] = useState('');
  const [attendeesText, setAttendeesText] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    // Trigger entrance animation
    requestAnimationFrame(() => setVisible(true));
  }, []);

  const handleClose = () => {
    setVisible(false);
    setTimeout(onClose, 200);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) { setError('Title is required'); return; }

    setSubmitting(true);
    setError('');

    try {
      const attendees = attendeesText
        .split(',')
        .map((a) => a.trim())
        .filter(Boolean)
        .map((email) => ({ email }));

      await apiClient.createMeeting({
        title: title.trim(),
        description: description.trim() || undefined,
        scheduled_at: scheduledAt || undefined,
        attendees,
      });

      onCreated();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create meeting');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={`fixed inset-0 z-50 flex items-center justify-center transition-all duration-300 ${
      visible ? 'bg-black/40 backdrop-blur-sm' : 'bg-black/0'
    }`}>
      <div className={`bg-white rounded-2xl shadow-elevated w-full max-w-lg mx-4 transition-all duration-300 ${
        visible ? 'scale-100 opacity-100 translate-y-0' : 'scale-95 opacity-0 translate-y-4'
      }`}>
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-gray-100">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-primary-100 to-primary-200 rounded-xl flex items-center justify-center">
              <Sparkles className="w-5 h-5 text-primary-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900">New Meeting</h2>
              <p className="text-xs text-gray-500">AI will research and prepare intelligence</p>
            </div>
          </div>
          <button
            onClick={handleClose}
            className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-xl transition-all"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Meeting Title *
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Q3 Strategy Review"
              className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition-shadow bg-gray-50/50 hover:bg-white"
              autoFocus
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Description / Agenda
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe the meeting topics, goals, and context. The more detail you provide, the better the AI research will be..."
              rows={4}
              className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-primary-500 resize-none transition-shadow bg-gray-50/50 hover:bg-white"
            />
            <p className="mt-1.5 text-[11px] text-gray-400">
              Detailed descriptions help the research agents find more relevant intelligence
            </p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                <Calendar className="w-3.5 h-3.5 inline mr-1 text-gray-400" />
                Date & Time
              </label>
              <input
                type="datetime-local"
                value={scheduledAt}
                onChange={(e) => setScheduledAt(e.target.value)}
                className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-primary-500 bg-gray-50/50 hover:bg-white transition-shadow text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                <Users className="w-3.5 h-3.5 inline mr-1 text-gray-400" />
                Attendees
              </label>
              <input
                type="text"
                value={attendeesText}
                onChange={(e) => setAttendeesText(e.target.value)}
                placeholder="alice@co.com, bob@co.com"
                className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 focus:border-primary-500 bg-gray-50/50 hover:bg-white transition-shadow text-sm"
              />
            </div>
          </div>

          {error && (
            <div className="p-3 bg-red-50 border border-red-100 rounded-xl animate-fade-up">
              <p className="text-sm text-red-600">{error}</p>
            </div>
          )}

          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={handleClose}
              className="px-5 py-2.5 text-gray-600 border border-gray-200 rounded-xl hover:bg-gray-50 transition-all text-sm font-medium"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || !title.trim()}
              className="px-6 py-2.5 bg-[#4f46e5] hover:bg-[#4338ca] text-white rounded-xl shadow-md hover:shadow-lg disabled:bg-gray-300 disabled:shadow-none transition-all duration-200 text-sm font-medium active:scale-[0.98]"
            >
              {submitting ? (
                <span className="flex items-center gap-2">
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Creating...
                </span>
              ) : (
                'Create Meeting'
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
