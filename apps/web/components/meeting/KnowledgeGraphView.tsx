'use client';

/**
 * KnowledgeGraphView
 *
 * Lightweight SVG visualization of a document's entity / relationship
 * graph. Nodes are arranged on a circle and colored by entity type.
 * Hovered nodes highlight their incident edges; the legend lists
 * entity types in the current graph.
 */

import React, { useEffect, useMemo, useState } from 'react';
import { Network, Loader2 } from 'lucide-react';
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
  UNKNOWN: '#94a3b8',
};

const colorFor = (type: string) =>
  TYPE_COLORS[type?.toUpperCase()] || TYPE_COLORS.UNKNOWN;

export default function KnowledgeGraphView({ documentId }: Props) {
  const [graph, setGraph] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

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

  // Deduplicate nodes by label (spaCy commonly extracts the same entity
  // multiple times). Keep the first occurrence + collapse edges.
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
      if (!edgeSet.has(k)) {
        edgeSet.set(k, { ...e, source: s, target: t });
      }
    }
    return { nodes: keptNodes, edges: Array.from(edgeSet.values()) };
  }, [graph]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8 text-gray-400 text-sm">
        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
        Loading knowledge graph...
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-4 text-sm text-red-500">Failed to load: {error}</div>
    );
  }

  if (!compact || compact.nodes.length === 0) {
    return (
      <div className="py-6 text-center text-sm text-gray-400">
        <Network className="w-6 h-6 mx-auto mb-1 opacity-40" />
        No entities extracted yet
      </div>
    );
  }

  // Geometry: radial layout
  const size = 360;
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 50;
  const nodeCount = compact.nodes.length;
  const positions = compact.nodes.map((n, i) => {
    const angle = (i / nodeCount) * 2 * Math.PI - Math.PI / 2;
    return {
      id: n.id,
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle),
      node: n,
    };
  });
  const posById = new Map(positions.map((p) => [p.id, p]));

  const typesInGraph = Array.from(new Set(compact.nodes.map((n) => n.type))).slice(0, 6);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <Network className="w-3.5 h-3.5" />
          <span>
            {compact.nodes.length} entities · {compact.edges.length} relationships
          </span>
        </div>
        <div className="flex flex-wrap gap-2 text-[10px]">
          {typesInGraph.map((t) => (
            <span key={t} className="flex items-center gap-1 text-gray-500">
              <span
                className="inline-block w-2 h-2 rounded-full"
                style={{ backgroundColor: colorFor(t) }}
              />
              {t}
            </span>
          ))}
        </div>
      </div>

      <div className="rounded-xl bg-gradient-to-br from-slate-50 to-indigo-50/40 border border-slate-200 p-2">
        <svg
          viewBox={`0 0 ${size} ${size}`}
          className="w-full max-h-[420px]"
        >
          {/* edges first so they render under nodes */}
          {compact.edges.map((e, idx) => {
            const a = posById.get(e.source);
            const b = posById.get(e.target);
            if (!a || !b) return null;
            const isActive =
              hoveredNode && (hoveredNode === e.source || hoveredNode === e.target);
            return (
              <g key={idx}>
                <line
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke={isActive ? '#4f46e5' : '#cbd5e1'}
                  strokeWidth={isActive ? 1.6 : 0.8}
                  opacity={isActive ? 0.95 : 0.55}
                />
                {isActive && (
                  <text
                    x={(a.x + b.x) / 2}
                    y={(a.y + b.y) / 2 - 4}
                    textAnchor="middle"
                    className="fill-indigo-600"
                    style={{ fontSize: 9, fontWeight: 600 }}
                  >
                    {e.relationship.replace(/_/g, ' ')}
                  </text>
                )}
              </g>
            );
          })}

          {/* nodes */}
          {positions.map(({ id, x, y, node }) => {
            const isHovered = hoveredNode === id;
            return (
              <g
                key={id}
                onMouseEnter={() => setHoveredNode(id)}
                onMouseLeave={() => setHoveredNode(null)}
                style={{ cursor: 'pointer' }}
              >
                <circle
                  cx={x}
                  cy={y}
                  r={isHovered ? 9 : 6}
                  fill={colorFor(node.type)}
                  stroke="white"
                  strokeWidth={2}
                  opacity={hoveredNode && !isHovered ? 0.35 : 1}
                  style={{ transition: 'r 120ms ease' }}
                />
                <text
                  x={x}
                  y={y - (isHovered ? 14 : 11)}
                  textAnchor="middle"
                  className="fill-slate-700"
                  style={{ fontSize: 10, fontWeight: isHovered ? 700 : 500 }}
                >
                  {node.label.length > 18
                    ? node.label.slice(0, 17) + '…'
                    : node.label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
