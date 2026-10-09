import React from 'react';
import { cn } from '../../lib/cn';
import { tx } from '../../lib/typography';
import { TONE_BADGE_CLASSES, TONE_DOT_CLASSES, type Tone } from './tokens';

/**
 * The single, canonical status pill for the whole dashboard. Every domain
 * badge (incident status, risk tier, agent state) maps its own metadata onto
 * this one implementation via a {@link Tone}, so severity/status/confidence
 * colour language is defined once and never duplicated.
 */
export interface StatusBadgeProps {
  tone: Tone;
  label: string;
  /** Prepend a solid tone-coloured dot. */
  dot?: boolean;
  /** Optional leading icon (already sized/coloured by the caller). */
  icon?: React.ReactNode;
  className?: string;
}

export function StatusBadge({ tone, label, dot = false, icon, className }: StatusBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border px-2 py-0.5 whitespace-nowrap',
        tx('badge'),
        TONE_BADGE_CLASSES[tone],
        className,
      )}
    >
      {dot && <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', TONE_DOT_CLASSES[tone])} aria-hidden />}
      {icon}
      {label}
    </span>
  );
}
