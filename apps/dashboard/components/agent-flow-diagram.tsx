'use client';

import React, { useState } from 'react';
import {
  ShieldAlert,
  Database,
  Search,
  Activity,
  ShieldCheck,
  Play,
  CheckCircle2,
  AlertTriangle,
  Lock,
  ArrowRight,
} from 'lucide-react';

interface AgentStep {
  id: string;
  name: string;
  role: string;
  status: 'completed' | 'in_progress' | 'pending' | 'requires_approval';
  model: string;
  latencyMs: number;
  details: string;
  icon: React.ElementType;
}

const pipelineSteps: AgentStep[] = [
  {
    id: 'ingest',
    name: 'Ingestion Agent',
    role: 'HMAC signature verification, alert deduplication, payload normalization',
    status: 'completed',
    model: 'Gemini 1.5 Flash',
    latencyMs: 142,
    details: 'Received Alertmanager webhook payload. HMAC verified. Normalized schema to IncidentEvent.',
    icon: Database,
  },
  {
    id: 'context',
    name: 'Context Builder',
    role: 'Qdrant vector search + Loki logs + Prometheus metrics query',
    status: 'completed',
    model: 'Gemini 1.5 Pro',
    latencyMs: 820,
    details: 'Vector match score 0.91 with historical Incident #3821. Fetched 50 lines of Loki logs.',
    icon: Search,
  },
  {
    id: 'rca',
    name: 'Root Cause Agent',
    role: 'Hypothesis generation & evidence reference calibration',
    status: 'completed',
    model: 'Gemini 1.5 Pro',
    latencyMs: 1240,
    details: 'Identified DB connection pool saturation in auth-service (Confidence: 0.88).',
    icon: Activity,
  },
  {
    id: 'impact',
    name: 'Impact Analyzer',
    role: 'Deterministic topology adjacency & blast radius calculation',
    status: 'completed',
    model: 'Deterministic Engine',
    latencyMs: 45,
    details: 'Blast radius calculated across auth-service -> api-gateway -> checkout-service.',
    icon: ShieldAlert,
  },
  {
    id: 'decision',
    name: 'OPA Risk & Decision Engine',
    role: 'Open Policy Agent evaluation & human approval routing',
    status: 'requires_approval',
    model: 'Rego Policy Engine',
    latencyMs: 62,
    details: 'Evaluated policy risk_tiers.rego: Risk Tier HIGH due to auth-service scope. Human approval required.',
    icon: Lock,
  },
  {
    id: 'execution',
    name: 'Execution Gateway',
    role: 'MCP Kubernetes/AWS/GitHub tool dispatch with hash validation',
    status: 'pending',
    model: 'MCP Protocol Handler',
    latencyMs: 0,
    details: 'Awaiting human authorization hash confirmation before invoking kubectl rollout restart.',
    icon: Play,
  },
  {
    id: 'verification',
    name: 'Verification Agent',
    role: 'Health probe monitoring & automated rollback trigger',
    status: 'pending',
    model: 'Gemini 1.5 Flash',
    latencyMs: 0,
    details: 'Configured 30s post-remediation health check window.',
    icon: ShieldCheck,
  },
];

export function AgentFlowDiagram() {
  const [selectedStep, setSelectedStep] = useState<AgentStep>(pipelineSteps[4]);

  return (
    <div className="w-full glass-panel rounded-xl p-6 border border-white/10 my-6">
      <div className="flex items-center justify-between mb-6 pb-4 border-b border-white/10">
        <div>
          <h3 className="font-fraunces text-xl text-white font-semibold flex items-center gap-2">
            <span>RISE Multi-Agent Execution Flow</span>
            <span className="text-xs font-mono bg-purple-900/60 text-purple-300 px-2 py-0.5 rounded border border-purple-500/30">
              LangGraph State Machine
            </span>
          </h3>
          <p className="text-sm text-gray-400 mt-1">
            Real-time status of the autonomous incident remediation graph
          </p>
        </div>
        <div className="flex items-center space-x-3 text-xs font-mono">
          <span className="flex items-center gap-1.5 text-emerald-400">
            <CheckCircle2 className="w-4 h-4" /> Completed
          </span>
          <span className="flex items-center gap-1.5 text-amber-400">
            <AlertTriangle className="w-4 h-4" /> Requires Approval
          </span>
          <span className="flex items-center gap-1.5 text-gray-500">
            <span className="w-2.5 h-2.5 rounded-full bg-gray-600 inline-block" /> Pending
          </span>
        </div>
      </div>

      {/* Horizontal Pipeline Steps */}
      <div className="grid grid-cols-1 md:grid-cols-7 gap-3 mb-6">
        {pipelineSteps.map((step, idx) => {
          const Icon = step.icon;
          const isSelected = selectedStep.id === step.id;

          let badgeColor = 'bg-gray-800 text-gray-400 border-gray-700';
          if (step.status === 'completed') badgeColor = 'bg-emerald-950/80 text-emerald-300 border-emerald-500/40';
          if (step.status === 'requires_approval') badgeColor = 'bg-amber-950/80 text-amber-300 border-amber-500/50 animate-pulse';
          if (step.status === 'in_progress') badgeColor = 'bg-purple-950/80 text-purple-300 border-purple-500/40';

          return (
            <button
              key={step.id}
              onClick={() => setSelectedStep(step)}
              className={`p-3 rounded-lg border text-left transition-all ${badgeColor} ${
                isSelected ? 'ring-2 ring-purple-400 scale-[1.02]' : 'opacity-85 hover:opacity-100'
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-mono text-gray-400 uppercase">Step 0{idx + 1}</span>
                <Icon className="w-4 h-4" />
              </div>
              <p className="font-semibold text-xs truncate text-white">{step.name}</p>
              <p className="text-[10px] font-mono text-gray-400 mt-1 truncate">{step.model}</p>
            </button>
          );
        })}
      </div>

      {/* Step Inspector Panel */}
      <div className="bg-black/50 rounded-lg p-4 border border-white/10">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center space-x-2">
            <span className="text-amber-400 font-mono text-xs uppercase font-bold tracking-wider">
              Agent Inspector
            </span>
            <ArrowRight className="w-3.5 h-3.5 text-gray-500" />
            <span className="text-white font-medium text-sm">{selectedStep.name}</span>
          </div>
          <span className="font-mono text-xs text-purple-300 bg-purple-950/60 px-2.5 py-1 rounded border border-purple-500/30">
            {selectedStep.latencyMs > 0 ? `${selectedStep.latencyMs}ms Latency` : 'Standby'}
          </span>
        </div>
        <p className="text-xs text-gray-300 mb-2">{selectedStep.role}</p>
        <div className="font-mono text-xs bg-black/80 p-3 rounded text-purple-200 border border-white/5">
          <span className="text-emerald-400 font-bold">&gt; </span>
          {selectedStep.details}
        </div>
      </div>
    </div>
  );
}
