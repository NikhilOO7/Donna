'use client';

import React, { useCallback, useEffect, useState } from 'react';
import {
  Database, ShieldCheck, ShieldAlert, Loader2, Plus, Trash2, RefreshCw,
  CheckCircle2, AlertTriangle, Lock, ScrollText, X,
} from 'lucide-react';
import { apiClient } from '@/lib/api-client';

/**
 * One-time setup for a read-only connection to the company's own database.
 *
 * The flow is deliberately three explicit steps rather than one "connect"
 * button, because each step is a decision the customer should make knowingly:
 *
 *   1. Credentials   — what Donna may authenticate as
 *   2. Verify        — we prove the account cannot write, and show them what
 *                      we can see, BEFORE reading any business data
 *   3. Approve tables— nothing is read until specific tables are ticked
 *
 * Step 2 is the one worth defending in a security review: Donna attempts a
 * write and requires it to fail. "Use a read-only user" is advice customers
 * frequently get wrong, so it is verified rather than trusted.
 */
export default function DataConnectionSettings() {
  const [loading, setLoading] = useState(true);
  const [connections, setConnections] = useState<any[]>([]);
  const [encryptionReady, setEncryptionReady] = useState(true);
  const [allowPrivate, setAllowPrivate] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [tables, setTables] = useState<Record<string, any[]>>({});
  const [checks, setChecks] = useState<Record<string, any>>({});
  const [auditFor, setAuditFor] = useState<string | null>(null);
  const [audit, setAudit] = useState<any[]>([]);
  const [syncReport, setSyncReport] = useState<any | null>(null);

  const [form, setForm] = useState({
    name: '', host: '', port: 5432, database: '', username: '', password: '',
    ssl_mode: 'require',
  });

  const load = useCallback(async () => {
    try {
      const data = await apiClient.listDataConnections();
      setConnections(data.connections || []);
      setEncryptionReady(data.encryption_ready);
      setAllowPrivate(data.allow_private_hosts);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Could not load connections');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy('create'); setError(null);
    try {
      await apiClient.createDataConnection(form);
      setForm({ name: '', host: '', port: 5432, database: '', username: '', password: '', ssl_mode: 'require' });
      setShowForm(false);
      await load();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Could not create connection');
    } finally { setBusy(null); }
  };

  const handleVerify = async (id: string) => {
    setBusy(id); setError(null);
    try {
      const res = await apiClient.verifyDataConnection(id);
      setTables((p) => ({ ...p, [id]: res.tables || [] }));
      setChecks((p) => ({ ...p, [id]: res.check || {} }));
      await load();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Verification failed');
    } finally { setBusy(null); }
  };

  const handleToggleTable = async (conn: any, qualified: string) => {
    const current: string[] = conn.allowed_tables || [];
    const next = current.includes(qualified)
      ? current.filter((t) => t !== qualified)
      : [...current, qualified];
    setBusy(conn.id);
    try {
      await apiClient.updateDataConnection(conn.id, { allowed_tables: next });
      await load();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Could not update approved tables');
    } finally { setBusy(null); }
  };

  const handleSync = async (id: string) => {
    setBusy(id); setError(null); setSyncReport(null);
    try {
      const res = await apiClient.syncDataConnection(id);
      // Show the per-table result: "it worked" is not the same as "it read
      // what you expected", and a table that returned zero rows is exactly
      // the thing a silent success would hide.
      setSyncReport({ id, ...res });
      await load();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Sync failed');
    } finally { setBusy(null); }
  };

  const handleAudit = async (id: string) => {
    setAuditFor(id);
    try {
      const res = await apiClient.getDataConnectionAudit(id);
      setAudit(res.queries || []);
    } catch { setAudit([]); }
  };

  const handleDelete = async (id: string) => {
    setBusy(id);
    try { await apiClient.deleteDataConnection(id); await load(); }
    finally { setBusy(null); }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="w-6 h-6 text-indigo-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <header>
        <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
          <Database className="w-5 h-5 text-indigo-600" />
          Company database
        </h2>
        <p className="text-sm text-gray-500 mt-1 max-w-2xl">
          Connect Donna to your own database, read-only, so she has a factual base
          for meetings even when nobody uploads a document. She uses it to prepare
          briefs from your agenda, and to answer data questions during the meeting.
        </p>
      </header>

      {!encryptionReady && (
        <Banner tone="error" icon={<Lock className="w-4 h-4" />}>
          <b>Encryption is not configured.</b> <code>ENCRYPTION_KEY</code> must be set
          before credentials can be stored. Connections are disabled until then.
        </Banner>
      )}

      {allowPrivate && (
        <Banner tone="warn" icon={<AlertTriangle className="w-4 h-4" />}>
          <b>Private hosts are permitted</b> on this deployment
          (<code>DATA_CONNECTION_ALLOW_PRIVATE=true</code>). Appropriate for a
          self-hosted database on your own network; not for a shared deployment.
        </Banner>
      )}

      {error && (
        <Banner tone="error" icon={<AlertTriangle className="w-4 h-4" />}>{error}</Banner>
      )}

      {connections.map((conn) => {
        const approved: string[] = conn.allowed_tables || [];
        const discovered = tables[conn.id] || [];
        const check = checks[conn.id];
        return (
          <div key={conn.id} className="bg-white border border-gray-200 rounded-xl overflow-hidden">
            <div className="px-5 py-4 flex items-start justify-between gap-4 border-b border-gray-100">
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="font-semibold text-gray-900">{conn.name}</h3>
                  <StatusChip status={conn.status} />
                  {approved.length > 0 && (
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
                      {approved.length} table{approved.length === 1 ? '' : 's'} approved
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-500 mt-1 font-mono">
                  {conn.username}@{conn.host}:{conn.port}/{conn.database} · SSL {conn.ssl_mode}
                </p>
                {conn.last_error && (
                  <p className="text-xs text-red-600 mt-1">{conn.last_error}</p>
                )}

              </div>
              <div className="flex items-center gap-1.5 flex-shrink-0">
                <IconBtn onClick={() => handleAudit(conn.id)} title="Query audit log">
                  <ScrollText className="w-4 h-4" />
                </IconBtn>
                <IconBtn onClick={() => handleDelete(conn.id)} title="Delete" danger>
                  <Trash2 className="w-4 h-4" />
                </IconBtn>
              </div>
            </div>

            {/* Step 2 — verification result */}
            {check && (
              <div className="px-5 py-3 bg-gray-50/70 border-b border-gray-100 space-y-1.5 text-xs">
                <Row ok={!!check.write_blocked}
                     label={check.write_blocked
                       ? 'Verified read-only — the account cannot write'
                       : 'This account CAN write'} />
                <Row ok={!check.is_superuser}
                     label={check.is_superuser
                       ? 'Account is a superuser — session read-only can be overridden'
                       : 'Not a superuser'} />
                {check.warning && (
                  <p className="text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-2.5 py-1.5 mt-1.5">
                    {check.warning}
                  </p>
                )}
              </div>
            )}

            <div className="px-5 py-4 space-y-3">
              <div className="flex items-center gap-2 flex-wrap">
                <button
                  onClick={() => handleVerify(conn.id)}
                  disabled={busy === conn.id}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-300 text-white text-xs font-medium rounded-lg transition-colors"
                >
                  {busy === conn.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ShieldCheck className="w-3.5 h-3.5" />}
                  Verify &amp; discover schema
                </button>
              </div>

              {/* Re-sync — the snapshot is what in-meeting insights read, so
                  this is the control that decides how current they are. */}
              {approved.length > 0 && (
                <div className="rounded-lg border border-gray-200 bg-gray-50/60 p-3">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-gray-800">
                        In-meeting snapshot
                      </p>
                      <p className="text-[11px] text-gray-500 mt-0.5">
                        {conn.last_indexed_at
                          ? <>Last synced {new Date(conn.last_indexed_at).toLocaleString()} · {conn.indexed_row_count} facts indexed</>
                          : <>Not synced yet — Donna has no data from this connection during meetings.</>}
                      </p>
                    </div>
                    <button
                      onClick={() => handleSync(conn.id)}
                      disabled={busy === conn.id}
                      className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-300 text-white text-xs font-semibold rounded-lg transition-colors flex-shrink-0"
                    >
                      {busy === conn.id
                        ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        : <RefreshCw className="w-3.5 h-3.5" />}
                      {conn.last_indexed_at ? 'Re-sync now' : 'Sync now'}
                    </button>
                  </div>

                  {syncReport?.id === conn.id && (
                    <div className="mt-2.5 pt-2.5 border-t border-gray-200">
                      {syncReport.error ? (
                        <p className="text-[11px] font-medium text-red-700 bg-red-50 border border-red-200 rounded-lg px-2.5 py-1.5 mb-1.5">
                          Read {syncReport.rows_read} row(s), but indexed none — {syncReport.error}
                        </p>
                      ) : (
                        <p className="text-[11px] font-medium text-emerald-700 mb-1">
                          Indexed {syncReport.indexed_rows} fact{syncReport.indexed_rows === 1 ? '' : 's'}
                        </p>
                      )}
                      <div className="space-y-0.5">
                        {(syncReport.tables || []).map((t: any) => (
                          <div key={t.table} className="flex items-center justify-between text-[11px]">
                            <span className="font-mono text-gray-600 truncate">{t.table}</span>
                            <span className={t.rows > 0 ? 'text-gray-500' : 'text-amber-600'}>
                              {t.rows} rows{t.reason ? ` · ${t.reason}` : ''}
                            </span>
                          </div>
                        ))}
                      </div>
                      <p className="text-[10px] text-gray-400 mt-1.5">
                        Re-sync after your data changes. Automatic scheduling is not
                        implemented yet — until it is, this is the only thing that
                        refreshes what Donna sees during meetings.
                      </p>
                    </div>
                  )}
                </div>
              )}

              {/* Step 3 — table approval */}
              {discovered.length > 0 ? (
                <div>
                  <p className="text-xs text-gray-600 mb-2">
                    <b>Nothing is read until you approve it.</b> Tick the tables Donna
                    may use. Columns that look like secrets or personal data are
                    excluded automatically and shown below for transparency.
                  </p>
                  <div className="max-h-72 overflow-y-auto border border-gray-200 rounded-lg divide-y divide-gray-100">
                    {discovered.map((t: any) => (
                      <label
                        key={t.qualified}
                        className="flex items-start gap-2.5 px-3 py-2 hover:bg-gray-50 cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={approved.includes(t.qualified)}
                          onChange={() => handleToggleTable(conn, t.qualified)}
                          className="mt-0.5 accent-indigo-600"
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-mono text-gray-800 truncate">
                            {t.qualified}
                          </span>
                          <span className="block text-[11px] text-gray-400">
                            {t.row_estimate === null || t.row_estimate === undefined
                              ? 'row count not analyzed'
                              : `~${t.row_estimate.toLocaleString()} rows`} · {t.column_count} columns
                            {t.sensitive_columns?.length > 0 && (
                              <span className="text-amber-600">
                                {' '}· {t.sensitive_columns.length} sensitive column
                                {t.sensitive_columns.length === 1 ? '' : 's'} excluded
                              </span>
                            )}
                          </span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="text-xs text-gray-400">
                  Verify the connection to discover which tables are available.
                </p>
              )}
            </div>
          </div>
        );
      })}

      {!showForm ? (
        <button
          onClick={() => setShowForm(true)}
          disabled={!encryptionReady}
          className="inline-flex items-center gap-2 px-4 py-2.5 bg-white border border-dashed border-gray-300 hover:border-indigo-400 hover:text-indigo-600 disabled:opacity-50 disabled:cursor-not-allowed text-gray-600 text-sm font-medium rounded-xl transition-colors w-full justify-center"
        >
          <Plus className="w-4 h-4" />
          Connect a database
        </button>
      ) : (
        <form onSubmit={handleCreate} className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-gray-900">New connection</h3>
            <button type="button" onClick={() => setShowForm(false)} className="text-gray-400 hover:text-gray-700">
              <X className="w-4 h-4" />
            </button>
          </div>

          <Banner tone="info" icon={<ShieldCheck className="w-4 h-4" />}>
            Create a dedicated role with <b>SELECT-only</b> grants on the tables you
            want Donna to see. She will attempt a write during verification and
            expects it to fail.
          </Banner>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Name" value={form.name} onChange={(v: string) => setForm({ ...form, name: v })} placeholder="Production analytics" required />
            <Field label="Database" value={form.database} onChange={(v: string) => setForm({ ...form, database: v })} placeholder="app_production" required />
            <Field label="Host" value={form.host} onChange={(v: string) => setForm({ ...form, host: v })} placeholder="db.company.com" required />
            <Field label="Port" value={String(form.port)} onChange={(v: string) => setForm({ ...form, port: parseInt(v || '5432', 10) })} type="number" />
            <Field label="Username" value={form.username} onChange={(v: string) => setForm({ ...form, username: v })} placeholder="donna_readonly" required />
            <Field label="Password" value={form.password} onChange={(v: string) => setForm({ ...form, password: v })} type="password" required />
          </div>

          <label className="block">
            <span className="block text-xs font-medium text-gray-600 mb-1">SSL mode</span>
            <select
              value={form.ssl_mode}
              onChange={(e) => setForm({ ...form, ssl_mode: e.target.value })}
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:border-indigo-300"
            >
              <option value="require">require (encrypted — recommended)</option>
              <option value="verify-full">verify-full (encrypted + certificate verified)</option>
              <option value="disable">disable (unencrypted — not recommended)</option>
            </select>
          </label>

          <button
            type="submit"
            disabled={busy === 'create'}
            className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-300 text-white text-sm font-semibold rounded-xl transition-colors"
          >
            {busy === 'create' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Database className="w-4 h-4" />}
            Save connection
          </button>
        </form>
      )}

      {/* Audit drawer — "what did you run against my database?" is self-service */}
      {auditFor && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div className="absolute inset-0 bg-gray-900/20 backdrop-blur-[2px]" onClick={() => setAuditFor(null)} />
          <aside className="relative w-full max-w-lg bg-white h-full shadow-2xl flex flex-col animate-slide-in">
            <header className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
              <div>
                <h3 className="font-semibold text-gray-900">Query audit</h3>
                <p className="text-xs text-gray-500">Every statement Donna ran against this database</p>
              </div>
              <button onClick={() => setAuditFor(null)} className="p-1.5 text-gray-400 hover:text-gray-700 rounded-lg">
                <X className="w-4 h-4" />
              </button>
            </header>
            <div className="flex-1 overflow-y-auto p-4 space-y-2">
              {audit.length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-10">No queries yet.</p>
              ) : audit.map((q, i) => (
                <div key={i} className="border border-gray-200 rounded-lg p-3">
                  <div className="flex items-center gap-2 mb-1.5 text-[11px]">
                    <span className={`px-1.5 py-0.5 rounded font-medium ${q.succeeded ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>
                      {q.succeeded ? 'ok' : 'failed'}
                    </span>
                    <span className="text-gray-500">{q.purpose}</span>
                    <span className="text-gray-400">{q.row_count} rows · {q.duration_ms}ms</span>
                    <span className="text-gray-400 ml-auto">{q.at ? new Date(q.at).toLocaleString() : ''}</span>
                  </div>
                  <pre className="text-[11px] text-gray-600 whitespace-pre-wrap font-mono bg-gray-50 rounded p-2 overflow-x-auto">{q.sql}</pre>
                  {q.error && <p className="text-[11px] text-red-600 mt-1">{q.error}</p>}
                </div>
              ))}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------- helpers */

function IconBtn({ onClick, title, children, danger }: any) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={[
        'p-1.5 rounded-lg transition-colors',
        danger
          ? 'text-gray-400 hover:text-red-600 hover:bg-red-50'
          : 'text-gray-400 hover:text-indigo-600 hover:bg-indigo-50',
      ].join(' ')}
    >
      {children}
    </button>
  );
}

function Field({ label, value, onChange, type = 'text', placeholder, required }: any) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-gray-600 mb-1">{label}</span>
      <input
        type={type}
        value={value}
        required={required}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:border-indigo-300"
      />
    </label>
  );
}

function StatusChip({ status }: { status: string }) {
  const map: Record<string, string> = {
    connected: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    error: 'bg-red-50 text-red-700 border-red-200',
    unverified: 'bg-gray-50 text-gray-500 border-gray-200',
  };
  return (
    <span className={`text-[11px] px-2 py-0.5 rounded-full border ${map[status] || map.unverified}`}>
      {status}
    </span>
  );
}

function Row({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      {ok ? (
        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 flex-shrink-0" />
      ) : (
        <ShieldAlert className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />
      )}
      <span className={ok ? 'text-gray-600' : 'text-amber-700'}>{label}</span>
    </div>
  );
}

function Banner({ tone, icon, children }: any) {
  const map: Record<string, string> = {
    error: 'bg-red-50 border-red-200 text-red-700',
    warn: 'bg-amber-50 border-amber-200 text-amber-800',
    info: 'bg-indigo-50 border-indigo-200 text-indigo-800',
  };
  return (
    <div className={`flex items-start gap-2 text-xs border rounded-lg px-3 py-2.5 ${map[tone]}`}>
      <span className="flex-shrink-0 mt-0.5">{icon}</span>
      <span>{children}</span>
    </div>
  );
}
