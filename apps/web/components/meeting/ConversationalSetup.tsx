'use client';

import React, { useEffect, useRef, useState } from 'react';
import {
  X, Send, Sparkles, Loader2, RotateCcw, Check, ClipboardList,
} from 'lucide-react';
import { apiClient } from '@/lib/api-client';

interface ConversationalSetupProps {
  onClose: () => void;
  onCreated: () => void;
}

type Prep = {
  role: string;
  meeting_type: string;
  meeting_goal: string;
  agenda_items: string[];
  risks_or_tensions: string[];
  confidence_notes: string;
};

type ChatMsg = { role: 'user' | 'donna'; text: string };

const STARTER =
  "Tell me about your meeting — what's it for, who's coming, what do you want to walk out with? I'll build the setup as we talk.";

export default function ConversationalSetup({ onClose, onCreated }: ConversationalSetupProps) {
  const [messages, setMessages] = useState<ChatMsg[]>([{ role: 'donna', text: STARTER }]);
  const [input, setInput] = useState('');
  const [prep, setPrep] = useState<Prep | null>(null);
  const [thinking, setThinking] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages.length, thinking]);

  const send = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const text = input.trim();
    if (!text || thinking) return;
    setMessages((prev) => [...prev, { role: 'user', text }]);
    setInput('');
    setThinking(true);
    setError(null);
    try {
      const next = await apiClient.prepMeeting(text, prep || undefined);
      setPrep(next);
      setMessages((prev) => [
        ...prev,
        {
          role: 'donna',
          text:
            next.confidence_notes ||
            "Got it — I've updated the plan on the right. Anything else I should know?",
        },
      ]);
    } catch (err: any) {
      setError(
        err?.response?.data?.detail ||
          'I had trouble processing that — try rephrasing, or switch to Standard Setup.',
      );
    } finally {
      setThinking(false);
    }
  };

  const startOver = () => {
    setMessages([{ role: 'donna', text: STARTER }]);
    setPrep(null);
    setError(null);
  };

  const confirmCreate = async () => {
    if (!prep || creating) return;
    setCreating(true);
    setError(null);
    try {
      const descLines = [
        prep.meeting_type ? `Meeting type: ${prep.meeting_type}` : '',
        ...(prep.agenda_items?.length
          ? ['Agenda:', ...prep.agenda_items.map((a) => `- ${a}`)]
          : []),
        ...(prep.risks_or_tensions?.length
          ? ['', 'Risks & tensions:', ...prep.risks_or_tensions.map((r) => `- ${r}`)]
          : []),
      ].filter(Boolean);

      await apiClient.createMeeting({
        title: prep.meeting_goal || 'Untitled Meeting',
        description: descLines.join('\n') || undefined,
        attendees: [],
        meeting_type: prep.meeting_type || undefined,
        agenda: prep.agenda_items || [],
      });
      onCreated();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to create the meeting.');
      setCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-white overflow-y-auto">
      {/* Top bar */}
      <div className="sticky top-0 bg-white/90 backdrop-blur-sm border-b border-gray-100 z-10">
        <div className="max-w-5xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-600 to-violet-600 flex items-center justify-center">
              <Sparkles className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="font-semibold text-gray-900 text-sm">Conversational Meeting Setup</span>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-8 grid lg:grid-cols-2 gap-6">
        {/* LEFT: conversation */}
        <div className="flex flex-col bg-white rounded-2xl border border-gray-200/80 shadow-card overflow-hidden min-h-[480px]">
          <div className="px-4 py-3 border-b border-gray-100 bg-gray-50/60">
            <p className="text-xs font-bold uppercase tracking-wider text-gray-400">
              Conversation
            </p>
          </div>
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3 max-h-[460px]">
            {messages.map((m, i) =>
              m.role === 'user' ? (
                <div key={i} className="flex justify-end">
                  <div className="bg-indigo-600 text-white rounded-xl rounded-tr-sm px-3.5 py-2 text-sm max-w-[85%]">
                    {m.text}
                  </div>
                </div>
              ) : (
                <div key={i} className="bg-violet-50 border border-violet-100 rounded-xl rounded-tl-sm px-3.5 py-2.5 text-sm text-gray-700 max-w-[90%] leading-relaxed">
                  {m.text}
                </div>
              ),
            )}
            {thinking && (
              <div className="flex items-center gap-2 text-xs text-violet-500 pl-1">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Donna is structuring your meeting…
              </div>
            )}
            {error && (
              <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                {error}
              </p>
            )}
          </div>
          <form onSubmit={send} className="p-3 border-t border-gray-100 flex items-center gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder='e.g. "Strategy sync Monday with ops and brand to lock Q3 pricing"'
              className="flex-1 px-3.5 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-indigo-400 focus:border-indigo-400 outline-none transition-shadow"
              autoFocus
            />
            <button
              type="submit"
              disabled={!input.trim() || thinking}
              className="p-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-200 text-white rounded-xl transition-colors"
            >
              <Send className="w-4 h-4" />
            </button>
          </form>
        </div>

        {/* RIGHT: incrementally built prep preview */}
        <div className="flex flex-col bg-white rounded-2xl border border-gray-200/80 shadow-card overflow-hidden min-h-[480px]">
          <div className="px-4 py-3 border-b border-gray-100 bg-gray-50/60 flex items-center justify-between">
            <p className="text-xs font-bold uppercase tracking-wider text-gray-400">
              Meeting Preview
            </p>
            {prep && (
              <span className="text-[10px] px-2 py-0.5 bg-emerald-50 text-emerald-600 rounded-full font-medium">
                Updating live
              </span>
            )}
          </div>

          <div className="flex-1 p-5">
            {!prep ? (
              <div className="h-full flex flex-col items-center justify-center text-center text-gray-400">
                <ClipboardList className="w-8 h-8 text-gray-200 mb-3" />
                <p className="text-sm font-medium text-gray-500">Nothing here yet</p>
                <p className="text-xs text-gray-400 mt-1 max-w-[220px]">
                  As you describe the meeting, Donna builds the setup here — goal, agenda, and risks.
                </p>
              </div>
            ) : (
              <div className="space-y-4 animate-fade-up">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-widest text-gray-400 mb-1">Meeting Goal</p>
                  <p className="text-base font-semibold text-gray-900">{prep.meeting_goal || '—'}</p>
                </div>
                <div className="flex items-center gap-2">
                  {prep.meeting_type && (
                    <span className="px-2 py-0.5 bg-indigo-50 text-indigo-600 border border-indigo-100 rounded text-[11px] font-medium">
                      {prep.meeting_type}
                    </span>
                  )}
                  {prep.role && (
                    <span className="px-2 py-0.5 bg-gray-50 text-gray-500 border border-gray-200 rounded text-[11px]">
                      You: {prep.role}
                    </span>
                  )}
                </div>
                {prep.agenda_items?.length > 0 && (
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-widest text-gray-400 mb-2">Agenda</p>
                    <ol className="space-y-1.5">
                      {prep.agenda_items.map((a, i) => (
                        <li key={i} className="flex items-start gap-2.5 text-sm text-gray-700">
                          <span className="w-5 h-5 rounded-md bg-indigo-50 text-indigo-600 text-[11px] font-semibold flex items-center justify-center flex-shrink-0 mt-0.5">
                            {i + 1}
                          </span>
                          {a}
                        </li>
                      ))}
                    </ol>
                  </div>
                )}
                {prep.risks_or_tensions?.length > 0 && (
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-widest text-gray-400 mb-2">Risks & Tensions</p>
                    <div className="space-y-1.5">
                      {prep.risks_or_tensions.map((r, i) => (
                        <p key={i} className="text-[13px] text-amber-800/90 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
                          ⚠ {r}
                        </p>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Confirm bar */}
          <div className="p-4 border-t border-gray-100 flex items-center gap-2">
            <button
              onClick={confirmCreate}
              disabled={!prep || creating}
              className="flex-1 flex items-center justify-center gap-2 py-2.5 bg-gray-900 hover:bg-gray-800 disabled:bg-gray-200 disabled:text-gray-400 text-white rounded-xl text-sm font-medium shadow-md hover:shadow-lg disabled:shadow-none transition-all duration-200"
            >
              {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              Confirm &amp; Create Meeting
            </button>
            <button
              onClick={startOver}
              disabled={thinking || creating}
              className="flex items-center gap-1.5 px-4 py-2.5 text-gray-500 border border-gray-200 rounded-xl hover:bg-gray-50 text-sm transition-colors"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Start Over
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
