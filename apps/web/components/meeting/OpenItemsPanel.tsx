'use client';

import React, { useEffect, useState } from 'react';
import { CheckCircle2, ClipboardList } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api-client';

/**
 * Cross-meeting open action items — the dashboard "what's still owed" view.
 * Click an item to jump to its meeting; check it off to mark done.
 */
export default function OpenItemsPanel() {
  const router = useRouter();
  const [items, setItems] = useState<any[]>([]);
  const [loaded, setLoaded] = useState(false);

  const fetchItems = async () => {
    try {
      const data = await apiClient.listOpenItems();
      setItems(data.items || []);
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
    } catch {
      fetchItems();
    }
  };

  if (!loaded || items.length === 0) return null;

  return (
    <div className="mb-6 bg-white rounded-xl border border-gray-200/60 shadow-card overflow-hidden animate-fade-up">
      <div className="px-4 py-3 border-b border-gray-100 bg-gradient-to-r from-sky-50/60 to-white flex items-center gap-2">
        <ClipboardList className="w-4 h-4 text-sky-600" />
        <h3 className="text-xs font-bold text-sky-700 uppercase tracking-wider">
          Open Action Items ({items.length})
        </h3>
      </div>
      <div className="divide-y divide-gray-50 max-h-64 overflow-y-auto">
        {items.map((item) => (
          <div
            key={item.id}
            onClick={() => router.push(`/meetings/${item.meeting_id}`)}
            className="px-4 py-2.5 flex items-center gap-3 hover:bg-gray-50/70 cursor-pointer transition-colors"
          >
            <button
              onClick={(e) => handleDone(item, e)}
              title="Mark done"
              className="flex-shrink-0 text-gray-300 hover:text-emerald-500 transition-colors"
            >
              <CheckCircle2 className="w-5 h-5" />
            </button>
            <div className="min-w-0 flex-1">
              <p className="text-sm text-gray-800 truncate">{item.description}</p>
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
