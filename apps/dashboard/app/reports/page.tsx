'use client';

import React, { useCallback, useEffect, useState } from 'react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts';
import { Navbar } from '../../components/navbar';
import { CardSkeleton } from '../../components/shared/CardSkeleton';
import { EmptyState } from '../../components/shared/EmptyState';
import { apiClient } from '../../lib/api-client';
import { useAuth } from '../../lib/auth-context';
import { MttrReportDTO, AutonomyReportDTO } from '../../lib/types';
import { tx } from '../../lib/typography';
import {
  BarChart2,
  TrendingDown,
  Zap,
  ShieldCheck,
  RefreshCw,
  Clock,
  Activity,
  CheckCircle2,
  XCircle,
  BarChart3,
  Calendar,
} from 'lucide-react';

/* ── Custom Donut Chart (SVG) using Semantic Outcome Colors ── */
function DonutChart({ segments }: { segments: { label: string; value: number; color: string }[] }) {
  const total = segments.reduce((s, seg) => s + seg.value, 0) || 1;
  let cumAngle = -90;

  const paths = segments.map((seg) => {
    const angle = (seg.value / total) * 360;
    const startAngle = cumAngle;
    const endAngle = cumAngle + angle;
    cumAngle += angle;

    const toRad = (a: number) => (a * Math.PI) / 180;
    const x1 = 50 + 35 * Math.cos(toRad(startAngle));
    const y1 = 50 + 35 * Math.sin(toRad(startAngle));
    const x2 = 50 + 35 * Math.cos(toRad(endAngle));
    const y2 = 50 + 35 * Math.sin(toRad(endAngle));
    const largeArc = angle > 180 ? 1 : 0;

    return {
      d: `M 50 50 L ${x1} ${y1} A 35 35 0 ${largeArc} 1 ${x2} ${y2} Z`,
      color: seg.color,
      label: seg.label,
      value: seg.value,
    };
  });

  return (
    <div className="flex flex-col sm:flex-row items-center gap-6">
      <svg viewBox="0 0 100 100" className="w-36 h-36 flex-shrink-0">
        {paths.map((p, i) => (
          <path key={i} d={p.d} fill={p.color} opacity={0.9} />
        ))}
        <circle cx="50" cy="50" r="22" fill="#0E0B14" />
        <text x="50" y="47" textAnchor="middle" fill="#FAF7F2" fontSize="9" fontWeight="bold" fontFamily="sans-serif">
          {total}
        </text>
        <text x="50" y="58" textAnchor="middle" fill="#6B6560" fontSize="5" fontFamily="sans-serif">
          total
        </text>
      </svg>
      <div className="space-y-2.5 w-full">
        {segments.map((seg, i) => (
          <div key={i} className="flex items-center justify-between text-xs font-mono">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ backgroundColor: seg.color }} />
              <span className="text-[#E8E2D9]">{seg.label}</span>
            </div>
            <span className="text-[#FAF7F2] font-bold tabular-nums">{seg.value}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ReportsPage() {
  const { session } = useAuth();
  const [mttr, setMttr] = useState<MttrReportDTO | null>(null);
  const [autonomy, setAutonomy] = useState<AutonomyReportDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Date-range filters. Default to the last 30 days, computed on the client
  // (in a mount effect) rather than a hardcoded window — a fixed range would
  // present a stale historical slice as the current default and only drift
  // further out of date over time.
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');

  useEffect(() => {
    const end = new Date();
    const start = new Date(end.getTime() - 30 * 24 * 60 * 60 * 1000);
    setToDate(end.toISOString().split('T')[0]);
    setFromDate(start.toISOString().split('T')[0]);
  }, []);

  const fetchReports = useCallback(async () => {
    const token = session?.token || '';
    setLoading(true);
    try {
      const [mttrData, autonomyData] = await Promise.all([
        apiClient.getMttrReport(token, { from: fromDate, to: toDate }),
        apiClient.getAutonomyReport(token, { from: fromDate, to: toDate }),
      ]);
      setMttr(mttrData);
      setAutonomy(autonomyData);
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Failed to load reports');
    } finally {
      setLoading(false);
    }
  }, [session, fromDate, toDate]);

  useEffect(() => {
    if (!fromDate || !toDate) return;
    fetchReports();
  }, [fetchReports, fromDate, toDate]);

  /* Resolve report metrics from the API WITHOUT fabricating fallbacks. A
     missing metric is rendered as an explicit "—"/empty state downstream —
     never a plausible-looking invented number (see CLAUDE.md honesty rule). */
  const num = (v: number | null | undefined): number | null =>
    typeof v === 'number' && !Number.isNaN(v) ? v : null;

  const mttrAvg = num(mttr?.overall_avg_minutes ?? mttr?.avg_mttr_minutes);
  const mttrReduction = num(mttr?.reduction_pct);
  const autoResolvedPct = num(autonomy?.auto_resolved_pct);
  const humanApprovedPct = num(autonomy?.human_approved_pct);
  const humanRejectedPct = num(autonomy?.human_rejected_pct ?? autonomy?.rejected_pct);
  const totalIncidents = num(autonomy?.total_incidents);

  const trendData = (mttr?.trend && mttr.trend.length > 0)
    ? mttr.trend.map((t) => ({ date: t.date, mttr: t.mttr_minutes ?? t.mttr ?? 0 }))
    : [];

  const hasAutonomyBreakdown =
    autoResolvedPct !== null && humanApprovedPct !== null && humanRejectedPct !== null;

  return (
    <div className="min-h-screen bg-[#0E0B14] text-[#FAF7F2]">
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Header Bar */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className={tx('incidentTitle', 'text-[#FAF7F2] flex items-center gap-3')}>
              <BarChart2 className="w-7 h-7 text-[#8B5CF6]" />
              <span>Reliability Telemetry & Reports</span>
            </h1>
            <p className={tx('cardMeta', 'text-[#6B6560] mt-1 font-mono')}>
              MTTR trends, resolution autonomy breakdown, and per-service statistics
            </p>
          </div>

          <button
            onClick={fetchReports}
            className="inline-flex items-center gap-2 rounded-lg border border-[#E8E2D9]/15 bg-[#151121] px-4 py-2 text-xs font-semibold text-[#E8E2D9] hover:bg-[#E8E2D9]/10 transition-colors self-start sm:self-center"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>Refresh Reports</span>
          </button>
        </div>

        {/* Date Range Filter Bar */}
        <div className="rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-4 flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="flex items-center gap-2 text-xs font-semibold text-[#E8E2D9]">
            <Calendar className="w-4 h-4 text-[#8B5CF6]" />
            <span>Date Range:</span>
          </div>

          <div className="flex items-center gap-3">
            <input
              type="date"
              value={fromDate}
              onChange={(e) => setFromDate(e.target.value)}
              className="rounded-lg border border-[#E8E2D9]/15 bg-[#0E0B14] px-3 py-1.5 text-xs text-[#FAF7F2] focus:border-[#8B5CF6] focus:outline-none"
            />
            <span className="text-xs text-[#6B6560]">to</span>
            <input
              type="date"
              value={toDate}
              onChange={(e) => setToDate(e.target.value)}
              className="rounded-lg border border-[#E8E2D9]/15 bg-[#0E0B14] px-3 py-1.5 text-xs text-[#FAF7F2] focus:border-[#8B5CF6] focus:outline-none"
            />
          </div>
        </div>

        {/* Honest error surface — previously `error` was captured in state but
            never rendered, so a failed fetch silently showed stale/empty UI. */}
        {error && !loading && (
          <div className="rounded-xl border border-[#EF4444]/30 bg-[#EF4444]/10 p-4 flex items-start gap-3">
            <XCircle className="w-5 h-5 text-[#EF4444] flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-[#EF4444]">Failed to load reports</p>
              <p className="text-xs font-mono text-[#E8E2D9]/70 mt-0.5">{error}</p>
            </div>
          </div>
        )}

        {/* ── KPI STAT CARDS (reportStat scale: 2.5rem/700/tabular-nums) ── */}
        {loading ? (
          <CardSkeleton count={4} variant="report" />
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              {
                label: 'Avg MTTR',
                value: mttrAvg !== null ? `${mttrAvg}m` : '—',
                sub: 'Mean time to resolve',
                icon: Clock,
                borderColor: 'border-l-[#F59E0B]',
                textColor: 'text-[#F59E0B]',
              },
              {
                label: 'MTTR Reduction',
                value: mttrReduction !== null ? `-${mttrReduction}%` : '—',
                sub: 'vs manual baseline',
                icon: TrendingDown,
                borderColor: 'border-l-[#22C55E]',
                textColor: 'text-[#22C55E]',
              },
              {
                label: 'Auto-Resolved',
                value: autoResolvedPct !== null ? `${autoResolvedPct}%` : '—',
                sub: 'Zero-human intervention',
                icon: Zap,
                borderColor: 'border-l-[#8B5CF6]',
                textColor: 'text-[#8B5CF6]',
              },
              {
                label: 'Total Incidents',
                value: totalIncidents !== null ? totalIncidents.toString() : '—',
                sub: 'Selected date window',
                icon: Activity,
                borderColor: 'border-l-[#E8E2D9]',
                textColor: 'text-[#FAF7F2]',
              },
            ].map(({ label, value, sub, icon: Icon, borderColor, textColor }, i) => (
              <div
                key={i}
                data-testid="report-stat-card"
                className={`rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-6 border-l-[4px] ${borderColor} space-y-2 overflow-hidden`}
              >
                <div className="flex items-center justify-between">
                  <span className={tx('sectionHeader', 'text-[#6B6560]')}>{label}</span>
                  <Icon className={`h-4 w-4 ${textColor}`} />
                </div>
                <p className={tx('reportStat', `${textColor} truncate`)}>{value}</p>
                <p className={tx('cardMeta', 'text-[#6B6560] truncate')}>{sub}</p>
              </div>
            ))}
          </div>
        )}

        {/* ── CHARTS SECTION ── */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
          {/* Left: MTTR Trend Line Chart */}
          <div className="lg:col-span-8 rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-6 space-y-6">
            <div className="flex items-center justify-between border-b border-[#E8E2D9]/10 pb-4">
              <h2 className={tx('sectionHeader', 'text-[#FAF7F2] flex items-center gap-2')}>
                <Clock className="w-4 h-4 text-[#8B5CF6]" />
                <span>MTTR Reduction Trend (Minutes)</span>
              </h2>
            </div>

            <div className="h-64 w-full pt-2">
              {trendData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={trendData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#E8E2D9" strokeOpacity={0.1} />
                    <XAxis dataKey="date" stroke="#6B6560" fontSize={12} tickLine={false} />
                    <YAxis stroke="#6B6560" fontSize={12} tickLine={false} unit="m" />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#0E0B14', borderColor: 'rgba(232,226,217,0.15)', borderRadius: '8px' }}
                      itemStyle={{ color: '#8B5CF6', fontSize: '12px' }}
                    />
                    <Line
                      type="monotone"
                      dataKey="mttr"
                      stroke="#8B5CF6"
                      strokeWidth={3}
                      dot={{ fill: '#8B5CF6', r: 4 }}
                      activeDot={{ r: 6 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-center">
                  <BarChart3 className="w-8 h-8 text-[#6B6560] mb-3" />
                  <p className="text-sm font-semibold text-[#E8E2D9]">No trend data</p>
                  <p className="text-xs font-mono text-[#6B6560] mt-1">
                    The reporting API returned no MTTR trend for this range.
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Right: Autonomy Donut Breakdown (Semantic Outcome Colors) */}
          <div className="lg:col-span-4 rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-6 space-y-6">
            <div className="flex items-center justify-between border-b border-[#E8E2D9]/10 pb-4">
              <h2 className={tx('sectionHeader', 'text-[#FAF7F2] flex items-center gap-2')}>
                <ShieldCheck className="w-4 h-4 text-[#22C55E]" />
                <span>Autonomy Resolution Breakdown</span>
              </h2>
            </div>

            {hasAutonomyBreakdown ? (
              <DonutChart
                segments={[
                  { label: 'Auto-Resolved', value: autoResolvedPct as number, color: '#22C55E' }, // status-approved green
                  { label: 'Human Approved', value: humanApprovedPct as number, color: '#F59E0B' }, // status-pending amber
                  { label: 'Human Rejected', value: humanRejectedPct as number, color: '#EF4444' }, // status-rejected red
                ]}
              />
            ) : (
              <div className="min-h-[144px] flex flex-col items-center justify-center text-center">
                <ShieldCheck className="w-8 h-8 text-[#6B6560] mb-3" />
                <p className="text-sm font-semibold text-[#E8E2D9]">No autonomy data</p>
                <p className="text-xs font-mono text-[#6B6560] mt-1">
                  The reporting API returned no resolution breakdown for this range.
                </p>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
