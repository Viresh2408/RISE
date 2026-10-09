import React from 'react';
import { cn } from '../../lib/cn';
import { tx } from '../../lib/typography';
import type { SeverityLevel } from '../../lib/types';
import { SEVERITY_META } from './tokens';

/**
 * Severity indicator (SEV1 = most severe → SEV4). Severity keeps its own hue
 * scale rather than the shared tone palette, so it has a dedicated primitive
 * instead of routing through <StatusBadge>.
 */
export interface SeverityMarkerProps {
  severity: SeverityLevel;
  /** 'badge' = labelled pill (default); 'dot' = coloured dot + optional label. */
  variant?: 'badge' | 'dot';
  /** For the dot variant, render the SEVn label beside the dot. */
  showLabel?: boolean;
  className?: string;
}

export function SeverityMarker({
  severity,
  variant = 'badge',
  showLabel = true,
  className,
}: SeverityMarkerProps) {
  const meta = SEVERITY_META[severity];

  if (variant === 'dot') {
    return (
      <span className={cn('inline-flex items-center gap-1.5', className)}>
        <span className={cn('h-2 w-2 shrink-0 rounded-full', meta.dotClass)} aria-hidden />
        {showLabel && <span className={tx('cardMeta', 'text-warm-grey-100')}>{meta.label}</span>}
        <span className="sr-only">{meta.label}</span>
      </span>
    );
  }

  return (
    <span
      className={cn(
        'inline-flex items-center rounded-[var(--radius-sm)] border px-2 py-0.5',
        tx('badge'),
        meta.badgeClass,
        className,
      )}
    >
      {meta.label}
    </span>
  );
}
