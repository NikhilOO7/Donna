'use client';

import React from 'react';
import { Check, AlertTriangle, ChevronDown } from 'lucide-react';

export type StepStatus = 'completed' | 'active' | 'pending' | 'error';

interface TimelineStepProps {
  stepNumber: number;
  title: string;
  subtitle: string;
  status: StepStatus;
  statusLabel?: string;
  icon: React.ReactNode;
  isExpanded: boolean;
  isLast?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

const STATUS_STYLES: Record<StepStatus, {
  circle: string; ring: string; badge: string; badgeText: string; line: string;
}> = {
  completed: {
    circle: 'bg-gradient-to-br from-emerald-400 to-emerald-600',
    ring: 'ring-emerald-100',
    badge: 'bg-emerald-50 border-emerald-200',
    badgeText: 'text-emerald-700',
    line: 'from-emerald-400 to-emerald-300',
  },
  active: {
    circle: 'bg-gradient-to-br from-primary-400 to-primary-600 shadow-glow-primary',
    ring: 'ring-primary-100',
    badge: 'bg-primary-50 border-primary-200',
    badgeText: 'text-primary-700',
    line: 'from-primary-300 to-gray-200',
  },
  pending: {
    circle: 'bg-gradient-to-br from-gray-200 to-gray-300',
    ring: 'ring-gray-100',
    badge: 'bg-gray-50 border-gray-200',
    badgeText: 'text-gray-500',
    line: 'from-gray-200 to-gray-200',
  },
  error: {
    circle: 'bg-gradient-to-br from-red-400 to-red-600 shadow-glow-red',
    ring: 'ring-red-100',
    badge: 'bg-red-50 border-red-200',
    badgeText: 'text-red-700',
    line: 'from-red-300 to-gray-200',
  },
};

export default function TimelineStep({
  stepNumber,
  title,
  subtitle,
  status,
  statusLabel,
  icon,
  isExpanded,
  isLast = false,
  onClick,
  children,
}: TimelineStepProps) {
  const s = STATUS_STYLES[status];

  return (
    <div className="relative flex gap-5">
      {/* Left: Circle + Connector Line */}
      <div className="flex flex-col items-center">
        {/* Step Circle */}
        <button
          onClick={onClick}
          className={`
            w-11 h-11 rounded-full flex items-center justify-center
            ring-[5px] flex-shrink-0 z-10
            transition-all duration-300 hover:scale-110
            ${s.circle} ${s.ring}
          `}
        >
          {status === 'completed' ? (
            <Check className="w-5 h-5 text-white drop-shadow-sm" />
          ) : status === 'error' ? (
            <AlertTriangle className="w-5 h-5 text-white drop-shadow-sm" />
          ) : status === 'active' ? (
            <span className="relative flex h-5 w-5 items-center justify-center">
              <span className="text-white text-sm font-bold">{stepNumber}</span>
            </span>
          ) : (
            <span className="text-white/80 text-sm font-bold">{stepNumber}</span>
          )}
        </button>

        {/* Connector Line */}
        {!isLast && (
          <div className={`w-0.5 flex-1 min-h-[28px] bg-gradient-to-b ${s.line}`} />
        )}
      </div>

      {/* Right: Content */}
      <div className={`flex-1 ${!isLast ? 'pb-8' : 'pb-2'}`}>
        {/* Header */}
        <button
          onClick={onClick}
          className="w-full flex items-center justify-between group text-left py-1"
        >
          <div>
            <div className="flex items-center gap-3">
              <h3 className={`text-[15px] font-semibold transition-colors ${
                status === 'pending' ? 'text-gray-400' : 'text-gray-900'
              }`}>
                {title}
              </h3>
              <span className={`
                inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium
                border transition-all ${s.badge} ${s.badgeText}
              `}>
                {status === 'active' && (
                  <span className="w-1.5 h-1.5 bg-current rounded-full mr-1.5 animate-pulse" />
                )}
                {statusLabel || status}
              </span>
            </div>
            <p className={`text-sm mt-0.5 ${status === 'pending' ? 'text-gray-300' : 'text-gray-500'}`}>
              {subtitle}
            </p>
          </div>
          <ChevronDown className={`
            w-5 h-5 text-gray-400 transition-all duration-300
            group-hover:text-gray-600
            ${isExpanded ? 'rotate-0' : '-rotate-90'}
          `} />
        </button>

        {/* Expandable Content with smooth transition */}
        <div className={`
          overflow-hidden transition-all duration-400 ease-out
          ${isExpanded ? 'max-h-[2000px] opacity-100 mt-4' : 'max-h-0 opacity-0 mt-0'}
        `}>
          <div className={`
            rounded-xl border bg-white/50 backdrop-blur-sm p-5
            transition-all duration-300
            ${isExpanded ? 'border-gray-200 shadow-card' : 'border-transparent'}
          `}>
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
