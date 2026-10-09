/**
 * RISE Design Tokens — canonical TypeScript mirror of the CSS custom properties
 * defined in `app/globals.css`.
 *
 * Source of truth for colors, spacing, elevation, radius, motion and border
 * values used across the RISE dashboard. Where a value must be resolved at
 * runtime by the browser (elevation shadows, which layer several rgba stops),
 * the token points at the CSS variable rather than duplicating the literal, so
 * a single edit in `globals.css` re-themes everything (including the scaffolded
 * "Day Mode" substrate override).
 */

export const colors = {
  // Brand
  violetPrimary: '#4C2A85',
  violetAccent: '#8B5CF6',
  // Substrate / ink
  cream: '#FAF7F2',
  nearBlack: '#0E0B14',
  warmGrey100: '#E8E2D9',
  warmGrey600: '#6B6560',
  warmGrey700: '#5A5550',
  // Human-attention
  amberAccent: '#F5A623',
  // Severity (SEV1 = most severe)
  sev1: '#EF4444',
  sev2: '#F97316',
  sev3: '#F59E0B',
  sev4: '#64748B',
  // Semantic status
  statusApproved: '#22C55E',
  statusPending: '#F59E0B',
  statusRejected: '#EF4444',
} as const;

export const spacing = {
  base: 8,
  cardPaddingDesktop: 24,
  cardPaddingMobile: 16,
  buttonGap: 16,
  sectionPaddingDesktop: 64,
  sectionPaddingMobile: 40,
  badgeClearance: 8,
} as const;

/**
 * Violet-tinted "Midnight" substrate ladder. Higher index sits closer to the
 * viewer and pairs with a higher `elevation` level.
 */
export const surfaces = {
  base: '#0E0B14',
  raised1: '#151121',
  raised2: '#1B1630',
  raised3: '#221B3C',
  raised4: '#2A2249',
} as const;

/**
 * Elevation 0–4. Each references the layered box-shadow CSS token (drop shadow
 * + inner top highlight) so surfaces read as dimensional under top-down light.
 * Consume in Tailwind via `shadow-elevation-{n}`.
 */
export const elevation = {
  0: 'var(--elevation-0)',
  1: 'var(--elevation-1)',
  2: 'var(--elevation-2)',
  3: 'var(--elevation-3)',
  4: 'var(--elevation-4)',
} as const;
export type ElevationLevel = 0 | 1 | 2 | 3 | 4;

/**
 * Canonical radius scale (CSS vars in :root). The pre-existing Tailwind
 * `borderRadius` keys are intentionally left untouched to avoid visual
 * regression on already-shipped pages; new primitives consume this scale via
 * `rounded-[var(--radius-*)]`.
 */
export const radius = {
  sm: '0.375rem',
  md: '0.5rem',
  lg: '0.75rem',
  xl: '1rem',
  '2xl': '1.25rem',
  full: '9999px',
} as const;

export const motion = {
  duration: { fast: '120ms', base: '200ms', moderate: '320ms', slow: '560ms' },
  ease: {
    standard: 'cubic-bezier(0.4, 0, 0.2, 1)',
    outExpo: 'cubic-bezier(0.16, 1, 0.3, 1)',
    spring: 'cubic-bezier(0.34, 1.56, 0.64, 1)',
  },
} as const;

export const borders = {
  subtle: 'rgba(204, 195, 210, 0.08)',
  DEFAULT: 'rgba(204, 195, 210, 0.12)',
  strong: 'rgba(139, 92, 246, 0.5)',
} as const;

/**
 * Confidence bands. RISE never shows more confidence than the evidence
 * supports: a null/undefined score renders as "Not computed", never a
 * fabricated default. See `components/rise/tokens.ts#resolveConfidence`.
 */
export const confidence = {
  highThreshold: 0.8,
  mediumThreshold: 0.5,
} as const;
