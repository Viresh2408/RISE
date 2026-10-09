/** @type {import('tailwindcss').Config} */

/**
 * Semantic colors are declared in channel form — `rgb(var(--rise-*) / <alpha-value>)`
 * — so Tailwind opacity modifiers work on them (`bg-sev1/15`, `border-sev1/30`),
 * replacing the arbitrary-hex-with-slash pattern the components used before.
 * `rgb(<ch> / 1)` renders identically to the old literal hex, so this is a
 * superset and non-breaking. The channel values live in `app/globals.css :root`.
 */
module.exports = {
  darkMode: 'class',
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './lib/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // Spec design tokens (channel-var form → supports /<alpha> modifiers)
        'violet-primary': 'rgb(var(--rise-violet-primary) / <alpha-value>)',
        'violet-accent': 'rgb(var(--rise-violet-accent) / <alpha-value>)',
        cream: 'rgb(var(--rise-cream) / <alpha-value>)',
        'near-black': 'rgb(var(--rise-near-black) / <alpha-value>)',
        'warm-grey-100': 'rgb(var(--rise-warm-grey-100) / <alpha-value>)',
        'warm-grey-600': 'rgb(var(--rise-warm-grey-600) / <alpha-value>)',
        'warm-grey-700': 'rgb(var(--rise-warm-grey-700) / <alpha-value>)',
        'amber-accent': 'rgb(var(--rise-amber-accent) / <alpha-value>)',
        // Severities
        sev1: 'rgb(var(--rise-sev1) / <alpha-value>)',
        sev2: 'rgb(var(--rise-sev2) / <alpha-value>)',
        sev3: 'rgb(var(--rise-sev3) / <alpha-value>)',
        sev4: 'rgb(var(--rise-sev4) / <alpha-value>)',
        // Outcomes
        'status-approved': 'rgb(var(--rise-status-approved) / <alpha-value>)',
        'status-pending': 'rgb(var(--rise-status-pending) / <alpha-value>)',
        'status-rejected': 'rgb(var(--rise-status-rejected) / <alpha-value>)',
        // Dimensional substrate ladder (Midnight default; overridden for Day Mode)
        'surface-0': 'var(--surface-0)',
        'surface-1': 'var(--surface-1)',
        'surface-2': 'var(--surface-2)',
        'surface-3': 'var(--surface-3)',
        'surface-4': 'var(--surface-4)',

        // Legacy / Fallback aliases (unchanged literal hex — not migrated in Phase 0)
        surface: '#fff8f4',
        'surface-dim': '#e1d8d2',
        'surface-bright': '#fff8f4',
        'surface-container': '#f6ece5',
        'on-surface': '#1f1b17',
        'on-surface-variant': '#4a4551',
        outline: '#7b7482',
        'outline-variant': '#ccc3d2',
        primary: '#4C2A85',
        'primary-container': '#350d6e',
        secondary: '#8B5CF6',
        'secondary-fixed-dim': '#d0bcff',
        error: '#EF4444',
        background: '#fff8f4',
        'ivory-bg': '#FAF7F2',
        'midnight-bg': '#0E0B14',
        'status-healthy': '#22C55E',
        'status-critical': '#EF4444',
        'warm-grey': '#E8E2D9',
        'warm-grey-light': '#E8E2D9',
        'accent-amber': '#F5A623',
      },
      borderRadius: {
        // Pre-existing keys preserved verbatim (no visual regression); 2xl/3xl added.
        DEFAULT: '0.125rem',
        lg: '0.25rem',
        xl: '0.5rem',
        '2xl': '1.25rem',
        '3xl': '1.5rem',
        full: '9999px',
      },
      boxShadow: {
        'elevation-0': 'var(--elevation-0)',
        'elevation-1': 'var(--elevation-1)',
        'elevation-2': 'var(--elevation-2)',
        'elevation-3': 'var(--elevation-3)',
        'elevation-4': 'var(--elevation-4)',
        'elevation-hover': 'var(--elevation-hover)',
        'glow-violet': 'var(--glow-violet)',
        'glow-amber': 'var(--glow-amber)',
        'inner-highlight': 'var(--inner-highlight)',
      },
      spacing: {
        base: '8px',
        gutter: '24px',
        'margin-mobile': '16px',
        'margin-desktop': '64px',
        'section-gap': '120px',
      },
      fontFamily: {
        display: ['var(--font-display)', 'Fraunces', 'Georgia', 'serif'],
        body: ['var(--font-body)', 'Hanken Grotesk', 'system-ui', 'sans-serif'],
        fraunces: ['var(--font-display)', 'Fraunces', 'serif'],
        hanken: ['var(--font-body)', 'Hanken Grotesk', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        hero: ['4rem', { lineHeight: '1.05', letterSpacing: '-0.02em', fontWeight: '600' }],
        'hero-mobile': ['2.5rem', { lineHeight: '1.05', letterSpacing: '-0.02em', fontWeight: '600' }],
        'section-head': ['2.5rem', { lineHeight: '1.15', letterSpacing: '-0.01em', fontWeight: '600' }],
        'metric-numeral': ['3.5rem', { lineHeight: '1', fontWeight: '700' }],
        'report-stat': ['2.5rem', { lineHeight: '1', fontWeight: '700' }],
        'card-title': ['1rem', { lineHeight: '1.5', fontWeight: '600' }],
        'card-summary': ['0.875rem', { lineHeight: '1.5', fontWeight: '400' }],
        'card-meta': ['0.8125rem', { lineHeight: '1.4', fontWeight: '400' }],
        badge: ['0.75rem', { lineHeight: '1', fontWeight: '600' }],
        confidence: ['1.75rem', { lineHeight: '1', fontWeight: '600' }],
        'section-label': ['0.9375rem', { lineHeight: '1.5', fontWeight: '600' }],
      },
      transitionTimingFunction: {
        standard: 'var(--ease-standard)',
        'out-expo': 'var(--ease-out-expo)',
        spring: 'var(--ease-spring)',
      },
      transitionDuration: {
        fast: '120ms',
        base: '200ms',
        moderate: '320ms',
        slow: '560ms',
      },
    },
  },
  plugins: [],
};
