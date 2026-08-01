'use client';

import React from 'react';
import {
  Lightbulb, BookOpen, ShieldCheck, MessageSquare, GitBranch, X,
  FileText, Table2, ImageIcon, ExternalLink, User, CalendarClock, Pin,
  Sparkles, UserCheck, TrendingUp, ChevronRight, ListChecks,
} from 'lucide-react';

interface NudgeCardProps {
  nudge: {
    id: string;
    type: string;
    title: string;
    content: string;
    source_agent?: string;
    source_data?: Record<string, any>;
    relevance_score?: number;
    pinned_at?: string | null;
    dismissed_at?: string | null;
    created_at: string;
  };
  onLogDecision?: (nudgeId: string, content: string) => void;
  onDismiss?: (nudgeId: string) => void;
  onPin?: (nudgeId: string) => void;
  /** "Ask Donna" — send a follow-up question about this insight to the assistant. */
  onAskDonna?: (prompt: string) => void;
  /** Compact rendering for canvas mode. */
  compact?: boolean;
}

const TYPE_CONFIG: Record<string, {
  icon: React.ElementType;
  gradient: string;
  border: string;
  iconBg: string;
  label: string;
  accent: string;
  barColor: string;
}> = {
  insight: {
    icon: Lightbulb,
    gradient: 'from-amber-50 to-orange-50',
    border: 'border-amber-200/60',
    iconBg: 'bg-gradient-to-br from-amber-400 to-orange-500',
    label: 'Insight',
    accent: 'border-amber-300',
    barColor: 'bg-amber-400',
  },
  context: {
    icon: BookOpen,
    gradient: 'from-blue-50 to-sky-50',
    border: 'border-blue-200/60',
    iconBg: 'bg-gradient-to-br from-blue-400 to-sky-500',
    label: 'Context',
    accent: 'border-blue-300',
    barColor: 'bg-blue-400',
  },
  fact_check: {
    icon: ShieldCheck,
    gradient: 'from-emerald-50 to-green-50',
    border: 'border-emerald-200/60',
    iconBg: 'bg-gradient-to-br from-emerald-400 to-green-500',
    label: 'Fact Check',
    accent: 'border-emerald-300',
    barColor: 'bg-emerald-400',
  },
  decision_prompt: {
    icon: MessageSquare,
    gradient: 'from-violet-50 to-purple-50',
    border: 'border-violet-200/60',
    iconBg: 'bg-gradient-to-br from-violet-400 to-purple-500',
    label: 'Decision',
    accent: 'border-violet-300',
    barColor: 'bg-violet-400',
  },
  knowledge_graph: {
    icon: GitBranch,
    gradient: 'from-indigo-50 to-blue-50',
    border: 'border-indigo-200/60',
    iconBg: 'bg-gradient-to-br from-indigo-400 to-blue-500',
    label: 'Connection',
    accent: 'border-indigo-300',
    barColor: 'bg-indigo-400',
  },
  activation: {
    icon: UserCheck,
    gradient: 'from-teal-50 to-emerald-50',
    border: 'border-teal-200/60',
    iconBg: 'bg-gradient-to-br from-teal-400 to-emerald-500',
    label: 'Your Expertise Needed',
    accent: 'border-teal-300',
    barColor: 'bg-teal-400',
  },
  agenda: {
    icon: ListChecks,
    gradient: 'from-rose-50 to-orange-50',
    border: 'border-rose-200/60',
    iconBg: 'bg-gradient-to-br from-rose-400 to-orange-400',
    label: 'Agenda Check',
    accent: 'border-rose-300',
    barColor: 'bg-rose-400',
  },
  flow: {
    icon: TrendingUp,
    gradient: 'from-cyan-50 to-sky-50',
    border: 'border-cyan-200/60',
    iconBg: 'bg-gradient-to-br from-cyan-400 to-sky-500',
    label: 'Meeting Flow',
    accent: 'border-cyan-300',
    barColor: 'bg-cyan-400',
  },
};

const FACT_CHECK_STATUS: Record<string, { label: string; classes: string }> = {
  contradicted: { label: 'Contradicted', classes: 'bg-red-100 text-red-700' },
  partial: { label: 'Partially true', classes: 'bg-amber-100 text-amber-700' },
  unverified: { label: 'Unverified', classes: 'bg-gray-100 text-gray-600' },
};

function hostnameOf(url?: string): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return null;
  }
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

/** Derive up to 3 topical tag chips from the card's source data (PDF: "#UX #Research #Q3"). */
function deriveTags(type: string, data: Record<string, any>): string[] {
  const tags: string[] = [];
  if (Array.isArray(data.tags)) tags.push(...data.tags.map(String));
  if (data.matched_topic) tags.push(String(data.matched_topic));
  if (data.element_type && data.element_type !== 'text') tags.push(String(data.element_type));
  if (type === 'knowledge_graph') {
    if (data.source_type) tags.push(String(data.source_type).toLowerCase());
    if (data.target_type) tags.push(String(data.target_type).toLowerCase());
  }
  if (type === 'fact_check' && data.status) tags.push(String(data.status));
  const section = Array.isArray(data.section_path) ? data.section_path[0] : null;
  if (section) tags.push(String(section));
  return Array.from(new Set(tags)).slice(0, 3);
}

/** The verbatim quote that triggered this card, when available. */
function triggerQuote(type: string, data: Record<string, any>): { speaker?: string; text: string } | null {
  if (type === 'decision_prompt' && Array.isArray(data.trigger_quotes) && data.trigger_quotes.length > 0) {
    const q = data.trigger_quotes[data.trigger_quotes.length - 1];
    if (q?.text) return { speaker: q.speaker, text: q.text };
  }
  if (type === 'fact_check' && data.claim) {
    return { text: String(data.claim) };
  }
  return null;
}

/** "Trace the claim" footer — every card names its source. */
function SourceFooter({ type, data }: { type: string; data: Record<string, any> }) {
  if (!data || Object.keys(data).length === 0) return null;

  if (type === 'context') {
    if (data.source_type === 'meeting_memory') {
      return (
        <div className="space-y-1">
          <p className="flex items-center gap-1.5 text-[11px] text-gray-500 truncate">
            <CalendarClock className="w-3 h-3 flex-shrink-0" />
            <span className="truncate">
              Source: Meeting — {data.meeting_title || 'previous meeting'}
              {data.meeting_date ? ` (${data.meeting_date})` : ''}
            </span>
          </p>
          {data.quote && (
            <p className="text-[11px] text-gray-400 italic truncate">&ldquo;{data.quote}&rdquo;</p>
          )}
        </div>
      );
    }
    const docLabel =
      data.document_title ||
      (data.document_id ? `Document ${String(data.document_id).slice(0, 8)}` : null);
    if (!docLabel) return null;
    const section = Array.isArray(data.section_path) && data.section_path.length > 0
      ? data.section_path[0]
      : null;
    const ElementIcon =
      data.element_type === 'table' ? Table2 :
      data.element_type === 'image' ? ImageIcon : FileText;
    return (
      <p className="flex items-center gap-1.5 text-[11px] text-gray-500 truncate">
        <ElementIcon className="w-3 h-3 flex-shrink-0" />
        <span className="truncate">
          Source: {docLabel}
          {section ? ` · ${section}` : ''}
          {data.page_number ? ` · p. ${data.page_number}` : ''}
        </span>
      </p>
    );
  }

  if (type === 'fact_check') {
    const status = FACT_CHECK_STATUS[data.status];
    const linkLabel = data.source_title || hostnameOf(data.source_url);
    return (
      <div className="flex items-center gap-2 min-w-0">
        {status && (
          <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold flex-shrink-0 ${status.classes}`}>
            {status.label}
          </span>
        )}
        {data.source_url && linkLabel && (
          <a
            href={data.source_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="flex items-center gap-1 text-[11px] text-blue-600 hover:text-blue-800 hover:underline truncate"
          >
            <ExternalLink className="w-3 h-3 flex-shrink-0" />
            <span className="truncate">{linkLabel}</span>
          </a>
        )}
      </div>
    );
  }

  if (type === 'insight') {
    const linkLabel = hostnameOf(data.source_url);
    if (!data.source_url || !linkLabel) return null;
    return (
      <a
        href={data.source_url}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
        className="flex items-center gap-1 text-[11px] text-blue-600 hover:text-blue-800 hover:underline truncate"
      >
        <ExternalLink className="w-3 h-3 flex-shrink-0" />
        <span className="truncate">Source: {linkLabel}</span>
      </a>
    );
  }

  if (type === 'knowledge_graph' && data.source_label && data.target_label) {
    return (
      <p className="flex items-center gap-1 text-[11px] text-gray-500 truncate">
        <GitBranch className="w-3 h-3 flex-shrink-0" />
        <span className="truncate">
          {data.source_label}
          <span className="text-indigo-500 font-medium">
            {' '}—{data.relationship ? ` ${String(data.relationship).replace(/_/g, ' ')} ` : ' '}→{' '}
          </span>
          {data.target_label}
        </span>
      </p>
    );
  }

  if (type === 'decision_prompt' && (data.owner || data.deadline)) {
    return (
      <div className="flex items-center gap-3 text-[11px] text-gray-500">
        {data.owner && (
          <span className="flex items-center gap-1">
            <User className="w-3 h-3" /> {data.owner}
          </span>
        )}
        {data.deadline && (
          <span className="flex items-center gap-1">
            <CalendarClock className="w-3 h-3" /> {data.deadline}
          </span>
        )}
      </div>
    );
  }

  if (type === 'activation') {
    return (
      <div className="space-y-1">
        {data.triggered_by && (
          <p className="flex items-center gap-1.5 text-[11px] text-gray-500">
            <User className="w-3 h-3" /> Triggered by {data.triggered_by}
          </p>
        )}
        {Array.isArray(data.matched_expertise) && data.matched_expertise.length > 0 && (
          <div className="flex items-center gap-1 flex-wrap">
            <span className="text-[10px] text-gray-400">Your expertise:</span>
            {data.matched_expertise.map((m: string) => (
              <span key={m} className="px-1.5 py-0.5 bg-teal-100 text-teal-700 rounded text-[10px] font-medium">
                {m}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }

  return null;
}

/** Render a markdown table (| a | b |) as a real table — the "visual insight". */
function VisualTable({ markdown }: { markdown: string }) {
  const rows = markdown
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l.startsWith('|'))
    .filter((l) => !/^\|[\s:|-]+\|$/.test(l))
    .map((l) => l.split('|').slice(1, -1).map((c) => c.trim()));
  if (rows.length < 2) return null;
  const [head, ...body] = rows;
  return (
    <div className="mt-2 overflow-x-auto rounded-lg border border-gray-200/70 bg-white/70">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="bg-gray-50">
            {head.map((h, i) => (
              <th key={i} className="px-2 py-1 text-left font-semibold text-gray-600 whitespace-nowrap">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.slice(0, 6).map((r, i) => (
            <tr key={i} className="border-t border-gray-100">
              {r.map((c, j) => (
                <td key={j} className="px-2 py-1 text-gray-700 whitespace-nowrap">{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** PDF "minimal nudge card" extras — rendered whenever an agent provides them. */
function CardExtras({ data }: { data: Record<string, any> }) {
  const metrics = Array.isArray(data.key_metrics) ? data.key_metrics : [];
  const actions = Array.isArray(data.recommended_actions) ? data.recommended_actions : [];
  if (metrics.length === 0 && actions.length === 0) return null;

  return (
    <div className="mt-2.5 space-y-2.5">
      {metrics.length > 0 && (
        <div>
          <p className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-1">
            <TrendingUp className="w-3 h-3" /> Key Metrics
          </p>
          <div className="space-y-0.5">
            {metrics.map((m: any, i: number) => (
              <p key={i} className="text-[12px] text-gray-600">
                <span className="font-semibold text-gray-900">{m.value}</span>{' '}
                {m.label}
              </p>
            ))}
          </div>
        </div>
      )}
      {actions.length > 0 && (
        <div>
          <p className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-1">
            <ChevronRight className="w-3 h-3" /> Recommended Actions
          </p>
          <div className="space-y-1">
            {actions.map((a: any, i: number) => (
              <div key={i} className="flex items-center justify-between gap-2">
                <span className="text-[12px] text-gray-700 flex items-center gap-1.5">
                  <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${i === 0 ? 'bg-gray-800' : 'border border-gray-400'}`} />
                  {a.action}
                </span>
                {a.role && (
                  <span className="text-[10px] text-gray-400 flex-shrink-0">({a.role})</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function NudgeCard({
  nudge, onLogDecision, onDismiss, onPin, onAskDonna, compact,
}: NudgeCardProps) {
  const config = TYPE_CONFIG[nudge.type] || TYPE_CONFIG.insight;
  const Icon = config.icon;
  const isPinned = Boolean(nudge.pinned_at);
  const data = nudge.source_data || {};
  const confidence = nudge.relevance_score
    ? Math.min(Math.round(nudge.relevance_score * 100), 100)
    : null;
  const quote = triggerQuote(nudge.type, data);
  const tags = deriveTags(nudge.type, data);
  const time = formatTime(nudge.created_at);

  return (
    <div className={`
      bg-gradient-to-br ${config.gradient}
      border ${isPinned ? 'border-primary-300 ring-1 ring-primary-200' : config.border}
      rounded-xl ${compact ? 'p-3' : 'p-4'} relative group
      animate-slide-in
      transition-all duration-300
      hover:shadow-card-hover hover:-translate-y-0.5
    `}>
      {/* Header row: type chip + time · confidence */}
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className={`w-7 h-7 rounded-lg ${config.iconBg} flex items-center justify-center flex-shrink-0 shadow-sm`}>
            <Icon className="w-3.5 h-3.5 text-white" />
          </div>
          <span className="text-[10px] font-bold uppercase tracking-wider text-gray-400">
            {config.label}
          </span>
          {time && <span className="text-[10px] text-gray-400">{time}</span>}
        </div>
        <div className="flex items-center gap-1.5">
          {confidence !== null && (
            <div className="flex items-center gap-1.5">
              <div className="w-10 h-1 rounded-full bg-gray-200/80 overflow-hidden">
                <div
                  className={`h-full rounded-full ${config.barColor}`}
                  style={{ width: `${confidence}%` }}
                />
              </div>
              <span className="text-[11px] font-semibold text-gray-500">{confidence}%</span>
            </div>
          )}
          {onPin && (
            <button
              onClick={() => onPin(nudge.id)}
              title={isPinned ? 'Unpin' : 'Pin insight'}
              className={`p-1 rounded-lg transition-all duration-200 hover:bg-white/50 ${
                isPinned
                  ? 'text-primary-600'
                  : 'text-gray-400 hover:text-gray-600 opacity-0 group-hover:opacity-100'
              }`}
            >
              <Pin className={`w-3.5 h-3.5 ${isPinned ? 'fill-current' : ''}`} />
            </button>
          )}
          {onDismiss && (
            <button
              onClick={() => onDismiss(nudge.id)}
              title="Dismiss"
              className="p-1 text-gray-400 hover:text-gray-600 opacity-0 group-hover:opacity-100 transition-all duration-200 rounded-lg hover:bg-white/50"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Verbatim trigger quote (PDF: italic quoted line with accent border) */}
      {quote && !compact && (
        <blockquote className={`border-l-2 ${config.accent} pl-2.5 mb-2`}>
          <p className="text-[12px] text-gray-600 italic leading-relaxed">
            &ldquo;{quote.text}&rdquo;
          </p>
          {quote.speaker && (
            <p className="text-[10px] text-gray-400 mt-0.5">— {quote.speaker}</p>
          )}
        </blockquote>
      )}

      {/* Optional visual insight (rendered when an agent supplies one) */}
      {data.image_url && !compact && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={data.image_url}
          alt=""
          className="w-full rounded-lg border border-gray-200/60 mb-2 max-h-40 object-cover"
        />
      )}

      <h4 className="text-sm font-semibold text-gray-900">{nudge.title}</h4>
      <p className={`text-[13px] text-gray-600 mt-1 leading-relaxed ${compact ? 'line-clamp-2' : 'line-clamp-4'}`}>
        {nudge.content}
      </p>

      {!compact && data.visual_table && <VisualTable markdown={data.visual_table} />}
      {!compact && <CardExtras data={data} />}

      {/* Source + tags */}
      <div className="mt-2 space-y-1.5">
        <SourceFooter type={nudge.type} data={data} />
        {tags.length > 0 && !compact && (
          <div className="flex items-center gap-1 flex-wrap">
            {tags.map((t) => (
              <span
                key={t}
                className="px-1.5 py-0.5 bg-white/70 border border-gray-200/60 rounded text-[10px] text-gray-500"
              >
                #{t.length > 24 ? `${t.slice(0, 24)}…` : t}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Action row */}
      {!compact && (onLogDecision || onAskDonna) && (
        <div className="mt-3 pt-2.5 border-t border-gray-200/40 flex items-center gap-2">
          {nudge.type === 'activation' && onPin && onDismiss && (
            <>
              <button
                onClick={() => onPin(nudge.id)}
                className="px-3 py-1.5 bg-teal-600 hover:bg-teal-700 text-white text-xs font-medium rounded-lg shadow-sm transition-all duration-200 active:scale-[0.97]"
              >
                I can contribute
              </button>
              <button
                onClick={() => onDismiss(nudge.id)}
                className="px-3 py-1.5 text-gray-500 text-xs rounded-lg border border-gray-200 hover:bg-white/60 transition-colors"
              >
                Not relevant to me
              </button>
            </>
          )}
          {nudge.type === 'decision_prompt' && onLogDecision && (
            <button
              onClick={() => onLogDecision(nudge.id, nudge.content)}
              className="px-3 py-1.5 bg-[#7c3aed] hover:bg-[#6d28d9] text-white text-xs font-medium rounded-lg shadow-sm hover:shadow-md transition-all duration-200 active:scale-[0.97]"
            >
              Log Decision
            </button>
          )}
          {onAskDonna && (
            <button
              onClick={() =>
                onAskDonna(
                  `Tell me more about this ${config.label.toLowerCase()}: "${nudge.title}" — ${nudge.content.slice(0, 200)}`,
                )
              }
              className="flex items-center gap-1 px-3 py-1.5 bg-white/70 hover:bg-white text-violet-600 text-xs font-medium rounded-lg border border-violet-200/60 transition-all duration-200"
            >
              <Sparkles className="w-3 h-3" />
              Ask Donna
            </button>
          )}
          {onDismiss && (
            <button
              onClick={() => onDismiss(nudge.id)}
              className="ml-auto px-2.5 py-1.5 text-gray-400 hover:text-gray-600 text-xs rounded-lg hover:bg-white/60 transition-colors"
            >
              Dismiss
            </button>
          )}
        </div>
      )}
    </div>
  );
}
