'use client';

import React, { useEffect, useState } from 'react';
import { CheckCircle2, ClipboardList } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api-client';

interface Props {
  /** "card" sits above another list and stays short. "page" owns the screen. */
  variant?: 'card' | 'page';
  /** Reports the count upward so the nav badge can show what's owed. */
  onCountChange?: (n: number) => void;
}

/**
 * Cross-meeting open action items — the "what's still owed" view.
 * Click an item to jump to its meeting; check it off to mark done.
 *
 * Two variants because the same list plays two roles. As a card it is a
 * reminder stacked above the meeting list, so it stays capped and silent when
 * empty. As a page it is the destination, so it fills the screen, shows every
 * item, and says so when there is nothing left — a section reached deliberately
 * that renders nothing looks broken, where the same emptiness inline is just
 * absence.
 */
export default function OpenItemsPanel({ variant = 'card', onCountChange }: Props) {
  const router = useRouter();
  const [items, setItems] = useState<any[]>([]);
  const [loaded, setLoaded] = useState(false);

  const fetchItems = async () => {
    try {
      const data = await apiClient.listOpenItems();
      const next = data.items || [];
      setItems(next);
      onCountChange?.(next.length);
    } catch {
      // auth-off/demo mode or transient error — hide the panel
    } finally {
      setLoaded(true);
    }
  };

  useEffect(() => {
    fetchItems();
  }, []);

  const handleDone = async (item: any, e: React.MouseEvent) => {
    e.stopPropagation();
    setItems((prev) => prev.filter((i) => i.id !== item.id));
    try {
      await apiClient.updateActionItemStatus(item.meeting_id, item.id, 'done');
      onCountChange?.(Math.max(0, items.length - 1));
    } catch {
      fetchItems();
    }
  };

  const isPage = variant === 'page';

  if (!loaded) {
    return isPage ? (
      <div className="bg-white rounded-xl border border-gray-200/60 p-10 text-center text-sm text-gray-400">
        Loading…
      </div>
    ) : null;
  }

  if (items.length === 0) {
    // Silent inline; explicit on its own page.
    if (!isPage) return null;
    return (
      <div className="bg-white rounded-xl border border-gray-200/60 py-14 text-center">
        <div className="w-12 h-12 rounded-2xl bg-emerald-50 grid place-items-center mx-auto mb-3">
          <CheckCircle2 className="w-6 h-6 text-emerald-500" />
        </div>
        <h3 className="text-base font-semibold text-gray-900 mb-1">Nothing outstanding</h3>
        <p className="text-sm text-gray-500 max-w-sm mx-auto">
          Action items Donna captures during meetings land here until they're done.
        </p>
      </div>
    );
  }

  return (
    <div
      className={[
        'bg-white rounded-xl border border-gray-200/60 shadow-card overflow-hidden animate-fade-up',
        isPage ? '' : 'mb-6',
      ].join(' ')}
    >
      {!isPage && (
        <div className="px-4 py-3 border-b border-gray-100 bg-gradient-to-r from-sky-50/60 to-white flex items-center gap-2">
          <ClipboardList className="w-4 h-4 text-sky-600" />
          <h3 className="text-xs font-bold text-sky-700 uppercase tracking-wider">
            Open Action Items ({items.length})
          </h3>
        </div>
      )}
      {/* Capped inline so it can't push the meeting list off the fold; uncapped
          on its own page, where scrolling the list is the whole point. */}
      <div className={isPage ? 'divide-y divide-gray-50' : 'divide-y divide-gray-50 max-h-64 overflow-y-auto'}>
        {items.map((item) => (
          <div
            key={item.id}
            onClick={() => router.push(`/meetings/${item.meeting_id}`)}
            className={[
              'flex items-center gap-3 hover:bg-gray-50/70 cursor-pointer transition-colors',
              isPage ? 'px-5 py-3.5' : 'px-4 py-2.5',
            ].join(' ')}
          >
            <button
              onClick={(e) => handleDone(item, e)}
              title="Mark done"
              className="flex-shrink-0 text-gray-300 hover:text-emerald-500 transition-colors"
            >
              <CheckCircle2 className="w-5 h-5" />
            </button>
            <div className="min-w-0 flex-1">
              <p className={isPage ? 'text-[15px] text-gray-800' : 'text-sm text-gray-800 truncate'}>
                {item.description}
              </p>
              <p className="text-[11px] text-gray-400 truncate">
                {item.meeting_title}
                {item.assignee ? ` · ${item.assignee}` : ''}
                {item.deadline ? ` · due ${item.deadline.slice(0, 10)}` : ''}
              </p>
            </div>
            {item.priority === 'high' && (
              <span className="flex-shrink-0 px-1.5 py-0.5 bg-red-100 text-red-700 rounded text-[10px] font-medium">
                high
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
