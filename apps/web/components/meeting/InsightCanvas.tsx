'use client';

/**
 * InsightCanvas — one insight, in full, with its thread.
 *
 * The insight list is a stream: reverse-chronological cards, each clipped to a
 * few lines so the panel stays scannable. That works for noticing something and
 * fails for reading it. A finding that ended "CoreScale spun out of..." was
 * unusable precisely where it got interesting, and the two other cards about
 * the same vendor sat forty pixels apart with nothing connecting them.
 *
 * So: the card stays a glance, and this is the read. Opening one shows the
 * whole retrieved passage and gathers the other insights from the same thread —
 * same document, same vocabulary, same moment in the conversation — so a topic
 * can be examined as a topic rather than reassembled by scrolling.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { X, Loader2, FileText, ArrowLeft, Link2 } from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import NudgeCard from './NudgeCard';

interface Props {
  meetingId: string;
  nudgeId: string;
  onClose: () => void;
  /** Follow a related insight without leaving the canvas. */
  onOpenRelated?: (nudgeId: string) => void;
  onAskDonna?: (prompt: string) => void;
  onLogDecision?: (nudgeId: string, content: string) => void;
  onDismiss?: (nudgeId: string) => void;
  onPin?: (nudgeId: string) => void;
  onBack?: () => void;
}

export default function InsightCanvas({
  meetingId,
  nudgeId,
  onClose,
  onOpenRelated,
  onAskDonna,
  onLogDecision,
  onDismiss,
  onPin,
  onBack,
}: Props) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nudge, setNudge] = useState<any | null>(null);
  const [related, setRelated] = useState<any[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.getNudgeThread(meetingId, nudgeId);
      setNudge(data.nudge);
      setRelated(data.related || []);
    } catch (e: any) {
      console.error('Failed to load insight:', e);
      setError(e?.response?.data?.detail ?? 'Could not load this insight.');
    } finally {
      setLoading(false);
    }
  }, [meetingId, nudgeId]);

  useEffect(() => {
    load();
  }, [load]);

  // Escape closes, which is what every other overlay in the product does.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const data = nudge?.source_data || {};
  const docTitle =
    data.document_title ||
    data.meeting_title ||
    (data.document_id ? `Document ${String(data.document_id).slice(0, 8)}` : null);
  const section = Array.isArray(data.section_path)
    ? data.section_path.filter(Boolean).join(' › ')
    : data.section_path || null;

  // full_content is the untruncated passage; content is the card snippet.
  const body: string = nudge?.full_content || nudge?.content || '';

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="absolute inset-0 bg-gray-900/20 backdrop-blur-[2px]"
        onClick={onClose}
      />

      <aside className="relative w-full max-w-2xl bg-white h-full shadow-2xl flex flex-col animate-slide-in">
        <header className="px-5 py-4 border-b border-gray-100 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 min-w-0">
            {onBack && (
              <button
                onClick={onBack}
                className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors flex-shrink-0"
                title="Back to insights"
              >
                <ArrowLeft className="w-4 h-4" />
              </button>
            )}
            <h2 className="text-base font-semibold text-gray-900 truncate">
              {loading ? 'Loading…' : nudge?.title || 'Insight'}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors flex-shrink-0"
            title="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto">
          {loading && (
            <div className="p-10 grid place-items-center text-gray-400">
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
          )}

          {error && !loading && (
            <div className="p-6">
              <p className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                {error}
              </p>
            </div>
          )}

          {!loading && !error && nudge && (
            <>
              <section className="px-5 py-5">
                {(docTitle || section) && (
                  <p className="flex items-center gap-1.5 text-[11px] text-gray-500 mb-3">
                    <FileText className="w-3 h-3 flex-shrink-0" />
                    <span className="truncate">
                      {docTitle}
                      {section ? ` · ${section}` : ''}
                      {data.page_number ? ` · p.${data.page_number}` : ''}
                    </span>
                  </p>
                )}

                {/* whitespace-pre-wrap: retrieved passages carry their own
                    line breaks, and collapsing them turns a table or a list
                    into a wall of text. */}
                <p className="text-[15px] leading-relaxed text-gray-800 whitespace-pre-wrap">
                  {body}
                </p>

                {data.quote && (
                  <blockquote className="mt-4 border-l-2 border-gray-200 pl-3 text-sm text-gray-500 italic">
                    &ldquo;{data.quote}&rdquo;
                  </blockquote>
                )}

                {onAskDonna && (
                  <button
                    onClick={() =>
                      onAskDonna(
                        `About this insight — "${nudge.title}": ${body.slice(0, 400)}\n\nWhat should I take from this?`,
                      )
                    }
                    className="mt-5 inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-xs font-medium transition-colors"
                  >
                    Ask Donna about this
                  </button>
                )}
              </section>

              <section className="border-t border-gray-100 px-5 py-4 bg-gray-50/50">
                <h3 className="flex items-center gap-1.5 text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-3">
                  <Link2 className="w-3 h-3" />
                  {related.length > 0
                    ? `Related in this discussion (${related.length})`
                    : 'Related in this discussion'}
                </h3>

                {related.length === 0 ? (
                  <p className="text-xs text-gray-400 py-2">
                    Nothing else has come up on this yet.
                  </p>
                ) : (
                  <div className="space-y-2.5">
                    {related.map((r) => (
                      <button
                        key={r.id}
                        onClick={() => onOpenRelated?.(r.id)}
                        className="w-full text-left"
                      >
                        <NudgeCard
                          nudge={r}
                          compact
                          onLogDecision={onLogDecision}
                          onDismiss={onDismiss}
                          onPin={onPin}
                        />
                      </button>
                    ))}
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
