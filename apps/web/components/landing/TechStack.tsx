'use client';

import React from 'react';

const TECH = [
  { name: 'OpenAI GPT-4', role: 'All 15 agents — reasoning & synthesis', color: 'bg-emerald-50 border-emerald-200 text-emerald-800' },
  { name: 'Deepgram', role: 'Real-time speech-to-text (Nova-3)', color: 'bg-blue-50 border-blue-200 text-blue-800' },
  { name: 'Cartesia', role: 'Natural text-to-speech (Sonic-2)', color: 'bg-purple-50 border-purple-200 text-purple-800' },
  { name: 'LiveKit', role: 'WebRTC voice streaming & rooms', color: 'bg-pink-50 border-pink-200 text-pink-800' },
  { name: 'Exa', role: 'Semantic web search for research', color: 'bg-amber-50 border-amber-200 text-amber-800' },
  { name: 'Postmark', role: 'Transactional email delivery', color: 'bg-red-50 border-red-200 text-red-800' },
  { name: 'Qdrant', role: 'Vector DB — 4 embedding collections', color: 'bg-indigo-50 border-indigo-200 text-indigo-800' },
  { name: 'PostgreSQL', role: 'Meetings, decisions, knowledge graph', color: 'bg-sky-50 border-sky-200 text-sky-800' },
  { name: 'Redis', role: 'Caching, rate limiting, session state', color: 'bg-orange-50 border-orange-200 text-orange-800' },
];

export default function TechStack() {
  return (
    <section className="py-20 bg-gray-50">
      <div className="max-w-6xl mx-auto px-6">
        <div className="text-center mb-16">
          <h2 className="text-3xl lg:text-4xl font-bold text-gray-900 mb-4">
            Tech Stack
          </h2>
          <p className="text-gray-500 max-w-xl mx-auto text-lg">
            Production-grade infrastructure with 9 integrated services
          </p>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 stagger-children">
          {TECH.map((t) => (
            <div
              key={t.name}
              className={`border rounded-xl p-4 ${t.color} hover:shadow-md transition-all duration-300 hover:-translate-y-0.5`}
            >
              <h3 className="font-bold text-sm">{t.name}</h3>
              <p className="text-xs mt-1 opacity-80">{t.role}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
