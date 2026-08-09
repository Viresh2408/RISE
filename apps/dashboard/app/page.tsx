'use client';

import React from 'react';
import Link from 'next/link';
import { Navbar } from '../components/navbar';
import { PipelineCanvas } from '../components/pipeline-canvas';
import { AgentFlowDiagram } from '../components/agent-flow-diagram';
import {
  Shield,
  Sparkles,
  ArrowRight,
  Zap,
  Lock,
  Activity,
  CheckCircle2,
  Cpu,
  Layers,
  Terminal,
  FileText,
  ChevronRight,
  ShieldAlert,
} from 'lucide-react';

export default function MarketingLandingPage() {
  return (
    <div className="min-h-screen bg-[#0E0B14] text-[#FAF7F2] font-hanken selection:bg-purple-500 selection:text-white">
      <Navbar />

      {/* Hero Section */}
      <section className="relative pt-16 pb-20 overflow-hidden antigravity-hero border-b border-white/10">
        <div className="absolute inset-0 bg-grid-pattern opacity-30 pointer-events-none" />
        
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
          <div className="text-center max-w-4xl mx-auto">
            {/* Pill Badge */}
            <div className="inline-flex items-center space-x-2 bg-purple-950/80 border border-purple-500/30 px-3.5 py-1.5 rounded-full text-xs font-mono text-purple-200 mb-8 glow-purple">
              <span className="w-2 h-2 rounded-full bg-amber-400 animate-ping" />
              <span>ANTIGRAVITY EXECUTION ENGINE v2.4</span>
            </div>

            {/* Editorial Display Headline */}
            <h1 className="font-fraunces text-4xl sm:text-6xl md:text-7xl font-bold tracking-tight text-white leading-[1.1] mb-6">
              Engineering <span className="text-transparent bg-clip-text bg-gradient-to-r from-amber-300 via-amber-400 to-purple-400">Antigravity</span> Execution
            </h1>

            {/* Subhead */}
            <p className="text-lg sm:text-xl text-gray-300 max-w-3xl mx-auto font-normal leading-relaxed mb-10">
              Autonomous SRE and multi-agent incident resolution. RISE ingests production alerts, correlates Loki & Qdrant context, evaluates OPA risk policies, and executes verified remediations in seconds.
            </p>

            {/* CTAs */}
            <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
              <Link
                href="/incidents"
                className="w-full sm:w-auto flex items-center justify-center space-x-2 bg-[#F5A623] hover:bg-amber-400 text-black font-bold text-base px-8 py-3.5 rounded-lg transition-all glow-amber transform hover:-translate-y-0.5"
              >
                <Sparkles className="w-5 h-5" />
                <span>Launch Incident Console</span>
              </Link>
              <a
                href="#architecture"
                className="w-full sm:w-auto flex items-center justify-center space-x-2 glass-panel hover:bg-white/10 text-white font-medium text-base px-8 py-3.5 rounded-lg transition-all border border-white/20"
              >
                <span>Explore 3D Pipeline</span>
                <ArrowRight className="w-4 h-4 text-purple-400" />
              </a>
            </div>
          </div>

          {/* 3D Pipeline Visualizer Canvas */}
          <div id="architecture" className="mt-16">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-fraunces text-2xl text-white font-semibold flex items-center gap-2">
                <Cpu className="w-6 h-6 text-amber-400" />
                <span>Interactive 3D Agent Pipeline Canvas</span>
              </h2>
              <span className="font-mono text-xs text-purple-300">Orbit & Drag to Inspect</span>
            </div>
            <PipelineCanvas activeStep={4} interactive={true} />
          </div>

          {/* Interactive Agent Step Inspector */}
          <AgentFlowDiagram />
        </div>
      </section>

      {/* Resilience Ticker Metrics */}
      <section className="py-12 bg-black/60 border-b border-white/10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8 text-center">
            <div className="p-4">
              <p className="font-fraunces text-4xl sm:text-5xl font-bold text-amber-400 mb-1">-88%</p>
              <p className="font-mono text-xs text-gray-400 uppercase tracking-wider">MTTR Reduction</p>
            </div>
            <div className="p-4">
              <p className="font-fraunces text-4xl sm:text-5xl font-bold text-purple-400 mb-1">94.2%</p>
              <p className="font-mono text-xs text-gray-400 uppercase tracking-wider">RCA Precision</p>
            </div>
            <div className="p-4">
              <p className="font-fraunces text-4xl sm:text-5xl font-bold text-emerald-400 mb-1">0.00%</p>
              <p className="font-mono text-xs text-gray-400 uppercase tracking-wider">Unsafe Auto-Approvals</p>
            </div>
            <div className="p-4">
              <p className="font-fraunces text-4xl sm:text-5xl font-bold text-white mb-1">100%</p>
              <p className="font-mono text-xs text-gray-400 uppercase tracking-wider">Audit Hash Tamper-Evident</p>
            </div>
          </div>
        </div>
      </section>

      {/* Platform Pillars */}
      <section className="py-24 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center max-w-3xl mx-auto mb-16">
          <h2 className="font-fraunces text-3xl sm:text-5xl font-bold text-white mb-4">
            Built for Zero-Trust Production Autonomy
          </h2>
          <p className="text-gray-400 text-lg">
            Safety engineered at every layer: deterministic policy engines, cryptographic audit chains, and automated rollback control.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          {/* Card 1 */}
          <div className="glass-card p-8 rounded-xl border border-white/10">
            <div className="w-12 h-12 rounded-lg bg-purple-900/60 border border-purple-500/30 flex items-center justify-center text-amber-400 mb-6">
              <Layers className="w-6 h-6" />
            </div>
            <h3 className="font-fraunces text-xl font-bold text-white mb-3">
              01. LangGraph Multi-Agent Architecture
            </h3>
            <p className="text-sm text-gray-300 leading-relaxed mb-4">
              Decoupled specialized agents for Context Aggregation, Root Cause Inference, Impact Analysis, Action Planning, and Health Probe Verification.
            </p>
            <span className="font-mono text-xs text-purple-300">Pydantic v2 Schema Enforced</span>
          </div>

          {/* Card 2 */}
          <div className="glass-card p-8 rounded-xl border border-white/10">
            <div className="w-12 h-12 rounded-lg bg-amber-950/60 border border-amber-500/30 flex items-center justify-center text-amber-400 mb-6">
              <Lock className="w-6 h-6" />
            </div>
            <h3 className="font-fraunces text-xl font-bold text-white mb-3">
              02. Rego OPA Policy Risk Matrix
            </h3>
            <p className="text-sm text-gray-300 leading-relaxed mb-4">
              Hardcoded un-overridable rules route CRITICAL actions and missing rollbacks straight to human Slack/UI approvals before any MCP tool dispatch.
            </p>
            <span className="font-mono text-xs text-amber-300">Open Policy Agent (OPA) Guarded</span>
          </div>

          {/* Card 3 */}
          <div className="glass-card p-8 rounded-xl border border-white/10">
            <div className="w-12 h-12 rounded-lg bg-emerald-950/60 border border-emerald-500/30 flex items-center justify-center text-emerald-400 mb-6">
              <Zap className="w-6 h-6" />
            </div>
            <h3 className="font-fraunces text-xl font-bold text-white mb-3">
              03. Cryptographic Audit Log
            </h3>
            <p className="text-sm text-gray-300 leading-relaxed mb-4">
              Every incident state transition and tool invocation generates a tamper-evident SHA-256 hash chain stored in Postgres with zero UPDATE/DELETE grants.
            </p>
            <span className="font-mono text-xs text-emerald-300">SHA-256 Hash Chain Integrity</span>
          </div>
        </div>
      </section>

      {/* Deployment Tiers */}
      <section className="py-20 bg-black/40 border-t border-white/10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-12">
            <h2 className="font-fraunces text-3xl font-bold text-white mb-3">Deployment Models</h2>
            <p className="text-gray-400 text-sm">Deploy RISE in your Kubernetes cluster, cloud VPC, or air-gapped environment.</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="glass-panel p-6 rounded-xl border border-white/10">
              <span className="font-mono text-xs text-purple-400 uppercase font-semibold">Self-Hosted Community</span>
              <h4 className="font-fraunces text-2xl font-bold text-white mt-2 mb-4">Open Source</h4>
              <ul className="text-xs text-gray-300 space-y-2 mb-6 font-mono">
                <li>• Docker Compose Local Stack</li>
                <li>• Qdrant + Postgres RLS</li>
                <li>• FastAPI + LangGraph Engine</li>
              </ul>
              <Link href="/incidents" className="block text-center bg-white/10 hover:bg-white/20 text-white font-mono text-xs py-2.5 rounded transition-colors">
                Deploy via Helm
              </Link>
            </div>

            <div className="glass-panel p-6 rounded-xl border-2 border-amber-500/60 glow-amber relative">
              <span className="absolute top-3 right-3 font-mono text-[10px] bg-amber-500 text-black px-2 py-0.5 rounded font-bold uppercase">
                Recommended
              </span>
              <span className="font-mono text-xs text-amber-400 uppercase font-semibold">Enterprise VPC</span>
              <h4 className="font-fraunces text-2xl font-bold text-white mt-2 mb-4">Autonomous Cloud</h4>
              <ul className="text-xs text-gray-300 space-y-2 mb-6 font-mono">
                <li>• Kubernetes Operator + EKS</li>
                <li>• Custom OPA Policy Registry</li>
                <li>• Slack ChatOps Integration</li>
                <li>• 24/7 Shadow Mode Testing</li>
              </ul>
              <Link href="/incidents" className="block text-center bg-amber-500 hover:bg-amber-400 text-black font-bold font-mono text-xs py-2.5 rounded transition-colors">
                Launch Enterprise Trial
              </Link>
            </div>

            <div className="glass-panel p-6 rounded-xl border border-white/10">
              <span className="font-mono text-xs text-emerald-400 uppercase font-semibold">Air-Gapped Sovereign</span>
              <h4 className="font-fraunces text-2xl font-bold text-white mt-2 mb-4">Sovereign Defense</h4>
              <ul className="text-xs text-gray-300 space-y-2 mb-6 font-mono">
                <li>• Local Ollama LLM Gateway</li>
                <li>• Strict Zero External API egress</li>
                <li>• Full Security Audit Suite</li>
              </ul>
              <Link href="/incidents" className="block text-center bg-white/10 hover:bg-white/20 text-white font-mono text-xs py-2.5 rounded transition-colors">
                Contact Security Team
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-12 glass-nav border-t border-white/10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-6 text-xs text-gray-400 font-mono">
          <div className="flex items-center space-x-3">
            <Shield className="w-5 h-5 text-amber-400" />
            <span className="font-fraunces text-base font-bold text-white">RISE</span>
            <span>© 2026 Antigravity Autonomous Systems Inc.</span>
          </div>

          <div className="flex items-center space-x-6">
            <Link href="/incidents" className="hover:text-amber-400 transition-colors">Incidents</Link>
            <Link href="/login" className="hover:text-amber-400 transition-colors">Console Auth</Link>
            <a href="https://github.com" target="_blank" rel="noreferrer" className="hover:text-amber-400 transition-colors">GitHub</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
