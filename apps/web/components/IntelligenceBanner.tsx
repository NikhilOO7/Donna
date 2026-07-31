'use client';

import React, { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { apiClient } from '@/lib/api-client';

/**
 * App-wide "intelligence degraded" banner.
 *
 * Driven by the backend's circuit breakers: when the OpenAI breaker is
 * open (provider outage, exhausted credits, sustained errors), every AI
 * feature is affected at once — say it once, at the top, instead of
 * letting each feature fail cryptically.
 */
export default function IntelligenceBanner() {
  const [degraded, setDegraded] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    const check = async () => {
      try {
        const health: any = await apiClient.healthCheck();
        const breakers = health?.circuit_breakers || {};
        const openaiState = String(breakers.openai || 'CLOSED').toUpperCase();
        if (!mounted) return;
        if (openaiState !== 'CLOSED') {
          setDegraded(
            'Donna’s intelligence is temporarily degraded — the AI provider is unreachable. ' +
            'Meetings, transcripts, and documents still work; insights, research, and summaries will resume automatically.',
          );
        } else {
          setDegraded(null);
        }
      } catch {
        /* backend unreachable — other UI already handles that */
      }
    };
    check();
    const i = setInterval(check, 30000);
    return () => { mounted = false; clearInterval(i); };
  }, []);

  if (!degraded) return null;

  return (
    <div className="bg-amber-50 border-b border-amber-200">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-2.5 flex items-center gap-2.5">
        <AlertTriangle className="w-4 h-4 text-amber-500 flex-shrink-0" />
        <p className="text-[13px] text-amber-800">{degraded}</p>
      </div>
    </div>
  );
}
