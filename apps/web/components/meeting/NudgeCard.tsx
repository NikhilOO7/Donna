'use client';

import React from 'react';
import {
  Lightbulb, BookOpen, ShieldCheck, MessageSquare, GitBranch, X
} from 'lucide-react';

interface NudgeCardProps {
  nudge: {
    id: string;
    type: string;
    title: string;
    content: string;
    source_agent?: string;
    relevance_score?: number;
    created_at: string;
  };
  onLogDecision?: (nudgeId: string, content: string) => void;
  onDismiss?: (nudgeId: string) => void;
}

const TYPE_CONFIG: Record<string, {
  icon: React.ElementType;
  gradient: string;
  border: string;
  iconBg: string;
  iconColor: string;
  label: string;
}> = {
  insight: {
    icon: Lightbulb,
    gradient: 'from-amber-50 to-orange-50',
    border: 'border-amber-200/60',
    iconBg: 'bg-gradient-to-br from-amber-400 to-orange-500',
    iconColor: 'text-white',
    label: 'Insight',
  },
  context: {
    icon: BookOpen,
    gradient: 'from-blue-50 to-sky-50',
    border: 'border-blue-200/60',
    iconBg: 'bg-gradient-to-br from-blue-400 to-sky-500',
    iconColor: 'text-white',
    label: 'Context',
  },
  fact_check: {
    icon: ShieldCheck,
    gradient: 'from-emerald-50 to-green-50',
    border: 'border-emerald-200/60',
    iconBg: 'bg-gradient-to-br from-emerald-400 to-green-500',
    iconColor: 'text-white',
    label: 'Fact Check',
  },
  decision_prompt: {
    icon: MessageSquare,
    gradient: 'from-violet-50 to-purple-50',
    border: 'border-violet-200/60',
    iconBg: 'bg-gradient-to-br from-violet-400 to-purple-500',
    iconColor: 'text-white',
    label: 'Decision',
  },
  knowledge_graph: {
    icon: GitBranch,
    gradient: 'from-indigo-50 to-blue-50',
    border: 'border-indigo-200/60',
    iconBg: 'bg-gradient-to-br from-indigo-400 to-blue-500',
    iconColor: 'text-white',
    label: 'Connection',
  },
};

export default function NudgeCard({ nudge, onLogDecision, onDismiss }: NudgeCardProps) {
  const config = TYPE_CONFIG[nudge.type] || TYPE_CONFIG.insight;
  const Icon = config.icon;

  return (
    <div className={`
      bg-gradient-to-br ${config.gradient}
      border ${config.border}
      rounded-xl p-4 relative group
      animate-slide-in
      transition-all duration-300
      hover:shadow-card-hover hover:-translate-y-0.5
    `}>
      {/* Dismiss */}
      {onDismiss && (
        <button
          onClick={() => onDismiss(nudge.id)}
          className="absolute top-2.5 right-2.5 p-1 text-gray-400 hover:text-gray-600 opacity-0 group-hover:opacity-100 transition-all duration-200 rounded-lg hover:bg-white/50"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      )}

      {/* Header */}
      <div className="flex items-start gap-3">
        <div className={`w-8 h-8 rounded-lg ${config.iconBg} flex items-center justify-center flex-shrink-0 shadow-sm`}>
          <Icon className={`w-4 h-4 ${config.iconColor}`} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] font-bold uppercase tracking-wider text-gray-400">{config.label}</span>
            {nudge.relevance_score && (
              <span className="text-[10px] text-gray-400">
                {Math.round(nudge.relevance_score * 100)}% relevant
              </span>
            )}
          </div>
          <h4 className="text-sm font-semibold text-gray-900">{nudge.title}</h4>
          <p className="text-[13px] text-gray-600 mt-1 leading-relaxed line-clamp-3">{nudge.content}</p>

          {nudge.source_agent && (
            <p className="text-[11px] text-gray-400 mt-2">via {nudge.source_agent}</p>
          )}
        </div>
      </div>

      {/* Actions */}
      {nudge.type === 'decision_prompt' && onLogDecision && (
        <div className="mt-3 pt-3 border-t border-gray-200/40 flex items-center gap-2">
          <button
            onClick={() => onLogDecision(nudge.id, nudge.content)}
            className="px-3 py-1.5 bg-[#7c3aed] hover:bg-[#6d28d9] text-white text-xs font-medium rounded-lg shadow-sm hover:shadow-md transition-all duration-200 active:scale-[0.97]"
          >
            Log Decision
          </button>
          <button
            onClick={() => onDismiss?.(nudge.id)}
            className="px-3 py-1.5 text-gray-500 text-xs rounded-lg hover:bg-white/60 transition-colors"
          >
            Dismiss
          </button>
        </div>
      )}
    </div>
  );
}
