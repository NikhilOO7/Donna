'use client';

import React, { useState } from 'react';
import { ChevronDown } from 'lucide-react';

interface FlowNode {
  label: string;
  type: 'input' | 'agent' | 'output' | 'parallel';
  color: string;
  children?: FlowNode[];
}

const FLOWCHARTS: {
  title: string;
  phase: string;
  color: string;
  nodes: FlowNode[];
}[] = [
  {
    title: 'Pre-Meeting Research Pipeline',
    phase: 'Phase 1',
    color: 'from-amber-500 to-orange-500',
    nodes: [
      { label: 'Meeting Brief', type: 'input', color: 'bg-gray-100 text-gray-700' },
      { label: 'Topic Extraction Agent', type: 'agent', color: 'bg-amber-100 text-amber-800' },
      {
        label: 'Parallel Search (per topic)', type: 'parallel', color: 'bg-orange-50 text-orange-800',
        children: [
          { label: 'Exa Search Agent', type: 'agent', color: 'bg-amber-100 text-amber-800' },
        ],
      },
      { label: 'Validation Agent', type: 'agent', color: 'bg-amber-100 text-amber-800' },
      { label: 'Synthesis Agent', type: 'agent', color: 'bg-amber-100 text-amber-800' },
      { label: 'Research Brief + Qdrant Embeddings', type: 'output', color: 'bg-green-100 text-green-800' },
    ],
  },
  {
    title: 'Live Meeting Intelligence',
    phase: 'Phase 2',
    color: 'from-blue-500 to-indigo-500',
    nodes: [
      { label: 'Live Audio (LiveKit + Deepgram)', type: 'input', color: 'bg-gray-100 text-gray-700' },
      { label: 'Transcript Agent', type: 'agent', color: 'bg-blue-100 text-blue-800' },
      {
        label: 'Tool Agents (triggered on strategic moments)', type: 'parallel', color: 'bg-indigo-50 text-indigo-800',
        children: [
          { label: 'Context Agent (RAG)', type: 'agent', color: 'bg-blue-100 text-blue-800' },
          { label: 'Fact-Check Agent', type: 'agent', color: 'bg-blue-100 text-blue-800' },
          { label: 'Scribe Agent', type: 'agent', color: 'bg-blue-100 text-blue-800' },
          { label: 'Insight Agent', type: 'agent', color: 'bg-blue-100 text-blue-800' },
        ],
      },
      { label: 'Nudge Card Generator', type: 'agent', color: 'bg-blue-100 text-blue-800' },
      { label: 'WebSocket → Nudge Cards UI', type: 'output', color: 'bg-green-100 text-green-800' },
    ],
  },
  {
    title: 'Post-Meeting Synthesis',
    phase: 'Phase 3',
    color: 'from-violet-500 to-purple-500',
    nodes: [
      { label: 'Meeting End Trigger', type: 'input', color: 'bg-gray-100 text-gray-700' },
      { label: 'Data Aggregator (transcript + decisions + research + nudges)', type: 'agent', color: 'bg-violet-100 text-violet-800' },
      { label: 'Summary Agent (GPT-4)', type: 'agent', color: 'bg-violet-100 text-violet-800' },
      { label: 'Delivery Agent (Postmark)', type: 'agent', color: 'bg-violet-100 text-violet-800' },
      { label: 'Executive Summary Email → Attendees', type: 'output', color: 'bg-green-100 text-green-800' },
    ],
  },
];

function FlowNodeView({ node, isLast }: { node: FlowNode; isLast: boolean }) {
  return (
    <div className="flex flex-col items-center">
      {/* Node */}
      <div className={`px-4 py-2.5 rounded-xl text-sm font-medium text-center max-w-xs ${node.color} shadow-sm border border-black/5`}>
        {node.label}
      </div>

      {/* Parallel children */}
      {node.children && (
        <div className="mt-3 mb-3 flex flex-wrap items-center justify-center gap-2">
          {node.children.map((child, i) => (
            <div key={i} className={`px-3 py-1.5 rounded-lg text-xs font-medium ${child.color} shadow-sm border border-black/5`}>
              {child.label}
            </div>
          ))}
        </div>
      )}

      {/* Connector */}
      {!isLast && (
        <div className="w-0.5 h-6 bg-gray-300 my-1" />
      )}
    </div>
  );
}

export default function AgentFlowchart() {
  const [expanded, setExpanded] = useState<number | null>(0);

  return (
    <section className="py-20 bg-white">
      <div className="max-w-4xl mx-auto px-6">
        <div className="text-center mb-16">
          <h2 className="text-3xl lg:text-4xl font-bold text-gray-900 mb-4">
            Agent Architecture
          </h2>
          <p className="text-gray-500 max-w-xl mx-auto text-lg">
            Each phase has its own specialized agent pipeline
          </p>
        </div>

        <div className="space-y-4 stagger-children">
          {FLOWCHARTS.map((chart, idx) => (
            <div key={chart.title} className="border border-gray-200 rounded-2xl overflow-hidden shadow-sm hover:shadow-md transition-shadow">
              {/* Header (clickable) */}
              <button
                onClick={() => setExpanded(expanded === idx ? null : idx)}
                className="w-full flex items-center justify-between px-6 py-4 bg-gray-50 hover:bg-gray-100 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <span className={`px-2.5 py-1 rounded-lg text-xs font-bold text-white bg-gradient-to-r ${chart.color}`}>
                    {chart.phase}
                  </span>
                  <h3 className="text-base font-semibold text-gray-900">{chart.title}</h3>
                </div>
                <ChevronDown className={`w-5 h-5 text-gray-400 transition-transform duration-300 ${expanded === idx ? 'rotate-0' : '-rotate-90'}`} />
              </button>

              {/* Flowchart */}
              {expanded === idx && (
                <div className="p-8 flex flex-col items-center animate-fade-up">
                  {chart.nodes.map((node, i) => (
                    <FlowNodeView key={i} node={node} isLast={i === chart.nodes.length - 1} />
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
