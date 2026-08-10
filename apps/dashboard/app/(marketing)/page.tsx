'use client';

import React from 'react';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import { motion } from 'framer-motion';
import {
  Activity,
  ArrowRight,
  BarChart3,
  Bot,
  CheckCircle2,
  Cpu,
  Database,
  FileCode2,
  GitBranch,
  Github,
  Layers,
  Lock,
  Radio,
  Search,
  Shield,
  ShieldCheck,
  Sparkles,
  Terminal,
  Zap,
} from 'lucide-react';
import { tx } from '../../lib/typography';
import { marketingMetrics } from '../../lib/benchmarks';

// Dynamic import for Three.js Hero Canvas with SSR disabled
const MarketingThreeHero = dynamic(
  () =>
    import('../../components/marketing-three-hero').then(
      (m) => m.MarketingThreeHero
    ),
  {
    ssr: false,
    loading: () => (
      <div className="w-full h-full flex items-center justify-center bg-[#0E0B14] rounded-xl border border-[#E8E2D9]/10">
        <div className="w-32 h-32 rounded-full bg-[#8B5CF6]/20 animate-pulse blur-xl" />
      </div>
    ),
  }
);

/* ─────────────────────────────────────────────────────────────────
   Marketing Navigation Bar — Sticky near-black glass nav
──────────────────────────────────────────────────────────────────── */
function MarketingNav() {
  return (
    <nav className="fixed top-0 w-full z-50 bg-[#0E0B14]/90 backdrop-blur-md border-b border-[#E8E2D9]/10">
      <div className="flex justify-between items-center max-w-7xl mx-auto px-4 md:px-16 py-4">
        <Link href="/" className={tx('navLogo', 'text-[#FAF7F2] hover:text-[#8B5CF6] transition-colors')}>
          RISE
        </Link>

        <div className="hidden md:flex items-center gap-8 text-sm font-medium text-[#6B6560]">
          <a href="#problem" className="hover:text-[#FAF7F2] transition-colors">
            Problem
          </a>
          <a href="#how-it-works" className="hover:text-[#FAF7F2] transition-colors">
            How it Works
          </a>
          <a href="#architecture" className="hover:text-[#FAF7F2] transition-colors">
            Architecture
          </a>
          <a href="#metrics" className="hover:text-[#FAF7F2] transition-colors">
            Metrics
          </a>
          <a href="#stack" className="hover:text-[#FAF7F2] transition-colors">
            Tech Stack
          </a>
        </div>

        <div className="flex items-center gap-4">
          <Link
            href="/login"
            className={tx('filterTab', 'text-[#E8E2D9] hover:text-[#8B5CF6] transition-colors hidden sm:block')}
          >
            Sign In
          </Link>
          <Link
            href="/incidents"
            className="inline-flex items-center gap-2 rounded-lg bg-[#F5A623] px-5 py-2.5 text-sm font-semibold text-[#0E0B14] hover:bg-[#F5A623]/90 transition-all duration-200 shadow-lg shadow-[#F5A623]/10"
          >
            <span>Console</span>
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
    </nav>
  );
}

/* ─────────────────────────────────────────────────────────────────
   Main Marketing Landing Page Component
──────────────────────────────────────────────────────────────────── */
export default function MarketingLandingPage() {
  return (
    <div className="min-h-screen bg-[#0E0B14] text-[#FAF7F2] overflow-x-hidden">
      <MarketingNav />

      <main className="pt-20">
        {/* ══════════════════════════════════════════════════════
            SECTION A — HERO (Dark: near-black, cream, violet, amber CTA)
        ══════════════════════════════════════════════════════ */}
        <section className="relative min-h-[90vh] flex items-center max-w-7xl mx-auto px-4 md:px-16 py-16 md:py-24">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 items-center w-full">
            {/* Left text column */}
            <div className="col-span-1 lg:col-span-7 space-y-8">
              <div className="inline-flex items-center gap-2.5 px-3.5 py-1.5 rounded-full bg-[#4C2A85]/30 border border-[#8B5CF6]/30 text-[#8B5CF6]">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#22C55E] opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-[#22C55E]"></span>
                </span>
                <span className={tx('cardMeta', 'text-[#FAF7F2] font-semibold uppercase tracking-wider')}>
                  Autonomous Incident Remediation System
                </span>
              </div>

              <h1 className={tx('heroHeadline', 'text-[#FAF7F2]')}>
                It was fixed while <br className="hidden sm:block" />
                you were asleep.
              </h1>

              <p className={tx('heroSubhead', 'text-[#E8E2D9]/85')}>
                RISE is an AI-powered multi-agent first responder that continuously monitors, diagnoses root cause with evidence, and safely resolves production incidents.
              </p>

              <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-4 pt-2">
                <Link
                  href="/incidents"
                  className={tx(
                    'ctaButton',
                    'inline-flex items-center justify-center gap-2.5 rounded-lg bg-[#F5A623] px-7 py-3.5 text-[#0E0B14] hover:bg-[#F5A623]/90 transition-all duration-200 shadow-xl shadow-[#F5A623]/15'
                  )}
                >
                  <span>Launch Operations Console</span>
                  <ArrowRight className="h-4 w-4" />
                </Link>

                <a
                  href="#how-it-works"
                  className={tx(
                    'ctaButton',
                    'inline-flex items-center justify-center rounded-lg border border-[#E8E2D9]/20 bg-[#151121]/60 px-7 py-3.5 text-[#FAF7F2] hover:bg-[#E8E2D9]/10 transition-all duration-200'
                  )}
                >
                  Explore How it Works
                </a>
              </div>
            </div>

            {/* Right 3D Visual panel */}
            <div className="col-span-1 lg:col-span-5 h-[420px] md:h-[500px] w-full">
              <MarketingThreeHero />
            </div>
          </div>
        </section>

        {/* ══════════════════════════════════════════════════════
            SECTION B — PROBLEM STATEMENT (Dark: near-black)
        ══════════════════════════════════════════════════════ */}
        <section id="problem" className="py-20 md:py-28 bg-[#151121]/80 border-y border-[#E8E2D9]/10 px-4 md:px-16">
          <div className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-12 gap-12 items-center">
            {/* Text left-aligned */}
            <div className="lg:col-span-6 space-y-6">
              <span className={tx('badge', 'text-[#8B5CF6]')}>
                The On-Call Problem
              </span>
              <h2 className={tx('sectionHeadline', 'text-[#FAF7F2]')}>
                Engineering is stressed. Alerts fragment focus.
              </h2>
              <p className={tx('bodyProse', 'text-[#E8E2D9]/80')}>
                Traditional incident response is manual, fragmented, and slow. Issues trigger pages in the middle of the night, forcing engineers to manually grep logs, pull metric graphs, correlate GitHub commits, and guess root causes under immense pressure.
              </p>
              <div className="space-y-3 pt-2">
                {[
                  '45+ minute average MTTR for manual investigation',
                  'Context scattered across CloudWatch, GitHub, K8s, and Slack',
                  'Alert fatigue destroying engineering velocity and sleep',
                ].map((item, idx) => (
                  <div key={idx} className="flex items-center gap-3 text-sm text-[#E8E2D9]">
                    <CheckCircle2 className="h-4 w-4 text-[#EF4444] flex-shrink-0" />
                    <span>{item}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Mockup right */}
            <div className="lg:col-span-6 rounded-xl border border-[#E8E2D9]/15 bg-[#0E0B14] p-6 shadow-2xl space-y-4">
              <div className="flex items-center justify-between border-b border-[#E8E2D9]/10 pb-3">
                <div className="flex items-center gap-2">
                  <Terminal className="h-4 w-4 text-[#8B5CF6]" />
                  <span className={tx('cardMeta', 'text-[#FAF7F2] font-mono')}>incident_event_stream.log</span>
                </div>
                <span className="text-[11px] font-mono text-[#EF4444] bg-[#EF4444]/15 px-2 py-0.5 rounded">SEV1 ALERT</span>
              </div>
              <div className="space-y-2 font-mono text-xs text-[#E8E2D9]/70">
                <p className="text-[#EF4444]">[02:14:03] CRITICAL: DB_CONNECTION_POOL_EXHAUSTED (auth-service)</p>
                <p className="text-[#6B6560]">[02:14:04] Dispatching PagerDuty alert to on-call engineer...</p>
                <p className="text-[#F5A623]">[02:14:12] RISE Agent Intercepted: Initiating context ingestion</p>
                <p className="text-[#8B5CF6]">[02:14:30] Root Cause Identified: High idle connection leak in commit #a8f3b</p>
                <p className="text-[#22C55E]">[02:15:02] Autonomous Scaling & Pool Reset Applied. Verification PASSED.</p>
              </div>
            </div>
          </div>
        </section>

        {/* ══════════════════════════════════════════════════════
            SECTION C — HOW IT WORKS (Light: cream background)
        ══════════════════════════════════════════════════════ */}
        <section id="how-it-works" className="py-20 md:py-28 bg-[#FAF7F2] text-[#0E0B14] px-4 md:px-16">
          <div className="max-w-7xl mx-auto space-y-16">
            <div className="space-y-4 max-w-2xl">
              <span className={tx('badge', 'text-[#4C2A85]')}>
                Autonomous Lifecycle
              </span>
              <h2 className={tx('sectionHeadline', 'text-[#0E0B14]')}>
                How RISE Resolves Incidents
              </h2>
              <p className={tx('sectionSubhead', 'text-[#5A5550]')}>
                A 6-stage automated pipeline executed seamlessly on every alert.
              </p>
            </div>

            {/* 6-stage flow grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
              {[
                { stage: '01', title: 'Detect', icon: Radio, desc: 'Real-time alert ingestion & de-duplication from Prometheus, CloudWatch, and Alertmanager.' },
                { stage: '02', title: 'Investigate', icon: Search, desc: 'Multi-source context gathering: logs, metrics, recent deployments, and GitHub PR diffs.' },
                { stage: '03', title: 'Diagnose', icon: Cpu, desc: 'AI root-cause reasoning with evidence scoring and similarity matching against past incidents.' },
                { stage: '04', title: 'Decide', icon: Layers, desc: 'OPA risk policy evaluation: auto-remediate low-risk actions or request human approval.' },
                { stage: '05', title: 'Remediate', icon: Zap, desc: 'Safe execution via Kubernetes API, CloudWatch, Ansible, or auto-generated Pull Requests.' },
                { stage: '06', title: 'Verify', icon: ShieldCheck, desc: 'Post-fix health check probes and error-rate monitoring with automatic rollback if verification fails.' },
              ].map(({ stage, title, icon: Icon, desc }) => (
                <motion.div
                  key={stage}
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.4 }}
                  className="rounded-xl border border-[#E8E2D9] bg-white p-6 shadow-sm hover:shadow-md transition-all duration-200 space-y-4"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#4C2A85]/10 text-[#4C2A85]">
                      <Icon className="h-5 w-5" />
                    </div>
                    <span className="font-mono text-xs font-bold text-[#6B6560]">{stage}</span>
                  </div>
                  <h3 className={tx('cardTitle', 'text-[#0E0B14]')}>{title}</h3>
                  <p className={tx('cardSummary', 'text-[#5A5550]')}>{desc}</p>
                </motion.div>
              ))}
            </div>
          </div>
        </section>

        {/* ══════════════════════════════════════════════════════
            SECTION D — ARCHITECTURE HIGHLIGHT (Dark: near-black)
        ══════════════════════════════════════════════════════ */}
        <section id="architecture" className="py-20 md:py-28 bg-[#0E0B14] px-4 md:px-16 border-t border-[#E8E2D9]/10">
          <div className="max-w-7xl mx-auto space-y-12">
            <div className="space-y-4 max-w-2xl">
              <span className={tx('badge', 'text-[#8B5CF6]')}>
                Multi-Agent System
              </span>
              <h2 className={tx('sectionHeadline', 'text-[#FAF7F2]')}>
                Engineered for Safety & Precision
              </h2>
              <p className={tx('sectionSubhead', 'text-[#6B6560]')}>
                Decoupled specialized agents coordinate through LangGraph orchestration.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
              {[
                { title: 'Ingestion Agent', role: 'Normalizes multi-source alert payloads', icon: Radio },
                { title: 'Context Builder', role: 'Fetches code diffs, logs & telemetry', icon: Database },
                { title: 'Root Cause Agent', role: 'Generates RCA with evidence links', icon: Cpu },
                { title: 'Execution Agent', role: 'Dispatches safe tool calls & fixes', icon: GitBranch },
              ].map(({ title, role, icon: Icon }, idx) => (
                <div key={idx} className="rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-6 space-y-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#4C2A85]/30 text-[#8B5CF6]">
                    <Icon className="h-5 w-5" />
                  </div>
                  <h3 className={tx('cardTitle', 'text-[#FAF7F2]')}>{title}</h3>
                  <p className={tx('cardSummary', 'text-[#6B6560]')}>{role}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ══════════════════════════════════════════════════════
            SECTION E — METRICS (Light: cream background)
        ══════════════════════════════════════════════════════ */}
        <section id="metrics" className="py-20 md:py-28 bg-[#FAF7F2] text-[#0E0B14] px-4 md:px-16 border-t border-[#E8E2D9]">
          <div className="max-w-7xl mx-auto space-y-12">
            <div className="space-y-4 max-w-xl">
              <span className={tx('badge', 'text-[#4C2A85] bg-[#4C2A85]/10 px-3 py-1 rounded-full border border-[#4C2A85]/20')}>
                Measured Performance
              </span>
              <h2 className={tx('sectionHeadline', 'text-[#0E0B14]')}>
                Proven Impact
              </h2>
              <p className={tx('sectionSubhead', 'text-[#5A5550]')}>
                Empirically benchmarked performance across production incident response environments.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
              {marketingMetrics.map((item, idx) => (
                <motion.div
                  key={idx}
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.4, delay: idx * 0.1 }}
                  className="rounded-xl border border-[#E8E2D9] bg-white p-6 sm:p-8 space-y-3 text-center shadow-sm hover:shadow-lg hover:border-[#8B5CF6]/40 transition-all duration-300 overflow-hidden group"
                >
                  <p className="font-display text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight text-[#8B5CF6] tabular-nums group-hover:scale-105 transition-transform duration-300">
                    {item.value}
                  </p>
                  <p className={tx('metricLabel', 'text-[#0E0B14] font-semibold tracking-wider')}>
                    {item.label}
                  </p>
                  <p className={tx('cardMeta', 'text-[#5A5550] italic')}>
                    {item.note}
                  </p>
                </motion.div>
              ))}
            </div>
          </div>
        </section>

        {/* ══════════════════════════════════════════════════════
            SECTION F — TECH STACK (Dark: near-black)
        ══════════════════════════════════════════════════════ */}
        <section id="stack" className="py-20 md:py-28 bg-[#0E0B14] border-t border-[#E8E2D9]/10 px-4 md:px-16">
          <div className="max-w-7xl mx-auto space-y-12">
            <div className="space-y-4 max-w-xl">
              <span className={tx('badge', 'text-[#8B5CF6]')}>
                Technology Stack
              </span>
              <h2 className={tx('sectionHeadline', 'text-[#FAF7F2]')}>
                Built on Modern Infrastructure
              </h2>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-4">
              {[
                'Next.js 14',
                'FastAPI',
                'LangGraph',
                'Qdrant Vector DB',
                'Supabase Postgres',
                'Kubernetes',
              ].map((tech, idx) => (
                <div key={idx} className="rounded-lg border border-[#E8E2D9]/15 bg-[#151121] p-4 text-center">
                  <span className={tx('techStackName', 'text-[#E8E2D9]')}>{tech}</span>
                </div>
              ))}
            </div>
          </div>
        </section>
      </main>

      {/* ══════════════════════════════════════════════════════
          SECTION G — FOOTER (Near-black)
      ══════════════════════════════════════════════════════ */}
      <footer className="bg-[#0E0B14] border-t border-[#E8E2D9]/10 py-12 px-4 md:px-16">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row justify-between items-center gap-6">
          <div className="flex items-center gap-4">
            <span className={tx('navLogo', 'text-[#FAF7F2]')}>RISE</span>
            <span className={tx('footerLink', 'text-[#6B6560]')}>© 2026 RISE Systems. All rights reserved.</span>
          </div>

          <div className="flex items-center gap-6 text-sm text-[#6B6560]">
            <Link href="/incidents" className="hover:text-[#FAF7F2] transition-colors">
              Console
            </Link>
            <Link href="/login" className="hover:text-[#FAF7F2] transition-colors">
              Sign In
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
