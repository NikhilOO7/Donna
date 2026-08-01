'use client';

/**
 * KnowledgeGraphView
 *
 * Two-part rendering that matches the actual shape of extracted data
 * (many isolated entities, few relationships):
 *
 *  1. CONNECTIONS — a small force-directed graph of ONLY the entities
 *     that participate in a relationship. With ~25 nodes and labeled
 *     edges this is readable; putting all 136 entities on a ring never
 *     was.
 *  2. ENTITY EXPLORER — everything else as searchable chips grouped by
 *     type, sorted by section size. Low-signal types (dates, numbers)
 *     start collapsed.
 */

import React, { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Loader2, Network, Search } from 'lucide-react';
import { apiClient } from '@/lib/api-client';

interface GraphNode {
  id: string;
  label: string;
  type: string;
  confidence?: number | null;
}

interface GraphEdge {
  source: string;
  target: string;
  relationship: string;
  confidence?: number | null;
  context?: string | null;
}

interface Props {
  documentId: string;
}

const TYPE_COLORS: Record<string, string> = {
  PERSON: '#4f46e5',
  ORG: '#0ea5e9',
  GPE: '#14b8a6',
  LOC: '#14b8a6',
  DATE: '#f59e0b',
  TIME: '#f59e0b',
  MONEY: '#10b981',
  PRODUCT: '#ec4899',
  EVENT: '#a855f7',
  CARDINAL: '#94a3b8',
  NORP: '#f43f5e',
  UNKNOWN: '#94a3b8',
};

// Types that are usually noise on documents — collapsed by default
const LOW_SIGNAL_TYPES = new Set(['CARDINAL', 'DATE', 'TIME', 'ORDINAL', 'PERCENT', 'QUANTITY']);

const colorFor = (type: string) =>
  TYPE_COLORS[type?.toUpperCase()] || TYPE_COLORS.UNKNOWN;

/** Deterministic force layout for a small graph (no deps, no randomness). */
function forceLayout(
  nodes: GraphNode[],
  edges: GraphEdge[],
  width: number,
  height: number,
) {
  const n = nodes.length;
  const pos = nodes.map((_, i) => {
    const angle = (i / Math.max(n, 1)) * 2 * Math.PI;
    return {
      x: width / 2 + (width / 3) * Math.cos(angle),
      y: height / 2 + (height / 3) * Math.sin(angle),
    };
  });
  const index = new Map(nodes.map((node, i) => [node.id, i]));
  const springLen = Math.min(width, height) / 3.2;

  for (let iter = 0; iter < 220; iter++) {
    const cool = 1 - iter / 220;
    const fx = new Array(n).fill(0);
    const fy = new Array(n).fill(0);

    // Repulsion between every pair
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let dx = pos[i].x - pos[j].x;
        let dy = pos[i].y - pos[j].y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) { dx = 1; dy = 1; d2 = 2; }
        const f = 5200 / d2;
        const d = Math.sqrt(d2);
        fx[i] += (dx / d) * f; fy[i] += (dy / d) * f;
        fx[j] -= (dx / d) * f; fy[j] -= (dy / d) * f;
      }
    }
    // Springs along edges
    for (const e of edges) {
      const i = index.get(e.source);
      const j = index.get(e.target);
      if (i === undefined || j === undefined) continue;
      const dx = pos[j].x - pos[i].x;
      const dy = pos[j].y - pos[i].y;
      const d = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      const f = (d - springLen) * 0.045;
      fx[i] += (dx / d) * f; fy[i] += (dy / d) * f;
      fx[j] -= (dx / d) * f; fy[j] -= (dy / d) * f;
    }
    // Gentle pull to center + apply with cooling
    for (let i = 0; i < n; i++) {
      fx[i] += (width / 2 - pos[i].x) * 0.012;
      fy[i] += (height / 2 - pos[i].y) * 0.012;
      pos[i].x += Math.max(-14, Math.min(14, fx[i])) * cool;
      pos[i].y += Math.max(-14, Math.min(14, fy[i])) * cool;
      // Keep labels inside the frame
      pos[i].x = Math.max(56, Math.min(width - 56, pos[i].x));
      pos[i].y = Math.max(30, Math.min(height - 24, pos[i].y));
    }
  }
  return pos;
}

export default function KnowledgeGraphView({ documentId }: Props) {
  const [graph, setGraph] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [openTypes, setOpenTypes] = useState<Set<string> | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiClient
      .getDocumentKnowledgeGraph(documentId)
      .then((data) => {
        if (cancelled) return;
        setGraph({ nodes: data.nodes || [], edges: data.edges || [] });
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e?.message || 'Failed to load knowledge graph');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  // Deduplicate by (type, label) and collapse edges accordingly.
  const compact = useMemo(() => {
    if (!graph) return null;
    const idByLabel = new Map<string, string>();
    const keptNodes: GraphNode[] = [];
    for (const n of graph.nodes) {
      const key = `${n.type}::${(n.label || '').toLowerCase().trim()}`;
      if (!idByLabel.has(key)) {
        idByLabel.set(key, n.id);
        keptNodes.push(n);
      }
    }
    const idRemap = new Map<string, string>();
    for (const n of graph.nodes) {
      const key = `${n.type}::${(n.label || '').toLowerCase().trim()}`;
      idRemap.set(n.id, idByLabel.get(key) || n.id);
    }
    const edgeSet = new Map<string, GraphEdge>();
    for (const e of graph.edges) {
      const s = idRemap.get(e.source) || e.source;
      const t = idRemap.get(e.target) || e.target;
      if (s === t) continue;
      const k = `${s}->${t}::${e.relationship}`;
      if (!edgeSet.has(k)) edgeSet.set(k, { ...e, source: s, target: t });
    }
    return { nodes: keptNodes, edges: Array.from(edgeSet.values()) };
  }, [graph]);

  // Split: connected subgraph (drawn) vs isolated entities (chips).
  const split = useMemo(() => {
    if (!compact) return null;
    const degree = new Map<string, number>();
    for (const e of compact.edges) {
      degree.set(e.source, (degree.get(e.source) || 0) + 1);
      degree.set(e.target, (degree.get(e.target) || 0) + 1);
    }
    const connected = compact.nodes.filter((n) => (degree.get(n.id) || 0) > 0);
    const byType = new Map<string, GraphNode[]>();
    for (const n of compact.nodes) {
      const t = (n.type || 'UNKNOWN').toUpperCase();
      if (!byType.has(t)) byType.set(t, []);
      byType.get(t)!.push(n);
    }
    const sections = Array.from(byType.entries())
      .map(([type, ns]) => ({
        type,
        nodes: ns.sort((a, b) => a.label.localeCompare(b.label)),
      }))
      .sort((a, b) => b.nodes.length - a.nodes.length);
    return { connected, sections, degree };
  }, [compact]);

  // Default-open sections: everything except low-signal types.
  useEffect(() => {
    if (split && openTypes === null) {
      setOpenTypes(
        new Set(
          split.sections
            .filter((s) => !LOW_SIGNAL_TYPES.has(s.type))
            .map((s) => s.type),
        ),
      );
    }
  }, [split, openTypes]);

  const W = 680;
  const H = 380;
  const layout = useMemo(() => {
    if (!split || !compact) return null;
    if (split.connected.length === 0) return null;
    const pos = forceLayout(split.connected, compact.edges, W, H);
    return new Map(split.connected.map((n, i) => [n.id, pos[i]]));
  }, [split, compact]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8 text-gray-400 text-sm">
        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
        Loading knowledge graph...
      </div>
    );
  }
  if (error) {
    return <div className="py-4 text-sm text-red-500">Failed to load: {error}</div>;
  }
  if (!compact || !split || compact.nodes.length === 0) {
    return (
      <div className="py-6 text-center text-sm text-gray-400">
        <Network className="w-6 h-6 mx-auto mb-1 opacity-40" />
        No entities extracted yet
      </div>
    );
  }

  const q = search.trim().toLowerCase();
  const showEdgeLabels = compact.edges.length <= 30;

  return (
    <div className="space-y-4">
      {/* ---- Connections: force-directed graph of related entities only ---- */}
      {split.connected.length > 0 && layout && (
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[11px] font-bold uppercase tracking-wider text-gray-500 flex items-center gap-1.5">
              <Network className="w-3.5 h-3.5" />
              Connections · {compact.edges.length} relationships between{' '}
              {split.connected.length} entities
            </span>
          </div>
          <div className="rounded-xl bg-gradient-to-br from-slate-50 to-indigo-50/40 border border-slate-200">
            <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
              {compact.edges.map((e, idx) => {
                const a = layout.get(e.source);
                const b = layout.get(e.target);
                if (!a || !b) return null;
                const isActive =
                  hoveredNode && (hoveredNode === e.source || hoveredNode === e.target);
                const dimmed = hoveredNode && !isActive;
                const mx = (a.x + b.x) / 2;
                const my = (a.y + b.y) / 2;
                return (
                  <g key={idx} opacity={dimmed ? 0.15 : 1}>
                    <line
                      x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                      stroke={isActive ? '#4f46e5' : '#94a3b8'}
                      strokeWidth={isActive ? 2 : 1.2}
                      opacity={0.7}
                    />
                    {(showEdgeLabels || isActive) && (
                      <text
                        x={mx} y={my - 4}
                        textAnchor="middle"
                        fill={isActive ? '#4338ca' : '#64748b'}
                        stroke="#f8fafc"
                        strokeWidth={3}
                        paintOrder="stroke"
                        style={{ fontSize: 9.5, fontWeight: 600, letterSpacing: 0.2 }}
                      >
                        {e.relationship.replace(/_/g, ' ')}
                      </text>
                    )}
                  </g>
                );
              })}
              {split.connected.map((node) => {
                const p = layout.get(node.id);
                if (!p) return null;
                const isHovered = hoveredNode === node.id;
                const dimmed = hoveredNode && !isHovered;
                return (
                  <g
                    key={node.id}
                    opacity={dimmed ? 0.3 : 1}
                    onMouseEnter={() => setHoveredNode(node.id)}
                    onMouseLeave={() => setHoveredNode(null)}
                    style={{ cursor: 'pointer' }}
                  >
                    <circle
                      cx={p.x} cy={p.y}
                      r={isHovered ? 10 : 7}
                      fill={colorFor(node.type)}
                      stroke="white"
                      strokeWidth={2.5}
                      style={{ transition: 'r 120ms ease' }}
                    />
                    <text
                      x={p.x} y={p.y - (isHovered ? 16 : 13)}
                      textAnchor="middle"
                      fill="#1e293b"
                      stroke="#f8fafc"
                      strokeWidth={3.5}
                      paintOrder="stroke"
                      style={{ fontSize: 11, fontWeight: isHovered ? 700 : 600 }}
                    >
                      {node.label.length > 24 ? node.label.slice(0, 23) + '…' : node.label}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>
        </div>
      )}

      {/* ---- Entity explorer: everything, grouped + searchable ---- */}
      <div>
        <div className="flex items-center justify-between gap-3 mb-2">
          <span className="text-[11px] font-bold uppercase tracking-wider text-gray-500">
            All entities · {compact.nodes.length}
          </span>
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter entities..."
              className="pl-8 pr-3 py-1.5 text-xs bg-white border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-300 w-44"
            />
          </div>
        </div>

        <div className="space-y-1.5">
          {split.sections.map(({ type, nodes }) => {
            const matches = q
              ? nodes.filter((n) => n.label.toLowerCase().includes(q))
              : nodes;
            if (q && matches.length === 0) return null;
            const isOpen = q ? true : openTypes?.has(type) ?? true;
            return (
              <div key={type} className="border border-gray-100 rounded-lg overflow-hidden">
                <button
                  onClick={() => {
                    if (q) return;
                    setOpenTypes((prev) => {
                      const next = new Set(prev || []);
                      if (next.has(type)) next.delete(type);
                      else next.add(type);
                      return next;
                    });
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2 bg-gray-50/70 hover:bg-gray-50 transition-colors"
                >
                  {isOpen ? (
                    <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
                  ) : (
                    <ChevronRight className="w-3.5 h-3.5 text-gray-400" />
                  )}
                  <span
                    className="inline-block w-2.5 h-2.5 rounded-full"
                    style={{ backgroundColor: colorFor(type) }}
                  />
                  <span className="text-xs font-semibold text-gray-700">{type}</span>
                  <span className="text-[10px] text-gray-400">({matches.length})</span>
                </button>
                {isOpen && (
                  <div className="px-3 py-2 flex flex-wrap gap-1.5 bg-white">
                    {matches.map((n) => {
                      const linked = (split.degree.get(n.id) || 0) > 0;
                      return (
                        <span
                          key={n.id}
                          onMouseEnter={() => linked && setHoveredNode(n.id)}
                          onMouseLeave={() => setHoveredNode(null)}
                          className={`px-2 py-0.5 rounded-full text-[11px] border transition-colors ${
                            linked
                              ? 'border-indigo-200 bg-indigo-50 text-indigo-700 cursor-pointer'
                              : 'border-gray-150 bg-gray-50 text-gray-600'
                          }`}
                          title={linked ? 'Appears in the connections graph above' : undefined}
                        >
                          {n.label}
                        </span>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
