'use client';

import React, { useState, useEffect } from 'react';
import { X, Calendar, Users, Sparkles, UploadCloud } from 'lucide-react';
import { apiClient } from '@/lib/api-client';

interface CreateMeetingModalProps {
  onClose: () => void;
  onCreated: () => void;
}

const MEETING_TYPES = [
  'Strategy Planning',
  'Design Sync',
  'Product Review',
  'Engineering Sync',
  'Go-to-Market Planning',
  'Vendor / Partner Review',
  'Other',
];

export default function CreateMeetingModal({ onClose, onCreated }: CreateMeetingModalProps) {
  const [title, setTitle] = useState('');
  const [meetingType, setMeetingType] = useState('');
  const [description, setDescription] = useState('');
  const [scheduledAt, setScheduledAt] = useState('');
  const [attendeesText, setAttendeesText] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [visible, setVisible] = useState(false);

  // Smart Fill — free text → structured prep via the Donna prep agent
  const [smartInput, setSmartInput] = useState('');
  const [smartBusy, setSmartBusy] = useState(false);
  const [smartNote, setSmartNote] = useState<string | null>(null);
  const [smartRisks, setSmartRisks] = useState<string[]>([]);
  const [agendaItems, setAgendaItems] = useState<string[]>([]);

  const handleSmartFill = async () => {
    const input = smartInput.trim();
    if (!input || smartBusy) return;
    setSmartBusy(true);
    setError('');
    try {
      const prep = await apiClient.prepMeeting(input);
      if (prep.meeting_goal) setTitle(prep.meeting_goal);
      if (prep.meeting_type) {
        setMeetingType(
          MEETING_TYPES.includes(prep.meeting_type) ? prep.meeting_type : 'Other',
        );
      }
      const descLines = [
        ...(prep.agenda_items?.length
          ? ['Agenda:', ...prep.agenda_items.map((a) => `- ${a}`)]
          : []),
        ...(prep.risks_or_tensions?.length
          ? ['', 'Risks & tensions:', ...prep.risks_or_tensions.map((r) => `- ${r}`)]
          : []),
      ];
      if (descLines.length) setDescription(descLines.join('\n'));
      setSmartRisks(prep.risks_or_tensions || []);
      setAgendaItems(prep.agenda_items || []);
      setSmartNote(prep.confidence_notes || null);
    } catch (err: any) {
      setError(
        err?.response?.data?.detail ||
          'Smart fill is unavailable right now — you can still fill the form manually.',
      );
    } finally {
      setSmartBusy(false);
    }
  };

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
    if (!title.trim()) { setError('Meeting name is required'); return; }

    setSubmitting(true);
    setError('');

    try {
      const attendees = attendeesText
        .split(',')
        .map((a) => a.trim())
        .filter(Boolean)
        .map((email) => ({ email }));

      // Meeting type rides in the description until it becomes a structured
      // field — the research agents read it, and the list surfaces it as a tag.
      const desc = [
        meetingType ? `Meeting type: ${meetingType}` : '',
        description.trim(),
      ].filter(Boolean).join('\n');

      await apiClient.createMeeting({
        title: title.trim(),
        description: desc || undefined,
        scheduled_at: scheduledAt || undefined,
        attendees,
        meeting_type: meetingType || undefined,
        agenda: agendaItems,
      });

      onCreated();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create meeting');
    } finally {
      setSubmitting(false);
    }
  };

  const inputClasses =
    'w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-shadow bg-gray-50/50 hover:bg-white outline-none';

  return (
    <div className={`fixed inset-0 z-50 flex items-center justify-center transition-all duration-300 overflow-y-auto py-8 ${
      visible ? 'bg-black/40 backdrop-blur-sm' : 'bg-black/0'
    }`}>
      <div className={`bg-white rounded-2xl shadow-elevated w-full max-w-lg mx-4 my-auto transition-all duration-300 ${
        visible ? 'scale-100 opacity-100 translate-y-0' : 'scale-95 opacity-0 translate-y-4'
      }`}>
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-gray-100">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-indigo-600 to-violet-600 rounded-xl flex items-center justify-center shadow-sm">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Set Up Your Meeting</h2>
              <p className="text-xs text-gray-500">Donna will research and prepare intelligence</p>
            </div>
          </div>
          <button
            onClick={handleClose}
            className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-xl transition-all"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form — field order mirrors the product spec */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* Smart Fill — describe it in a sentence, Donna structures it */}
          <div className="p-4 bg-gradient-to-br from-violet-50/70 to-indigo-50/50 border border-violet-100 rounded-xl">
            <label className="flex items-center gap-1.5 text-sm font-medium text-violet-800 mb-1.5">
              <Sparkles className="w-3.5 h-3.5" />
              Smart Fill
            </label>
            <div className="flex items-start gap-2">
              <textarea
                value={smartInput}
                onChange={(e) => setSmartInput(e.target.value)}
                placeholder={'Describe your meeting in a sentence — e.g. "I\'m prepping a session with the engineers to make sure we ship the component on time. I\'m in product design."'}
                rows={2}
                className="flex-1 px-3.5 py-2.5 bg-white border border-violet-200/70 rounded-xl text-sm focus:ring-2 focus:ring-violet-400 focus:border-violet-400 outline-none resize-none transition-shadow"
              />
              <button
                type="button"
                onClick={handleSmartFill}
                disabled={!smartInput.trim() || smartBusy}
                className="px-4 py-2.5 bg-violet-600 hover:bg-violet-700 disabled:bg-gray-200 disabled:text-gray-400 text-white rounded-xl text-sm font-medium transition-colors flex-shrink-0"
              >
                {smartBusy ? (
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin block" />
                ) : (
                  'Fill'
                )}
              </button>
            </div>
            {smartNote && (
              <p className="text-[11px] text-violet-500 mt-2">
                Donna: {smartNote} — review and edit anything below before creating.
              </p>
            )}
            {smartRisks.length > 0 && (
              <div className="mt-2 space-y-1">
                {smartRisks.map((r) => (
                  <p key={r} className="text-[11px] text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-2.5 py-1.5">
                    ⚠ Tension to address: {r}
                  </p>
                ))}
              </div>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Meeting Name *
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Q2 Strategic Planning"
              className={inputClasses}
              autoFocus
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Meeting Type
            </label>
            <select
              value={meetingType}
              onChange={(e) => setMeetingType(e.target.value)}
              className={`${inputClasses} ${meetingType ? 'text-gray-900' : 'text-gray-400'}`}
            >
              <option value="">Select a meeting type</option>
              {MEETING_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                <Users className="w-3.5 h-3.5 inline mr-1 text-gray-400" />
                Expected Participants
              </label>
              <input
                type="text"
                value={attendeesText}
                onChange={(e) => setAttendeesText(e.target.value)}
                placeholder="alice@co.com, bob@co.com"
                className={`${inputClasses} text-sm`}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                <Calendar className="w-3.5 h-3.5 inline mr-1 text-gray-400" />
                Meeting Date
              </label>
              <input
                type="datetime-local"
                value={scheduledAt}
                onChange={(e) => setScheduledAt(e.target.value)}
                className={`${inputClasses} text-sm`}
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Meeting Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What will you discuss in this meeting? Any specific goals or agenda items?"
              rows={3}
              className={`${inputClasses} resize-none`}
            />
            <p className="mt-1.5 text-[11px] text-gray-400">
              This helps Donna prepare relevant insights during your meeting.
            </p>
          </div>

          {/* Meeting materials hint — uploads live in the meeting's Knowledge Base step */}
          <div className="flex items-start gap-3 p-3.5 bg-indigo-50/60 border border-indigo-100 rounded-xl">
            <UploadCloud className="w-4 h-4 text-indigo-500 flex-shrink-0 mt-0.5" />
            <p className="text-[12px] text-indigo-900/70 leading-relaxed">
              <span className="font-medium">Meeting materials</span> — after setup you can
              upload decks, PDFs, docs, and data in the Knowledge Base step; Donna cites
              them during the meeting.
            </p>
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
              className="px-6 py-2.5 bg-gray-900 hover:bg-gray-800 text-white rounded-xl shadow-md hover:shadow-lg disabled:bg-gray-300 disabled:shadow-none transition-all duration-200 text-sm font-medium active:scale-[0.98]"
            >
              {submitting ? (
                <span className="flex items-center gap-2">
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Creating...
                </span>
              ) : (
                'Continue to Setup'
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
