'use client';

import React from 'react';
import { Check, Lock } from 'lucide-react';

export type WizardStepState =
  | 'done'      // finished — revisitable
  | 'current'   // the screen you are on
  | 'available' // reachable, not started
  | 'locked';   // genuinely not reachable yet

export interface WizardStepMeta {
  id: number;
  title: string;
  hint: string;          // one line: what this step is for
  status: WizardStepState;
  statusLabel?: string;  // live state, e.g. "3 sources", "live now"
  icon: React.ReactNode;
  lockedReason?: string; // why it can't be opened — shown on hover
}

interface Props {
  steps: WizardStepMeta[];
  onSelect: (id: number) => void;
}

/**
 * Persistent progress rail for the meeting journey.
 *
 * Replaces the previous accordion, where all four phases were stacked on one
 * screen and every one competed for attention. A wizard makes the *current*
 * task the only thing on screen, and the rail answers the two questions the
 * accordion left implicit: where am I, and what is left.
 *
 * Completed steps stay clickable — this is a journey, not a cage. Only steps
 * that genuinely cannot function yet (a summary before the meeting has ended)
 * are locked, and they say why rather than silently refusing.
 */
export default function WizardStepper({ steps, onSelect }: Props) {
  return (
    <nav aria-label="Meeting progress" className="mb-8">
      <ol className="flex items-stretch gap-2 sm:gap-3">
        {steps.map((step, i) => {
          const clickable = step.status !== 'locked';
          const isCurrent = step.status === 'current';

          return (
            <li key={step.id} className="flex-1 min-w-0">
              <button
                type="button"
                onClick={() => clickable && onSelect(step.id)}
                disabled={!clickable}
                aria-current={isCurrent ? 'step' : undefined}
                title={step.status === 'locked' ? step.lockedReason : undefined}
                className={[
                  'group w-full text-left rounded-xl border px-3 py-2.5 transition-all duration-200',
                  isCurrent
                    ? 'border-indigo-300 bg-indigo-50/70 shadow-sm ring-1 ring-indigo-200'
                    : step.status === 'done'
                      ? 'border-emerald-200 bg-emerald-50/40 hover:border-emerald-300 hover:bg-emerald-50'
                      : step.status === 'available'
                        ? 'border-gray-200 bg-white hover:border-indigo-200 hover:bg-indigo-50/30'
                        : 'border-gray-150 bg-gray-50/60 cursor-not-allowed opacity-60',
                ].join(' ')}
              >
                <div className="flex items-center gap-2.5">
                  {/* Status marker */}
                  <span
                    className={[
                      'flex-shrink-0 w-6 h-6 rounded-lg grid place-items-center text-[11px] font-bold',
                      step.status === 'done'
                        ? 'bg-emerald-500 text-white'
                        : isCurrent
                          ? 'bg-indigo-600 text-white'
                          : step.status === 'locked'
                            ? 'bg-gray-200 text-gray-400'
                            : 'bg-gray-100 text-gray-500 group-hover:bg-indigo-100 group-hover:text-indigo-600',
                    ].join(' ')}
                  >
                    {step.status === 'done' ? (
                      <Check className="w-3.5 h-3.5" strokeWidth={3} />
                    ) : step.status === 'locked' ? (
                      <Lock className="w-3 h-3" />
                    ) : (
                      i + 1
                    )}
                  </span>

                  <span className="min-w-0 flex-1">
                    <span
                      className={[
                        'block text-[13px] font-semibold truncate',
                        isCurrent
                          ? 'text-indigo-900'
                          : step.status === 'locked'
                            ? 'text-gray-400'
                            : 'text-gray-700',
                      ].join(' ')}
                    >
                      {step.title}
                    </span>
                    {step.statusLabel && (
                      <span
                        className={[
                          'block text-[10.5px] truncate',
                          step.status === 'done'
                            ? 'text-emerald-600'
                            : isCurrent
                              ? 'text-indigo-500'
                              : 'text-gray-400',
                        ].join(' ')}
                      >
                        {step.statusLabel}
                      </span>
                    )}
                  </span>
                </div>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
