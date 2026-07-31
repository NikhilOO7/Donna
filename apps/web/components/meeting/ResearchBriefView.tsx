'use client';

import React from 'react';
import { Globe, Shield, ShieldCheck, ExternalLink, BookOpen, Sparkles } from 'lucide-react';

interface ResearchBriefViewProps {
  research: {
    status: string;
    source_count: number;
    executive_summary?: string;
    topics: {
      topic: string;
      rationale: string;
      key_findings?: { finding: string; source_url?: string; confidence?: number; urgency?: string }[];
      data_gaps?: string[];
      sources: {
        url: string;
        title: string;
        excerpt: string;
        tier: number;
        credibility_score: number;
      }[];
    }[];
  };
  /** "Discuss This" — sends a prompt about the topic/finding to the Donna assistant. */
  onDiscuss?: (prompt: string) => void;
}

/* Rotating accent borders for key findings — the report-card look */
const FINDING_ACCENTS = [
  'border-indigo-400',
  'border-emerald-400',
  'border-amber-400',
  'border-violet-400',
  'border-sky-400',
  'border-rose-400',
];

const TIER_STYLES: Record<number, { bg: string; text: string; label: string; icon: React.ReactNode }> = {
  1: {
    bg: 'bg-green-100',
    text: 'text-green-700',
    label: 'Tier 1',
    icon: <ShieldCheck className="w-3 h-3" />,
  },
  2: {
    bg: 'bg-yellow-100',
    text: 'text-yellow-700',
    label: 'Tier 2',
    icon: <Shield className="w-3 h-3" />,
  },
};

export default function ResearchBriefView({ research, onDiscuss }: ResearchBriefViewProps) {
  return (
    <div className="space-y-6">
      {/* Executive Summary */}
      {research.executive_summary && (
        <div className="bg-gradient-to-br from-primary-50 to-white rounded-lg border border-primary-200 p-6">
          <div className="flex items-center gap-2 mb-3">
            <BookOpen className="w-5 h-5 text-primary-600" />
            <h3 className="text-lg font-semibold text-gray-900">Executive Summary</h3>
            <span className="ml-auto text-sm text-gray-500">
              {research.source_count} validated sources
            </span>
          </div>
          <p className="text-gray-700 whitespace-pre-wrap leading-relaxed">
            {research.executive_summary}
          </p>
        </div>
      )}

      {/* Topics — report-card layout: key findings, then sources */}
      {research.topics?.map((topic, idx) => {
        const authoritative = (topic.sources || []).filter((s) => s.tier <= 2).length;
        return (
        <div key={idx} className="bg-white rounded-lg border border-gray-200 p-6">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <h4 className="text-lg font-semibold text-gray-900">{topic.topic}</h4>
              <p className="text-sm text-gray-500 mt-1">{topic.rationale}</p>
            </div>
            {onDiscuss && (
              <button
                onClick={() =>
                  onDiscuss(
                    `Let's discuss this research topic: "${topic.topic}". ` +
                    `Key findings: ${(topic.key_findings || []).map((f) => f.finding).join(' | ') || 'see sources'}. ` +
                    'What are the implications for our meeting?',
                  )
                }
                className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium rounded-lg shadow-sm transition-colors flex-shrink-0"
              >
                <Sparkles className="w-3 h-3" />
                Discuss This
              </button>
            )}
          </div>

          {/* KEY FINDINGS */}
          {topic.key_findings && topic.key_findings.length > 0 && (
            <div className="mb-5">
              <p className="text-[10px] font-bold uppercase tracking-widest text-gray-400 mb-3">
                Key Findings ({topic.key_findings.length})
              </p>
              <div className="space-y-2.5">
                {topic.key_findings.map((f, fIdx) => (
                  <div
                    key={fIdx}
                    className={`pl-3.5 py-2 border-l-[3px] ${FINDING_ACCENTS[fIdx % FINDING_ACCENTS.length]} bg-gray-50/60 rounded-r-lg`}
                  >
                    <p className="text-sm text-gray-800 leading-relaxed">{f.finding}</p>
                    <div className="flex items-center gap-2 mt-1">
                      {f.urgency === 'act_now' ? (
                        <span className="px-1.5 py-0.5 bg-red-100 text-red-700 rounded text-[10px] font-bold uppercase tracking-wide">Act Now</span>
                      ) : f.urgency === 'watch' ? (
                        <span className="px-1.5 py-0.5 bg-sky-100 text-sky-700 rounded text-[10px] font-bold uppercase tracking-wide">Watch</span>
                      ) : null}
                      {typeof f.confidence === 'number' && (
                        <span className="text-[11px] text-gray-400">
                          confidence {Math.round(f.confidence * 100)}/100
                        </span>
                      )}
                      {f.source_url && (
                        <a
                          href={f.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-1 text-[11px] text-primary-600 hover:underline"
                        >
                          <ExternalLink className="w-3 h-3" />
                          source
                        </a>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Blind spots (H7): adjacent topics the user didn't ask about */}
          {(topic as any).suggested_topics?.length > 0 && (
            <div className="mb-5 p-3.5 bg-violet-50/60 border border-violet-100 rounded-lg">
              <p className="text-[10px] font-bold uppercase tracking-widest text-violet-600/80 mb-2">
                Blind Spots — Worth Watching
              </p>
              <div className="space-y-2">
                {(topic as any).suggested_topics.map((s: any, sIdx: number) => (
                  <button
                    key={sIdx}
                    onClick={() =>
                      onDiscuss?.(
                        `Tell me more about "${s.topic}" and why it matters for this meeting. ${s.why || ''}`,
                      )
                    }
                    className="w-full text-left p-2 rounded-lg hover:bg-white/80 transition-colors group"
                  >
                    <p className="text-[13px] font-medium text-violet-800 group-hover:text-violet-900">
                      {s.topic}
                    </p>
                    {s.why && (
                      <p className="text-[11px] text-violet-600/70 mt-0.5">{s.why}</p>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Data limitations (cross-topic entry) */}
          {topic.data_gaps && topic.data_gaps.length > 0 && (
            <div className="mb-5 p-3.5 bg-amber-50/60 border border-amber-100 rounded-lg">
              <p className="text-[10px] font-bold uppercase tracking-widest text-amber-600/80 mb-2">
                Data Limitations
              </p>
              <ul className="space-y-1">
                {topic.data_gaps.map((g, gIdx) => (
                  <li key={gIdx} className="text-[13px] text-amber-800/80">— {g}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Verified-sources footer */}
          {authoritative > 0 && (
            <p className="flex items-center gap-1.5 text-[12px] text-emerald-600 font-medium mb-4">
              <ShieldCheck className="w-3.5 h-3.5" />
              Verified by {authoritative} authoritative {authoritative === 1 ? 'source' : 'sources'}
            </p>
          )}

          {topic.sources?.length > 0 ? (
            <div className="space-y-3">
              {topic.sources.map((source, sIdx) => {
                const tierStyle = TIER_STYLES[source.tier] || TIER_STYLES[2];
                return (
                  <div
                    key={sIdx}
                    className="border border-gray-100 rounded-lg p-4 hover:border-gray-200 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-3 mb-2">
                      <div className="flex items-center gap-2 flex-1 min-w-0">
                        <Globe className="w-4 h-4 text-gray-400 flex-shrink-0" />
                        <a
                          href={source.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-sm font-medium text-primary-600 hover:underline truncate"
                        >
                          {source.title || source.url}
                        </a>
                        <ExternalLink className="w-3 h-3 text-gray-400 flex-shrink-0" />
                      </div>

                      <div className="flex items-center gap-2 flex-shrink-0">
                        <span className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${tierStyle.bg} ${tierStyle.text}`}>
                          {tierStyle.icon}
                          {tierStyle.label}
                        </span>
                        <span className="text-xs text-gray-500">
                          {Math.round(source.credibility_score * 100)}%
                        </span>
                      </div>
                    </div>

                    {source.excerpt && (
                      <p className="text-sm text-gray-600 line-clamp-3">
                        {source.excerpt}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          ) : topic.topic !== 'Cross-topic findings' ? (
            <p className="text-sm text-gray-400 italic">No validated sources found for this topic</p>
          ) : null}
        </div>
        );
      })}
    </div>
  );
}
