'use client';

import React from 'react';
import { Search, Mic, FileText, ArrowRight } from 'lucide-react';

const PHASES = [
  {
    icon: Search,
    title: 'Before Meeting',
    subtitle: 'Research & Prep',
    agents: '4 Agents',
    color: 'from-amber-500 to-orange-500',
    bg: 'bg-amber-50',
    border: 'border-amber-200',
    items: [
      'Topic Extraction Agent analyzes meeting brief',
      'Search Agent queries Exa for web intelligence',
      'Validation Agent scores & classifies sources (Tier 1/2/3)',
      'Synthesis Agent produces executive summary',
    ],
  },
  {
    icon: Mic,
    title: 'During Meeting',
    subtitle: 'Live Intelligence',
    agents: '6 Agents',
    color: 'from-blue-500 to-indigo-500',
    bg: 'bg-blue-50',
    border: 'border-blue-200',
    items: [
      'Transcript Agent captures speech with speaker labels',
      'Context Agent (RAG) searches docs + research',
      'Fact-Check Agent verifies claims via Exa',
      'Scribe Agent detects decisions & action items',
      'Insight Agent surfaces relevant pre-meeting research',
      'Nudge Generator pushes cards to UI via WebSocket',
    ],
  },
  {
    icon: FileText,
    title: 'After Meeting',
    subtitle: 'Summary & Delivery',
    agents: '2 Agents',
    color: 'from-violet-500 to-purple-500',
    bg: 'bg-violet-50',
    border: 'border-violet-200',
    items: [
      'Summary Agent synthesizes transcript + decisions + research',
      'Delivery Agent formats HTML email & sends via Postmark',
    ],
  },
];

export default function PhaseFlow() {
  return (
    <section className="py-20 bg-gray-50">
      <div className="max-w-6xl mx-auto px-6">
        <div className="text-center mb-16">
          <h2 className="text-3xl lg:text-4xl font-bold text-gray-900 mb-4">
            How It Works
          </h2>
          <p className="text-gray-500 max-w-xl mx-auto text-lg">
            Three phases, fifteen agents, one seamless workflow
          </p>
        </div>

        <div className="grid lg:grid-cols-3 gap-6 stagger-children">
          {PHASES.map((phase, idx) => (
            <div key={phase.title} className="relative">
              {/* Connector arrow (between cards) */}
              {idx < PHASES.length - 1 && (
                <div className="hidden lg:flex absolute -right-3 top-1/2 -translate-y-1/2 z-10">
                  <ArrowRight className="w-6 h-6 text-gray-300" />
                </div>
              )}

              <div className={`${phase.bg} border ${phase.border} rounded-2xl p-6 h-full hover:shadow-lg transition-all duration-300 hover:-translate-y-1`}>
                {/* Header */}
                <div className="flex items-center gap-3 mb-4">
                  <div className={`w-12 h-12 bg-gradient-to-br ${phase.color} rounded-xl flex items-center justify-center shadow-md`}>
                    <phase.icon className="w-6 h-6 text-white" />
                  </div>
                  <div>
                    <h3 className="text-lg font-bold text-gray-900">{phase.title}</h3>
                    <p className="text-sm text-gray-500">{phase.subtitle}</p>
                  </div>
                </div>

                {/* Agent count badge */}
                <div className={`inline-flex items-center px-3 py-1 bg-white rounded-full text-xs font-semibold mb-4 shadow-sm`}>
                  <span className={`w-2 h-2 rounded-full bg-gradient-to-br ${phase.color} mr-2`} />
                  {phase.agents}
                </div>

                {/* Agent list */}
                <ul className="space-y-2.5">
                  {phase.items.map((item, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                      <span className="w-1.5 h-1.5 rounded-full bg-gray-400 mt-2 flex-shrink-0" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
