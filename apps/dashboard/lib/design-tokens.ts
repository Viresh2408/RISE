/**
 * RISE Design Tokens System
 * Source of truth for colors, elevation, and design values across marketing and operations dashboard.
 */

export const colors = {
  // Brand colors
  violetPrimary: '#4C2A85', // Deep violet — primary brand color
  violetAccent:  '#8B5CF6', // Brighter violet — interactive/focus accent
  cream:         '#FAF7F2', // Warm ivory — light backgrounds, high-emphasis text on dark
  nearBlack:     '#0E0B14', // Dark backgrounds, violet undertone
  warmGrey100:   '#E8E2D9', // Light neutral
  warmGrey600:   '#6B6560', // Mid neutral, secondary text
  warmGrey700:   '#5A5550', // Darker neutral for high-contrast light theme secondary text
  amberAccent:   '#F5A623', // Live/action moments, primary CTAs

  // Semantic Severities
  sev1: '#EF4444', // Critical red
  sev2: '#F97316', // High orange
  sev3: '#F59E0B', // Medium amber
  sev4: '#64748B', // Low grey-blue

  // Semantic Status Outcomes
  statusApproved: '#22C55E', // Green
  statusPending:  '#F59E0B', // Amber
  statusRejected: '#EF4444', // Red
} as const;

export const spacing = {
  base: '8px',
  cardPaddingDesktop: '24px',
  cardPaddingMobile: '16px',
  buttonGap: '16px',
  sectionPaddingDesktop: '64px',
  sectionPaddingMobile: '40px',
  badgeClearance: '8px',
} as const;
