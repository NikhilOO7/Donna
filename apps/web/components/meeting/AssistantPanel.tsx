'use client';

import React, { useEffect, useRef, useState } from 'react';
import { Send, Sparkles, Loader2, FileText } from 'lucide-react';
import { apiClient } from '@/lib/api-client';

interface AssistantPanelProps {
  meetingId: string;
  /** Externally injected prompt (e.g. "Ask Donna" on an insight card). */
  pendingPrompt?: string | null;
  onPromptConsumed?: () => void;
}

type Message = {
  role: 'user' | 'donna';
  text: string;
  sources?: any[];
  confidence?: number | null;
};

export default function AssistantPanel({
  meetingId,
  pendingPrompt,
  onPromptConsumed,
}: AssistantPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [thinking, setThinking] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages.length, thinking]);

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || thinking) return;
    setMessages((prev) => [...prev, { role: 'user', text: q }]);
    setInput('');
    setThinking(true);
    try {
      const result = await apiClient.queryMeeting(meetingId, q);
      setMessages((prev) => [
        ...prev,
        {
          role: 'donna',
          text: result.answer || 'I could not find anything on that.',
          sources: result.sources || [],
          confidence: result.confidence,
        },
      ]);
    } catch (error) {
      console.error('Ask Donna failed:', error);
      setMessages((prev) => [
        ...prev,
        {
          role: 'donna',
          text: "Sorry — I couldn't process that just now. Try again in a moment.",
        },
      ]);
    } finally {
      setThinking(false);
    }
  };

  // Consume prompts injected from insight cards ("Ask Donna")
  useEffect(() => {
    if (pendingPrompt) {
      onPromptConsumed?.();
      ask(pendingPrompt);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingPrompt]);

  return (
    <div className="flex flex-col h-full bg-white rounded-xl border border-gray-200/60 shadow-card overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 bg-gradient-to-r from-violet-50/60 to-white flex items-center gap-2">
        <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-violet-500 to-indigo-500 flex items-center justify-center">
          <Sparkles className="w-3.5 h-3.5 text-white" />
        </div>
        <h3 className="text-xs font-bold text-violet-700 uppercase tracking-wider">
          Donna Assistant
        </h3>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-3 min-h-[180px]">
        {/* Greeting bubble — mirrors the PDF's assistant panel */}
        <div className="bg-violet-50 border border-violet-100 rounded-xl rounded-tl-sm p-3 text-[13px] text-gray-700 leading-relaxed">
          Hi! I&apos;m Donna, your AI meeting assistant. I can help you analyze
          insights, generate summaries, or answer questions about the discussion.
        </div>

        {messages.map((m, i) =>
          m.role === 'user' ? (
            <div key={i} className="flex justify-end">
              <div className="bg-indigo-600 text-white rounded-xl rounded-tr-sm px-3 py-2 text-[13px] max-w-[85%]">
                {m.text}
              </div>
            </div>
          ) : (
            <div key={i} className="bg-violet-50 border border-violet-100 rounded-xl rounded-tl-sm p-3 text-[13px] text-gray-700 leading-relaxed max-w-[95%]">
              <p className="whitespace-pre-wrap">{m.text}</p>
              {typeof m.confidence === 'number' && m.confidence > 0 && (
                <p className="mt-1.5 text-[10px] font-medium text-violet-400">
                  {Math.round(m.confidence * 100)}% confidence · {m.sources?.length || 0} source{(m.sources?.length || 0) !== 1 ? 's' : ''}
                </p>
              )}
              {m.sources && m.sources.length > 0 && (
                <div className="mt-2 pt-2 border-t border-violet-100 space-y-1">
                  {m.sources.slice(0, 3).map((s: any, j: number) => (
                    <p key={j} className="flex items-center gap-1.5 text-[11px] text-violet-600 truncate">
                      <FileText className="w-3 h-3 flex-shrink-0" />
                      <span className="truncate">
                        {s.citation ||
                          s.filename ||
                          s.document_title ||
                          (s.source_type === 'meeting_memory'
                            ? `Meeting: ${s.meeting_title || 'previous meeting'}`
                            : `Document ${String(s.document_id || '').slice(0, 8)}`)}
                      </span>
                    </p>
                  ))}
                </div>
              )}
            </div>
          ),
        )}

        {thinking && (
          <div className="flex items-center gap-2 text-[12px] text-violet-500 pl-1">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            Donna is thinking...
          </div>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(input);
        }}
        className="p-3 border-t border-gray-100 flex items-center gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask Donna..."
          className="flex-1 px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-[13px] focus:ring-2 focus:ring-violet-400 focus:border-violet-400 outline-none"
        />
        <button
          type="submit"
          disabled={!input.trim() || thinking}
          className="p-2 bg-violet-600 hover:bg-violet-700 disabled:bg-gray-200 text-white rounded-lg transition-colors"
        >
          <Send className="w-4 h-4" />
        </button>
      </form>
    </div>
  );
}
