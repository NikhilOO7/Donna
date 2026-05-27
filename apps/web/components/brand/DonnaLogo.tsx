'use client';

import React from 'react';

type Size = 'sm' | 'md' | 'lg';

interface DonnaLogoProps {
  /** Show the "Donna" wordmark + tagline next to the avatar. */
  showWordmark?: boolean;
  /** Show the "She already knew." tagline under the wordmark. */
  showTagline?: boolean;
  size?: Size;
  className?: string;
}

const SIZES: Record<Size, { box: string; mono: string; name: string; tag: string }> = {
  sm: { box: 'w-8 h-8 rounded-lg', mono: 'text-lg', name: 'text-base', tag: 'text-[10px]' },
  md: { box: 'w-10 h-10 rounded-xl', mono: 'text-2xl', name: 'text-lg', tag: 'text-[11px]' },
  lg: { box: 'w-14 h-14 rounded-2xl', mono: 'text-4xl', name: 'text-2xl', tag: 'text-xs' },
};

/**
 * Donna's mark — a gradient "D" monogram that quietly breathes, with a slow
 * diagonal sheen sweeping across it. Editorial serif monogram for a bit of
 * Suits-era class. Reuse anywhere the brand appears (header, landing, emails).
 */
export default function DonnaLogo({
  showWordmark = true,
  showTagline = true,
  size = 'sm',
  className = '',
}: DonnaLogoProps) {
  const s = SIZES[size];

  return (
    <div className={`flex items-center gap-2.5 group ${className}`}>
      {/* Avatar */}
      <div
        className={`relative ${s.box} flex items-center justify-center overflow-hidden
          bg-gradient-to-br from-primary-400 via-primary-600 to-primary-800
          animate-gradient animate-donna-breathe
          ring-1 ring-white/20 select-none`}
      >
        {/* Diagonal sheen */}
        <span
          className="pointer-events-none absolute inset-y-0 left-0 w-1/3
            bg-gradient-to-r from-transparent via-white/40 to-transparent
            animate-donna-sheen"
        />
        {/* Top highlight */}
        <span className="pointer-events-none absolute inset-x-0 top-0 h-1/2 bg-white/10 rounded-t-[inherit]" />
        {/* Monogram */}
        <span
          className={`relative font-serif font-bold text-white leading-none ${s.mono}
            drop-shadow-[0_1px_2px_rgba(0,0,0,0.25)]`}
          style={{ fontFamily: 'Georgia, "Times New Roman", serif' }}
        >
          D
        </span>
      </div>

      {/* Wordmark */}
      {showWordmark && (
        <div className="leading-tight">
          <h1 className={`font-bold text-gray-900 leading-tight tracking-tight ${s.name}`}>
            Donna
          </h1>
          {showTagline && (
            <p className={`text-gray-400 leading-tight italic ${s.tag}`}>She already knew.</p>
          )}
        </div>
      )}
    </div>
  );
}
