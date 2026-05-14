'use client';

import React from 'react';
import { Globe, Shield, ShieldCheck, ExternalLink, BookOpen } from 'lucide-react';

interface ResearchBriefViewProps {
  research: {
    status: string;
    source_count: number;
    executive_summary?: string;
    topics: {
      topic: string;
      rationale: string;
      sources: {
        url: string;
        title: string;
        excerpt: string;
        tier: number;
        credibility_score: number;
      }[];
    }[];
  };
}

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

export default function ResearchBriefView({ research }: ResearchBriefViewProps) {
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

      {/* Topics */}
      {research.topics?.map((topic, idx) => (
        <div key={idx} className="bg-white rounded-lg border border-gray-200 p-6">
          <div className="mb-4">
            <h4 className="text-lg font-semibold text-gray-900">{topic.topic}</h4>
            <p className="text-sm text-gray-500 mt-1">{topic.rationale}</p>
          </div>

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
          ) : (
            <p className="text-sm text-gray-400 italic">No validated sources found for this topic</p>
          )}
        </div>
      ))}
    </div>
  );
}
