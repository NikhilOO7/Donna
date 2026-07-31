'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Sparkles, Loader2, ArrowRight } from 'lucide-react';
import { apiClient } from '@/lib/api-client';

type Tab = 'signin' | 'signup';

export default function LoginPage() {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>('signin');
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Already signed in → straight to the dashboard
  useEffect(() => {
    if (apiClient.isAuthenticated()) {
      router.replace('/dashboard');
    }
  }, [router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (tab === 'signup' && password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }

    setBusy(true);
    try {
      if (tab === 'signup') {
        await apiClient.register(email, password, fullName);
      } else {
        await apiClient.login(email, password);
      }
      router.replace('/dashboard');
    } catch (err: any) {
      const status = err?.response?.status;
      const detail = err?.response?.data?.detail;
      if (status === 409) {
        setError('An account with this email already exists — try signing in.');
      } else if (status === 401) {
        setError('Invalid email or password.');
      } else if (status === 422) {
        setError('Please enter a valid email and a password of at least 8 characters.');
      } else {
        setError(typeof detail === 'string' ? detail : 'Something went wrong. Please try again.');
      }
    } finally {
      setBusy(false);
    }
  };

  const tabButton = (t: Tab, label: string) => (
    <button
      type="button"
      onClick={() => { setTab(t); setError(null); }}
      className={`flex-1 py-2 text-sm font-medium rounded-lg transition-all duration-200 ${
        tab === t
          ? 'bg-white text-gray-900 shadow-sm'
          : 'text-gray-500 hover:text-gray-700'
      }`}
    >
      {label}
    </button>
  );

  return (
    <main className="min-h-screen bg-gradient-to-b from-indigo-50/70 via-white to-white flex flex-col">
      {/* Minimal nav */}
      <nav className="h-16 flex items-center px-6 max-w-6xl mx-auto w-full">
        <Link href="/" className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-600 to-violet-600 flex items-center justify-center shadow-sm">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <span className="font-bold text-gray-900 text-lg tracking-tight">Donna</span>
        </Link>
      </nav>

      <div className="flex-1 flex items-center justify-center px-6 pb-20">
        <div className="w-full max-w-md">
          <div className="text-center mb-8">
            <h1 className="text-2xl font-bold text-gray-900 mb-2">
              {tab === 'signin' ? 'Welcome back' : 'Create your account'}
            </h1>
            <p className="text-gray-500 text-sm">
              {tab === 'signin'
                ? 'Sign in to see your meetings and briefs.'
                : 'Your meetings, research, and decisions — in one workspace.'}
            </p>
          </div>

          <div className="bg-white rounded-2xl border border-gray-200/80 shadow-elevated p-6">
            {/* Tabs */}
            <div className="flex gap-1 bg-gray-100 rounded-xl p-1 mb-6">
              {tabButton('signin', 'Sign in')}
              {tabButton('signup', 'Create account')}
            </div>

            <form onSubmit={submit} className="space-y-4">
              {tab === 'signup' && (
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1.5">
                    Full name
                  </label>
                  <input
                    type="text"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="Alex Rivera"
                    className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-indigo-400 focus:border-indigo-400 outline-none transition-shadow"
                  />
                </div>
              )}
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1.5">
                  Email
                </label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@company.com"
                  className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-indigo-400 focus:border-indigo-400 outline-none transition-shadow"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1.5">
                  Password
                </label>
                <input
                  type="password"
                  required
                  minLength={tab === 'signup' ? 8 : 1}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={tab === 'signup' ? 'At least 8 characters' : '••••••••'}
                  className="w-full px-3.5 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-indigo-400 focus:border-indigo-400 outline-none transition-shadow"
                />
              </div>

              {error && (
                <div className="px-3.5 py-2.5 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={busy}
                className="w-full flex items-center justify-center gap-2 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white font-semibold rounded-xl shadow-sm hover:shadow-md transition-all duration-200 active:scale-[0.99]"
              >
                {busy ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <>
                    {tab === 'signin' ? 'Sign in' : 'Create account'}
                    <ArrowRight className="w-4 h-4" />
                  </>
                )}
              </button>
            </form>
          </div>

          <p className="text-center text-xs text-gray-400 mt-6">
            {tab === 'signin' ? (
              <>New to Donna?{' '}
                <button onClick={() => setTab('signup')} className="text-indigo-600 hover:underline font-medium">
                  Create an account
                </button>
              </>
            ) : (
              <>Already have an account?{' '}
                <button onClick={() => setTab('signin')} className="text-indigo-600 hover:underline font-medium">
                  Sign in
                </button>
              </>
            )}
          </p>
        </div>
      </div>
    </main>
  );
}
