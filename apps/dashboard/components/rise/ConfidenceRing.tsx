import React from 'react';
import { cn } from '../../lib/cn';
import { resolveConfidence, type ConfidenceBand } from './tokens';

/**
 * Circular confidence indicator.
 *
 * Honesty rule (see CLAUDE.md): a null/undefined/NaN score renders an empty
 * track with an em dash and an accessible "Not computed" label — it NEVER
 * fabricates a ring. A real 0 correctly draws 0% (band 'low'), the exact case
 * the old `score || 0.85` bug corrupted into a confident 85%.
 */
const BAND_TEXT: Record<ConfidenceBand, string> = {
  high: 'text-status-approved',
  medium: 'text-amber-accent',
  low: 'text-sev2',
  none: 'text-warm-grey-600',
};

export interface ConfidenceRingProps {
  /** 0..1 by default; pass scale=100 if the source is already a percentage. */
  value: number | null | undefined;
  scale?: 1 | 100;
  /** Diameter in px. */
  size?: number;
  strokeWidth?: number;
  /** Show the numeric value in the centre. */
  showValue?: boolean;
  className?: string;
}

export function ConfidenceRing({
  value,
  scale = 1,
  size = 72,
  strokeWidth = 6,
  showValue = true,
  className,
}: ConfidenceRingProps) {
  const resolved = resolveConfidence(value, scale);
  const r = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * r;
  const offset =
    resolved.fraction === null ? circumference : circumference * (1 - resolved.fraction);

  return (
    <div
      className={cn('relative inline-flex items-center justify-center', BAND_TEXT[resolved.band], className)}
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} role="img" aria-label={`Confidence: ${resolved.label}`}>
        <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            strokeWidth={strokeWidth}
            className="stroke-warm-grey-700/40"
          />
          {resolved.state === 'computed' && (
            <circle
              cx={size / 2}
              cy={size / 2}
              r={r}
              fill="none"
              strokeWidth={strokeWidth}
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={offset}
              className="stroke-current transition-[stroke-dashoffset] duration-slow ease-out-expo"
            />
          )}
        </g>
      </svg>
      {showValue && (
        <span
          className="absolute font-display font-semibold leading-none tabular-nums"
          style={{ fontSize: size * 0.24 }}
        >
          {resolved.display}
        </span>
      )}
    </div>
  );
}
