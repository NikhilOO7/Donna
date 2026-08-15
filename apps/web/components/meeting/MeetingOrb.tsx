'use client';

import React from 'react';

export type OrbState = 'idle' | 'listening' | 'thinking' | 'ended';

interface Props {
  state: OrbState;
  onClick?: () => void;
  disabled?: boolean;
}

/**
 * The meeting orb — the single focal point of the live screen.
 *
 * The old live view was a dashboard: transcript, nudge feed, controls and
 * filters all competing at once. But during a meeting the user is *talking to
 * people*, not operating software. Anything on screen that asks to be read is
 * a tax on their attention.
 *
 * So the live screen has exactly one object, and its colour and motion carry
 * the entire state: warm grey when idle, cool blue while listening, a slow
 * shimmer while an agent is working. Everything else is either a toast that
 * announces itself and leaves, or behind a deliberate tap.
 *
 * Motion is intentionally slow (6–10s cycles). A fast pulse reads as urgency,
 * and urgency is the wrong feeling for something sitting in the corner of a
 * conversation for an hour.
 */
export default function MeetingOrb({ state, onClick, disabled }: Props) {
  const interactive = !!onClick && !disabled;

  return (
    <div className="relative grid place-items-center select-none">
      {/* Ambient halo — only while active, so idle stays visually silent */}
      {(state === 'listening' || state === 'thinking') && (
        <div
          aria-hidden
          className="absolute rounded-full blur-2xl opacity-60 animate-orb-halo"
          style={{
            width: 340,
            height: 340,
            background:
              state === 'thinking'
                ? 'radial-gradient(circle, rgba(167,139,250,.45), transparent 70%)'
                : 'radial-gradient(circle, rgba(147,178,246,.40), transparent 70%)',
          }}
        />
      )}

      <button
        type="button"
        onClick={interactive ? onClick : undefined}
        disabled={!interactive}
        aria-label={
          state === 'idle'
            ? 'Start the meeting'
            : state === 'ended'
              ? 'Meeting ended'
              : 'Meeting is live'
        }
        className={[
          'relative rounded-full transition-transform duration-500',
          interactive ? 'cursor-pointer hover:scale-[1.02] active:scale-[0.99]' : 'cursor-default',
          state === 'listening' || state === 'thinking' ? 'animate-orb-breathe' : '',
        ].join(' ')}
        style={{ width: 260, height: 260 }}
      >
        <span
          aria-hidden
          className="absolute inset-0 rounded-full"
          style={{
            background:
              state === 'idle'
                ? 'radial-gradient(circle at 38% 32%, #ffffff 0%, #f4f2ee 45%, #e8e4dc 100%)'
                : state === 'thinking'
                  ? 'radial-gradient(circle at 38% 32%, #ffffff 0%, #dcd9fb 42%, #bcc6f2 100%)'
                  : state === 'ended'
                    ? 'radial-gradient(circle at 38% 32%, #ffffff 0%, #eef0f3 45%, #dfe3e8 100%)'
                    : 'radial-gradient(circle at 38% 32%, #ffffff 0%, #dbe4fb 42%, #b9c8f0 100%)',
            boxShadow:
              state === 'idle' || state === 'ended'
                ? '0 24px 60px -20px rgba(15,23,42,.16), inset 0 -18px 40px -24px rgba(15,23,42,.18)'
                : '0 28px 70px -18px rgba(99,102,241,.35), inset 0 -18px 40px -22px rgba(79,70,229,.25)',
          }}
        />
        {/* Specular highlight: gives the orb physicality without a texture */}
        <span
          aria-hidden
          className="absolute rounded-full opacity-70"
          style={{
            top: '14%',
            left: '20%',
            width: '38%',
            height: '26%',
            background: 'radial-gradient(ellipse at center, rgba(255,255,255,.95), transparent 70%)',
            filter: 'blur(6px)',
          }}
        />
      </button>
    </div>
  );
}
