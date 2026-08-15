'use client';

import React, { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  BarChart3,
  Menu,
  X,
  Activity,
  CalendarDays,
  ChevronRight,
  Circle,
  LogOut,
  Mic,
  Home as HomeIcon,
  Settings,
  ClipboardList,
} from 'lucide-react';
import DonnaLogo from '@/components/brand/DonnaLogo';
import AnalyticsDashboard from '@/components/analytics/AnalyticsDashboard';
import MeetingList from '@/components/meeting/MeetingList';
import OpenItemsPanel from '@/components/meeting/OpenItemsPanel';
import CalendarConnect from '@/components/meeting/CalendarConnect';
import ErrorBoundary from '@/components/ErrorBoundary';
import IntelligenceBanner from '@/components/IntelligenceBanner';
import { apiClient, type AuthUser } from '@/lib/api-client';
import type { HealthStatus, WebSocketMessage } from '@/types';

type View = 'meetings' | 'actions' | 'analytics';

const STATUS_CONFIG: Record<string, { dot: string; label: string }> = {
  scheduled: { dot: 'bg-gray-400', label: 'Scheduled' },
  researching: { dot: 'bg-amber-400 animate-pulse', label: 'Researching' },
  ready: { dot: 'bg-emerald-400', label: 'Ready' },
  in_progress: { dot: 'bg-blue-500 animate-pulse', label: 'Live' },
  completed: { dot: 'bg-violet-400', label: 'Done' },
};

export default function Home() {
  const router = useRouter();
  const [activeView, setActiveView] = useState<View>('meetings');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [healthStatus, setHealthStatus] = useState<HealthStatus | null>(null);
  const [recentMeetings, setRecentMeetings] = useState<any[]>([]);
  const [openItemCount, setOpenItemCount] = useState<number | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [sessionSearch, setSessionSearch] = useState('');

  // Auth guard: no session → login page. With a session, hydrate the user
  // (stored copy first for instant paint, then verified against the API).
  useEffect(() => {
    if (!apiClient.isAuthenticated()) {
      router.replace('/login');
      return;
    }
    setUser(apiClient.getStoredUser());
    setAuthChecked(true);
    apiClient
      .me()
      .then(setUser)
      .catch(() => {
        /* 401 interceptor handles redirect */
      });
  }, [router]);

  const handleSignOut = () => {
    apiClient.logout();
    router.replace('/');
  };

  useEffect(() => {
    const checkHealth = async () => {
      try { setHealthStatus(await apiClient.healthCheck()); }
      catch (e) { /* silent */ }
    };
    checkHealth();
    const i = setInterval(checkHealth, 30000);
    return () => clearInterval(i);
  }, []);

  const fetchRecentMeetings = useCallback(async () => {
    try {
      const data = await apiClient.listMeetings(0, 10);
      setRecentMeetings(data.meetings || []);
    } catch (e) { /* silent */ }
  }, []);

  // Fetched here, not only inside the panel: the badge has to be right on
  // arrival, and the panel only mounts once you've already opened the section
  // the badge exists to draw you to.
  const fetchOpenItemCount = useCallback(async () => {
    try {
      const data = await apiClient.listOpenItems();
      setOpenItemCount((data.items || []).length);
    } catch {
      setOpenItemCount(null); // auth-off/demo — show no badge rather than a wrong one
    }
  }, []);

  useEffect(() => {
    fetchOpenItemCount();
    const i = setInterval(fetchOpenItemCount, 30000);
    return () => clearInterval(i);
  }, [fetchOpenItemCount]);

  useEffect(() => {
    fetchRecentMeetings();
    const i = setInterval(fetchRecentMeetings, 15000);
    return () => clearInterval(i);
  }, [fetchRecentMeetings]);

  useEffect(() => {
    let wsHandle: { ws: WebSocket; close: () => void } | null = null;
    try {
      wsHandle = apiClient.createWebSocket(
        () => { fetchRecentMeetings(); },
        () => {}
      );
    } catch (e) { /* silent */ }
    return () => { wsHandle?.close(); };
  }, [fetchRecentMeetings]);

  const navItems = [
    { id: 'meetings' as View, name: 'Meetings', icon: CalendarDays, count: recentMeetings.length },
    // The count is the point of this section — what's still owed across every
    // meeting is the one number a leader wants without opening anything.
    { id: 'actions' as View, name: 'Action Items', icon: ClipboardList, count: openItemCount ?? undefined },
    { id: 'analytics' as View, name: 'Analytics', icon: BarChart3 },
  ];

  // Avoid flashing the dashboard while the auth guard decides
  if (!authChecked) {
    return <div className="min-h-screen bg-gradient-to-br from-gray-50 via-white to-primary-50/30" />;
  }

  return (
    <div className="min-h-screen flex flex-col bg-gradient-to-br from-gray-50 via-white to-primary-50/30">
      <IntelligenceBanner />
      {/* Header — gradient with glass effect */}
      <header className="bg-white/80 backdrop-blur-md border-b border-gray-200/60 sticky top-0 z-50">
        <div className="px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-3">
              <button
                onClick={() => setSidebarOpen(!sidebarOpen)}
                className="lg:hidden p-2 hover:bg-gray-100 rounded-lg transition-colors"
              >
                {sidebarOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
              </button>
              <Link href="/" title="Back to homepage" className="hover:opacity-80 transition-opacity">
                <DonnaLogo size="sm" />
              </Link>
            </div>

            <div className="flex items-center gap-3">
              {/* Health Status Pill */}
              {healthStatus && (
                <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-50 rounded-full border border-gray-200/60">
                  <div className={`w-2 h-2 rounded-full ${
                    healthStatus.status === 'healthy' ? 'bg-emerald-500 shadow-glow-green' :
                    healthStatus.status === 'degraded' ? 'bg-amber-500' : 'bg-red-500 shadow-glow-red'
                  }`} />
                  <span className="text-xs font-medium text-gray-600 hidden sm:inline">
                    {healthStatus.status === 'healthy' ? 'All Systems Online' : healthStatus.status}
                  </span>
                </div>
              )}

              {/* User chip + sign out */}
              {user && (
                <div className="flex items-center gap-2">
                  <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 bg-indigo-50 rounded-full border border-indigo-100">
                    <div className="w-5 h-5 rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center text-white text-[10px] font-bold">
                      {(user.full_name || user.email)[0]?.toUpperCase()}
                    </div>
                    <span className="text-xs font-medium text-indigo-700 max-w-[140px] truncate">
                      {user.full_name || user.email}
                    </span>
                  </div>
                  <Link
                    href="/settings"
                    title="Settings — connect your company database"
                    className="p-2 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
                  >
                    <Settings className="w-4 h-4" />
                  </Link>
                  <button
                    onClick={handleSignOut}
                    title="Sign out"
                    className="p-2 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
                  >
                    <LogOut className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      <div className="flex-1 flex">
        {/* Sidebar */}
        <aside className={`
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
          fixed lg:static inset-y-0 left-0 z-40 w-64
          bg-white/90 backdrop-blur-sm border-r border-gray-200/60
          transition-all duration-300 ease-out
          mt-14 lg:mt-0 flex flex-col
        `}>
          {/* Search (filters recent sessions) */}
          <div className="p-3 pb-0">
            <input
              value={sessionSearch}
              onChange={(e) => setSessionSearch(e.target.value)}
              placeholder="Search meetings..."
              className="w-full px-3.5 py-2 bg-gray-50 border border-gray-200 rounded-xl text-[13px] focus:ring-2 focus:ring-indigo-400 focus:border-indigo-400 outline-none transition-shadow"
            />
          </div>

          {/* Nav Links */}
          <nav className="p-3 space-y-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeView === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => {
                    setActiveView(item.id);
                    setSidebarOpen(false);
                  }}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-xl transition-all duration-200 text-sm group ${
                    isActive
                      ? 'bg-gradient-to-r from-primary-50 to-primary-100/50 text-primary-700 font-semibold shadow-sm'
                      : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                  }`}
                >
                  <Icon className={`w-[18px] h-[18px] transition-transform duration-200 ${isActive ? '' : 'group-hover:scale-110'}`} />
                  <span className="flex-1">{item.name}</span>
                  {item.count ? (
                    <span className={`text-xs px-1.5 py-0.5 rounded-md ${
                      isActive ? 'bg-primary-200/50 text-primary-700' : 'bg-gray-100 text-gray-500'
                    }`}>
                      {item.count}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </nav>

          {/* Integrations */}
          <CalendarConnect />

          {/* Divider */}
          <div className="mx-4 border-t border-gray-100" />

          {/* Recent Meetings */}
          <div className="flex-1 overflow-y-auto">
            <div className="p-3">
              <h3 className="text-[10px] font-bold text-gray-400 uppercase tracking-widest px-3 mb-2">
                Recent Sessions
              </h3>
              {recentMeetings.length > 0 ? (
                <div className="space-y-0.5">
                  {recentMeetings
                    .filter((m) =>
                      !sessionSearch.trim() ||
                      m.title?.toLowerCase().includes(sessionSearch.trim().toLowerCase()),
                    )
                    .map((m) => {
                    const cfg = STATUS_CONFIG[m.status] || STATUS_CONFIG.scheduled;
                    const isSelected = false;
                    return (
                      <button
                        key={m.id}
                        onClick={() => {
                          setSidebarOpen(false);
                          router.push(`/meetings/${m.id}`);
                        }}
                        className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-left transition-all duration-200 group ${
                          isSelected
                            ? 'bg-primary-50 text-primary-700 shadow-sm'
                            : 'text-gray-600 hover:bg-gray-50'
                        }`}
                      >
                        <div className={`w-2 h-2 rounded-full flex-shrink-0 ${cfg.dot}`} />
                        <span className="text-[13px] truncate flex-1">{m.title}</span>
                        <ChevronRight className={`w-3.5 h-3.5 flex-shrink-0 transition-all duration-200 ${
                          isSelected ? 'text-primary-500 translate-x-0' : 'text-gray-300 -translate-x-1 opacity-0 group-hover:translate-x-0 group-hover:opacity-100'
                        }`} />
                      </button>
                    );
                  })}
                </div>
              ) : (
                <div className="text-center py-6">
                  <Circle className="w-8 h-8 text-gray-200 mx-auto mb-2" />
                  <p className="text-xs text-gray-400">No meetings yet</p>
                </div>
              )}
            </div>
          </div>

          {/* Footer */}
          <div className="p-3 border-t border-gray-100/80 space-y-1">
            <Link
              href="/assistant"
              className="w-full flex items-center gap-3 px-4 py-2 rounded-xl text-sm text-gray-600 hover:bg-gray-50 hover:text-gray-900 transition-colors"
            >
              <Mic className="w-[18px] h-[18px]" />
              Talk to Donna
            </Link>
            <Link
              href="/"
              className="w-full flex items-center gap-3 px-4 py-2 rounded-xl text-sm text-gray-600 hover:bg-gray-50 hover:text-gray-900 transition-colors"
            >
              <HomeIcon className="w-[18px] h-[18px]" />
              Homepage
            </Link>
            <div className="flex items-center gap-2 px-4 pt-1">
              <div className="w-6 h-6 bg-gradient-to-br from-primary-100 to-primary-200 rounded-md flex items-center justify-center">
                <Activity className="w-3 h-3 text-primary-600" />
              </div>
              <div>
                <p className="text-[11px] font-medium text-gray-600">Donna v2.0</p>
                <p className="text-[10px] text-gray-400">She already knew.</p>
              </div>
            </div>
          </div>
        </aside>

        {/* Mobile overlay */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 bg-black/30 backdrop-blur-sm z-30 lg:hidden transition-opacity"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* Main Content */}
        <main className="flex-1 overflow-auto">
          <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
            {/* Meetings View */}
            {activeView === 'meetings' && (
              <ErrorBoundary sectionName="Meetings">
                <div className="animate-fade-up">
                  <MeetingList
                    onSelectMeeting={(id) => router.push(`/meetings/${id}`)}
                  />
                </div>
              </ErrorBoundary>
            )}

            {/* Action Items View — cross-meeting commitments, on their own
                screen rather than stacked above the meeting list where a long
                list pushed the meetings off the fold. */}
            {activeView === 'actions' && (
              <div className="space-y-6 animate-fade-up">
                <div>
                  <h2 className="text-2xl font-bold text-gray-900 mb-1">Action items</h2>
                  <p className="text-gray-500">
                    Everything still owed across your meetings, newest first.
                  </p>
                </div>
                <ErrorBoundary sectionName="Action items">
                  <OpenItemsPanel
                    variant="page"
                    onCountChange={setOpenItemCount}
                  />
                </ErrorBoundary>
              </div>
            )}

            {/* Analytics View */}
            {activeView === 'analytics' && (
              <div className="space-y-6 animate-fade-up">
                <div>
                  <h2 className="text-2xl font-bold text-gray-900 mb-1">Analytics</h2>
                  <p className="text-gray-500">Monitor system performance and usage</p>
                </div>
                <ErrorBoundary sectionName="Analytics">
                  <AnalyticsDashboard />
                </ErrorBoundary>
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
