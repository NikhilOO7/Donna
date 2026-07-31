'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Minus, Plus, Maximize2 } from 'lucide-react';
import NudgeCard from './NudgeCard';

interface CanvasBoardProps {
  meetingId: string;
  nudges: any[];
  onPin?: (nudgeId: string) => void;
  onDismiss?: (nudgeId: string) => void;
  /** Server-synced layout (shared across the team). */
  serverPositions?: Positions;
  /** Persist the layout server-side (leader-only). */
  onPersist?: (positions: Positions) => void;
}

type Positions = Record<string, { x: number; y: number }>;

const CARD_W = 300;
const GAP = 24;

/** Default layout: loose grid, staggered like the PDF's canvas mockup. */
function defaultPositions(nudges: any[]): Positions {
  const pos: Positions = {};
  nudges.forEach((n, i) => {
    const col = i % 3;
    const row = Math.floor(i / 3);
    pos[n.id] = {
      x: 30 + col * (CARD_W + GAP) + (row % 2 === 1 ? 40 : 0),
      y: 30 + row * 210 + col * 14,
    };
  });
  return pos;
}

export default function CanvasBoard({
  meetingId, nudges, onPin, onDismiss, serverPositions, onPersist,
}: CanvasBoardProps) {
  const storageKey = `donna-canvas-${meetingId}`;
  const [positions, setPositions] = useState<Positions>({});
  const [zoom, setZoom] = useState(0.85);
  const dragRef = useRef<{ id: string; startX: number; startY: number; origX: number; origY: number } | null>(null);
  const boardRef = useRef<HTMLDivElement>(null);

  // Load layout: server-synced first, localStorage fallback, defaults last
  useEffect(() => {
    let saved: Positions = {};
    try {
      saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
    } catch {
      saved = {};
    }
    const defaults = defaultPositions(nudges);
    const merged: Positions = {};
    nudges.forEach((n) => {
      merged[n.id] = serverPositions?.[n.id] || saved[n.id] || defaults[n.id];
    });
    setPositions(merged);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meetingId, nudges.length, serverPositions]);

  const persist = useCallback(
    (pos: Positions) => {
      try {
        localStorage.setItem(storageKey, JSON.stringify(pos));
      } catch {
        /* storage full/blocked — canvas still works, positions just don't persist */
      }
    },
    [storageKey],
  );

  const onPointerDown = (e: React.PointerEvent, id: string) => {
    // Don't start a drag from buttons/links inside the card
    const target = e.target as HTMLElement;
    if (target.closest('button') || target.closest('a')) return;
    const p = positions[id];
    if (!p) return;
    dragRef.current = { id, startX: e.clientX, startY: e.clientY, origX: p.x, origY: p.y };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d) return;
    const dx = (e.clientX - d.startX) / zoom;
    const dy = (e.clientY - d.startY) / zoom;
    setPositions((prev) => ({
      ...prev,
      [d.id]: { x: Math.max(0, d.origX + dx), y: Math.max(0, d.origY + dy) },
    }));
  };

  const onPointerUp = () => {
    if (dragRef.current) {
      setPositions((prev) => {
        persist(prev);
        onPersist?.(prev); // server-side, shared with the team
        return prev;
      });
      dragRef.current = null;
    }
  };

  return (
    <div className="relative rounded-xl border border-gray-200/60 shadow-card overflow-hidden bg-white">
      {/* Zoom controls */}
      <div className="absolute top-3 right-3 z-20 flex items-center gap-1 bg-white rounded-lg border border-gray-200 shadow-sm px-1.5 py-1">
        <button
          onClick={() => setZoom((z) => Math.max(0.4, +(z - 0.15).toFixed(2)))}
          className="p-1 text-gray-500 hover:text-gray-800 rounded hover:bg-gray-100"
        >
          <Minus className="w-3.5 h-3.5" />
        </button>
        <span className="text-[11px] font-medium text-gray-600 w-9 text-center">
          {Math.round(zoom * 100)}%
        </span>
        <button
          onClick={() => setZoom((z) => Math.min(1.5, +(z + 0.15).toFixed(2)))}
          className="p-1 text-gray-500 hover:text-gray-800 rounded hover:bg-gray-100"
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={() => setZoom(0.85)}
          title="Reset zoom"
          className="p-1 text-gray-500 hover:text-gray-800 rounded hover:bg-gray-100"
        >
          <Maximize2 className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Dotted-grid board */}
      <div
        ref={boardRef}
        className="relative h-[560px] overflow-auto"
        style={{
          backgroundImage: 'radial-gradient(circle, #d4d4d8 1px, transparent 1px)',
          backgroundSize: '22px 22px',
          backgroundColor: '#fafafa',
        }}
      >
        {nudges.length === 0 ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-400">
            <p className="text-sm font-medium text-gray-500">Canvas is empty</p>
            <p className="text-xs text-gray-400 mt-1">
              Insights appear here as Donna generates them — drag to arrange and cluster.
            </p>
          </div>
        ) : (
          <div
            className="relative origin-top-left"
            style={{
              transform: `scale(${zoom})`,
              width: `${(1 / zoom) * 100}%`,
              height: `${(1 / zoom) * 100}%`,
            }}
          >
            {nudges.map((n) => {
              const p = positions[n.id];
              if (!p) return null;
              return (
                <div
                  key={n.id}
                  onPointerDown={(e) => onPointerDown(e, n.id)}
                  onPointerMove={onPointerMove}
                  onPointerUp={onPointerUp}
                  className="absolute cursor-grab active:cursor-grabbing select-none"
                  style={{ left: p.x, top: p.y, width: CARD_W }}
                >
                  <NudgeCard nudge={n} onPin={onPin} onDismiss={onDismiss} compact />
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
