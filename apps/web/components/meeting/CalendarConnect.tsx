'use client';

import React, { useEffect, useState } from 'react';
import { Calendar, Check, Loader2, RefreshCw } from 'lucide-react';
import { apiClient } from '@/lib/api-client';

/**
 * Google Calendar connect/sync control (sidebar).
 * Hidden entirely when the server has no Google OAuth credentials.
 */
export default function CalendarConnect() {
  const [state, setState] = useState<'hidden' | 'connect' | 'ready' | 'busy'>('hidden');
  const [lastSync, setLastSync] = useState<string | null>(null);

  useEffect(() => {
    apiClient
      .googleCalendarStatus()
      .then((s) => {
        if (!s.configured) return;
        setState(s.connected ? 'ready' : 'connect');
      })
      .catch(() => {});
  }, []);

  const handleClick = async () => {
    if (state === 'connect') {
      try {
        const { url } = await apiClient.googleCalendarAuthUrl();
        window.location.href = url;
      } catch (err) {
        console.error('Google auth URL failed:', err);
      }
      return;
    }
    if (state === 'ready') {
      setState('busy');
      try {
        const result = await apiClient.googleCalendarSync();
        setLastSync(`${result.created} imported`);
      } catch (err) {
        console.error('Calendar sync failed:', err);
        setLastSync('sync failed');
      } finally {
        setState('ready');
      }
    }
  };

  if (state === 'hidden') return null;

  return (
    <div className="p-3">
      <button
        onClick={handleClick}
        disabled={state === 'busy'}
        className="w-full flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm text-gray-600 hover:bg-gray-50 hover:text-gray-900 transition-all duration-200 border border-dashed border-gray-200"
      >
        {state === 'busy' ? (
          <Loader2 className="w-[18px] h-[18px] animate-spin text-indigo-500" />
        ) : state === 'ready' ? (
          <RefreshCw className="w-[18px] h-[18px] text-indigo-500" />
        ) : (
          <Calendar className="w-[18px] h-[18px]" />
        )}
        <span className="flex-1 text-left">
          {state === 'connect' ? 'Connect Google Calendar' : 'Sync calendar'}
        </span>
        {lastSync && (
          <span className="flex items-center gap-1 text-[10px] text-emerald-600">
            <Check className="w-3 h-3" />
            {lastSync}
          </span>
        )}
      </button>
    </div>
  );
}
