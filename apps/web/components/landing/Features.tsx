'use client';

import React from 'react';
import {
  Boxes, ShieldCheck, FileSearch, BarChart3, ShieldAlert, GitBranch
} from 'lucide-react';

const FEATURES = [
  {
    icon: Boxes,
    title: 'Dependency Injection',
    description: 'ServiceContainer with protocol-based abstractions. No globals, full testability.',
  },
  {
    icon: ShieldAlert,
    title: 'Circuit Breakers',
    description: 'Per-service resilience with retry, exponential backoff, and automatic recovery.',
  },
  {
    icon: FileSearch,
    title: 'Structured Logging',
    description: 'JSON logs with request-ID propagation via structlog. Every request is traceable.',
  },
  {
    icon: BarChart3,
    title: 'Prometheus Metrics',
    description: 'HTTP latencies, RAG query duration, external API calls — all at /metrics.',
  },
  {
    icon: ShieldCheck,
    title: 'Rate Limiting',
    description: 'Redis-backed slowapi. Upload: 5/min, Query: 30/min. API key + IP based.',
  },
  {
    icon: GitBranch,
    title: 'Knowledge Graph',
    description: 'Entity relationships extracted by GPT-4, stored in PostgreSQL, queried via NetworkX.',
  },
];

export default function Features() {
  return (
    <section className="py-20 bg-white">
      <div className="max-w-6xl mx-auto px-6">
        <div className="text-center mb-16">
          <h2 className="text-3xl lg:text-4xl font-bold text-gray-900 mb-4">
            Production Engineering
          </h2>
          <p className="text-gray-500 max-w-xl mx-auto text-lg">
            Staff-level patterns that demonstrate operational maturity
          </p>
        </div>

        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6 stagger-children">
          {FEATURES.map((f) => (
            <div
              key={f.title}
              className="group bg-white border border-gray-200 rounded-2xl p-6 hover:border-[#4f46e5]/30 hover:shadow-lg transition-all duration-300 hover:-translate-y-1"
            >
              <div className="w-12 h-12 bg-[#eef2ff] rounded-xl flex items-center justify-center mb-4 group-hover:bg-[#4f46e5] transition-colors duration-300">
                <f.icon className="w-6 h-6 text-[#4f46e5] group-hover:text-white transition-colors duration-300" />
              </div>
              <h3 className="text-base font-bold text-gray-900 mb-2">{f.title}</h3>
              <p className="text-sm text-gray-500 leading-relaxed">{f.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
