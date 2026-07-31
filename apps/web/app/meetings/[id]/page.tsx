'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { Sparkles, LayoutDashboard } from 'lucide-react';
import MeetingTimeline from '@/components/meeting/MeetingTimeline';
import ErrorBoundary from '@/components/ErrorBoundary';
import IntelligenceBanner from '@/components/IntelligenceBanner';
import { apiClient } from '@/lib/api-client';

/** Linkable, shareable meeting page — /meetings/<uuid>. */
export default function MeetingPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const meetingId = params?.id;
  const [authChecked, setAuthChecked] = useState(false);

  useEffect(() => {
    if (!apiClient.isAuthenticated()) {
      router.replace('/login');
      return;
    }
    setAuthChecked(true);
  }, [router]);

  if (!authChecked || !meetingId) {
    return <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-primary-50/30" />;
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-primary-50/30">
      <IntelligenceBanner />
      <header className="bg-white/80 backdrop-blur-md border-b border-gray-200/60 sticky top-0 z-40">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2.5 hover:opacity-80 transition-opacity">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-600 to-violet-600 flex items-center justify-center shadow-sm">
              <Sparkles className="w-4 h-4 text-white" />
            </div>
            <span className="font-bold text-gray-900 tracking-tight">Donna</span>
          </Link>
          <Link
            href="/dashboard"
            className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-900 transition-colors"
          >
            <LayoutDashboard className="w-4 h-4" />
            Dashboard
          </Link>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <ErrorBoundary sectionName="Meeting">
          <MeetingTimeline
            meetingId={meetingId}
            onBack={() => router.push('/dashboard')}
          />
        </ErrorBoundary>
      </main>
    </div>
  );
}
