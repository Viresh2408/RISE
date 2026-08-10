/**
 * RISE Typography Token System
 * Strict typography scale, font choices, weights, line-heights, and tracking rules per context.
 */

export interface TypeStyle {
  family: 'font-display' | 'font-body';
  size: string;
  weight: 'font-normal' | 'font-medium' | 'font-semibold' | 'font-bold';
  leading?: string;
  tracking?: string;
  transform?: string;
  numeric?: string;
  maxWidth?: string;
}

export const typeScale = {
  // ── MARKETING PAGE ──
  heroHeadline: {
    family: 'font-display',
    size: 'text-[2.5rem] md:text-[4rem]',
    weight: 'font-semibold',
    leading: 'leading-[1.05]',
    tracking: 'tracking-[-0.02em]',
  },
  heroSubhead: {
    family: 'font-body',
    size: 'text-[1.125rem] md:text-[1.25rem]',
    weight: 'font-normal',
    leading: 'leading-[1.5]',
    maxWidth: 'max-w-[560px]',
  },
  sectionHeadline: {
    family: 'font-display',
    size: 'text-[1.75rem] md:text-[2.5rem]',
    weight: 'font-semibold',
    leading: 'leading-[1.15]',
    tracking: 'tracking-[-0.01em]',
  },
  sectionSubhead: {
    family: 'font-body',
    size: 'text-[1.125rem]',
    weight: 'font-normal',
    leading: 'leading-[1.6]',
  },
  bodyProse: {
    family: 'font-body',
    size: 'text-[1rem]',
    weight: 'font-normal',
    leading: 'leading-[1.65]',
  },
  metricNumeral: {
    family: 'font-display',
    size: 'text-3xl sm:text-4xl lg:text-5xl',
    weight: 'font-bold',
    leading: 'leading-none',
    numeric: 'tabular-nums',
  },
  metricLabel: {
    family: 'font-body',
    size: 'text-[0.875rem]',
    weight: 'font-medium',
    tracking: 'tracking-[0.05em]',
    transform: 'uppercase',
  },
  techStackName: {
    family: 'font-body',
    size: 'text-[0.9375rem]',
    weight: 'font-medium',
  },
  ctaButton: {
    family: 'font-body',
    size: 'text-[1rem]',
    weight: 'font-semibold',
    tracking: 'tracking-[0.01em]',
  },
  footerLink: {
    family: 'font-body',
    size: 'text-[0.875rem]',
    weight: 'font-normal',
  },

  // ── LOGIN PAGE ──
  loginTitle: {
    family: 'font-display',
    size: 'text-[1.75rem]',
    weight: 'font-semibold',
  },
  formLabel: {
    family: 'font-body',
    size: 'text-[0.8125rem]',
    weight: 'font-medium',
    tracking: 'tracking-[0.04em]',
    transform: 'uppercase',
  },
  inputText: {
    family: 'font-body',
    size: 'text-[1rem]', // 16px min prevents iOS zoom
    weight: 'font-normal',
  },
  errorText: {
    family: 'font-body',
    size: 'text-[0.8125rem]',
    weight: 'font-medium',
  },

  // ── DASHBOARD — INCIDENT FEED ──
  navLogo: {
    family: 'font-display',
    size: 'text-[1.25rem]',
    weight: 'font-semibold',
  },
  filterTab: {
    family: 'font-body',
    size: 'text-[0.875rem]',
    weight: 'font-medium',
  },
  cardTitle: {
    family: 'font-body',
    size: 'text-[1rem]',
    weight: 'font-semibold',
  },
  cardSummary: {
    family: 'font-body',
    size: 'text-[0.875rem]',
    weight: 'font-normal',
    leading: 'leading-[1.5]',
  },
  cardMeta: {
    family: 'font-body',
    size: 'text-[0.8125rem]',
    weight: 'font-normal',
    tracking: 'tracking-[0.01em]',
  },
  badge: {
    family: 'font-body',
    size: 'text-[0.75rem]',
    weight: 'font-semibold',
    tracking: 'tracking-[0.04em]',
    transform: 'uppercase',
  },

  // ── DASHBOARD — INCIDENT DETAIL ──
  incidentTitle: {
    family: 'font-body',
    size: 'text-[1.5rem]',
    weight: 'font-semibold',
  },
  incidentMeta: {
    family: 'font-body',
    size: 'text-[0.8125rem]',
    weight: 'font-normal',
  },
  sectionHeader: {
    family: 'font-body',
    size: 'text-[0.9375rem]',
    weight: 'font-semibold',
    tracking: 'tracking-[0.05em]',
    transform: 'uppercase',
  },
  rcaProse: {
    family: 'font-body',
    size: 'text-[0.9375rem]',
    weight: 'font-normal',
    leading: 'leading-[1.6]',
  },
  confidenceScore: {
    family: 'font-display',
    size: 'text-xl md:text-2xl',
    weight: 'font-bold',
    leading: 'leading-none',
    numeric: 'tabular-nums',
  },
  evidenceTable: {
    family: 'font-body',
    size: 'text-[0.8125rem]',
    weight: 'font-normal',
    numeric: 'tabular-nums',
  },
  actionStep: {
    family: 'font-body',
    size: 'text-[0.875rem]',
    weight: 'font-normal',
    leading: 'leading-[1.6]',
  },
  actionButton: {
    family: 'font-body',
    size: 'text-[0.875rem]',
    weight: 'font-semibold',
    tracking: 'tracking-[0.01em]',
  },
  riskBadge: {
    family: 'font-body',
    size: 'text-[0.75rem]',
    weight: 'font-semibold',
    tracking: 'tracking-[0.04em]',
    transform: 'uppercase',
  },

  // ── REPORTS ──
  reportStat: {
    family: 'font-display',
    size: 'text-2xl sm:text-3xl lg:text-4xl',
    weight: 'font-bold',
    leading: 'leading-none',
    numeric: 'tabular-nums',
  },
} as const;

export type TypeScaleKey = keyof typeof typeScale;

/**
 * Returns a compiled string of utility classes for a given typeScale key
 */
export function tx(key: TypeScaleKey, extraClasses = ''): string {
  const style = typeScale[key] as TypeStyle;
  const classes = [
    style.family,
    style.size,
    style.weight,
    style.leading,
    style.tracking,
    style.transform,
    style.numeric,
    style.maxWidth,
    extraClasses,
  ].filter(Boolean);

  return classes.join(' ');
}
