/**
 * BENCHMARKS data handler
 * Exposes benchmark metric values for the RISE platform landing page and reports.
 */

export const BENCHMARKS_ABSENT = false;

export interface MarketingMetric {
  value: string;
  label: string;
  note: string;
  color: string;
}

export const marketingMetrics: MarketingMetric[] = [
  {
    value: '-88%',
    label: 'MTTR Reduction',
    note: 'versus manual triage baseline',
    color: 'text-[#8B5CF6]', // violet-accent
  },
  {
    value: '94.2%',
    label: 'RCA Precision',
    note: 'human-validated root cause accuracy',
    color: 'text-[#8B5CF6]', // violet-accent
  },
  {
    value: '71.0%',
    label: 'Autonomy Rate',
    note: 'low-risk auto-remediations',
    color: 'text-[#8B5CF6]', // violet-accent
  },
];
