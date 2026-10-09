'use client';

/**
 * RISE Design System — Phase 0 primitive gallery.
 *
 * A STATIC, data-free showcase of the consolidated foundation: typography,
 * the dimensional elevation ladder, and every RISE semantic primitive. It
 * imports NO api-client and fabricates NO incident data — the confidence /
 * duration / evidence examples below deliberately include the honest
 * "unknown" states (—, Not computed, Unavailable) alongside real sample
 * values so the honesty contract is visible. The approval buttons use no-op
 * handlers: this is a component gallery, not a live control surface.
 *
 * Route is public (see auth-guard PUBLIC_PATHS) precisely because it holds no
 * tenant data.
 */

import React from 'react';
import {
  ElevationSurface,
  StatusBadge,
  SeverityMarker,
  IncidentState,
  RiskTierBadge,
  ConfidenceRing,
  ConfidenceBar,
  AgentNode,
  Spine,
  LifecycleStage,
  ApprovalAction,
  EvidenceLink,
} from '../../components/rise';
import { tx } from '../../lib/typography';
import type { IncidentStatus, RiskTier, SeverityLevel } from '../../lib/types';

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="mb-16">
      <div className="mb-5 border-b border-[var(--rise-border)] pb-3">
        <h2 className={tx('sectionHeadline', 'text-cream')}>{title}</h2>
        {subtitle && <p className={tx('cardSummary', 'mt-1 text-warm-grey-600')}>{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

const INCIDENT_STATUSES: IncidentStatus[] = ['open', 'investigating', 'awaiting_approval', 'resolved', 'closed'];
const RISK_TIERS: RiskTier[] = ['low', 'medium', 'high', 'critical'];
const SEVERITIES: SeverityLevel[] = ['SEV1', 'SEV2', 'SEV3', 'SEV4'];

export default function DesignSystemPage() {
  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <header className="mb-16">
        <p className={tx('badge', 'text-violet-accent')}>Phase 0 · Foundation</p>
        <h1 className={tx('heroHeadline', 'mt-2 text-cream')}>RISE Design System</h1>
        <p className={tx('heroSubhead', 'mt-3 text-warm-grey-100')}>
          The consolidated dimensional foundation and semantic primitives. Static gallery — no live
          incident data, and the honest &ldquo;unknown&rdquo; states are shown deliberately.
        </p>
      </header>

      <Section title="Typography" subtitle="Fraunces (display) · Hanken Grotesk (interface) · JetBrains Mono (technical data)">
        <div className="space-y-4">
          <p className="font-display text-4xl font-semibold text-cream">Fraunces display · incident resolved</p>
          <p className="font-body text-lg text-warm-grey-100">Hanken Grotesk interface — the system must never be more confident than the evidence supports.</p>
          <p className="font-mono text-sm text-warm-grey-100">JetBrains Mono · commit 9c4f2a1 · incident_id=inc_01H9 · +42 −7</p>
        </div>
      </Section>

      <Section title="Elevation ladder" subtitle="2.5D substrate levels 0–4, glass, interactive lift, inner highlight — all token-driven CSS.">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          {([0, 1, 2, 3, 4] as const).map((lvl) => (
            <ElevationSurface key={lvl} level={lvl} highlight className="flex h-24 items-center justify-center">
              <span className={tx('cardMeta', 'text-warm-grey-100')}>elev {lvl}</span>
            </ElevationSurface>
          ))}
        </div>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <ElevationSurface glass className="flex h-24 items-center justify-center">
            <span className={tx('cardMeta', 'text-warm-grey-100')}>glass-panel</span>
          </ElevationSurface>
          <ElevationSurface level={2} interactive highlight className="flex h-24 items-center justify-center">
            <span className={tx('cardMeta', 'text-warm-grey-100')}>interactive (hover / focus)</span>
          </ElevationSurface>
        </div>
      </Section>
      <Section title="Status · severity · risk" subtitle="One canonical StatusBadge; incident status and risk tier are thin mappings onto it. Severity keeps its own hue scale.">
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            {INCIDENT_STATUSES.map((s) => (
              <IncidentState key={s} status={s} />
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {RISK_TIERS.map((t) => (
              <RiskTierBadge key={t} tier={t} dot />
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {SEVERITIES.map((sev) => (
              <SeverityMarker key={sev} severity={sev} />
            ))}
            {SEVERITIES.map((sev) => (
              <SeverityMarker key={`${sev}-dot`} severity={sev} variant="dot" />
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge tone="violet" label="Tone violet" dot />
            <StatusBadge tone="amber" label="Tone amber" dot />
            <StatusBadge tone="green" label="Tone green" dot />
            <StatusBadge tone="red" label="Tone red" dot />
            <StatusBadge tone="slate" label="Tone slate" dot />
            <StatusBadge tone="neutral" label="Tone neutral" dot />
          </div>
        </div>
      </Section>

      <Section title="Confidence" subtitle="Honest by construction: a null score renders empty + “Not computed”; a real 0 renders 0%, never a fabricated default.">
        <div className="flex flex-wrap items-end gap-8">
          <div className="text-center">
            <ConfidenceRing value={0.88} />
            <p className={tx('cardMeta', 'mt-2 text-warm-grey-600')}>0.88 · high</p>
          </div>
          <div className="text-center">
            <ConfidenceRing value={0.5} />
            <p className={tx('cardMeta', 'mt-2 text-warm-grey-600')}>0.5 · medium</p>
          </div>
          <div className="text-center">
            <ConfidenceRing value={0} />
            <p className={tx('cardMeta', 'mt-2 text-warm-grey-600')}>real 0 · low</p>
          </div>
          <div className="text-center">
            <ConfidenceRing value={null} />
            <p className={tx('cardMeta', 'mt-2 text-warm-grey-600')}>null · not computed</p>
          </div>
          <div className="text-center">
            <ConfidenceRing value={72} scale={100} />
            <p className={tx('cardMeta', 'mt-2 text-warm-grey-600')}>72 (scale 100)</p>
          </div>
        </div>
        <div className="mt-6 max-w-md space-y-4">
          <ConfidenceBar value={0.88} label="Root-cause confidence" />
          <ConfidenceBar value={0} label="Decision confidence" />
          <ConfidenceBar value={null} label="Impact confidence" />
        </div>
      </Section>
      <Section title="Agent pipeline" subtitle="AgentNode run states with real vs unknown latency; the Spine derived from an incident status and shown per-stage.">
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="space-y-2">
            <AgentNode label="build_context" state="success" durationMs={842} summary="Correlated 3 alerts, 12 log lines" />
            <AgentNode label="root_cause" state="success" durationMs={2140} />
            <AgentNode label="impact_analysis" state="running" />
            <AgentNode label="decide" state="pending" durationMs={null} summary={null} />
            <AgentNode label="execute" state="failed" durationMs={510} summary="Resource lock contended" />
            <AgentNode label="verify" state="skipped" />
          </div>
          <div className="grid grid-cols-2 gap-6">
            <div>
              <p className={tx('cardMeta', 'mb-3 text-warm-grey-600')}>status: awaiting_approval</p>
              <Spine status="awaiting_approval" />
            </div>
            <div>
              <p className={tx('cardMeta', 'mb-3 text-warm-grey-600')}>standalone stages</p>
              <div className="flex flex-col gap-3">
                <LifecycleStage label="Ingest" state="complete" />
                <LifecycleStage label="Investigate" state="active" />
                <LifecycleStage label="Verify" state="pending" />
              </div>
            </div>
          </div>
        </div>
        <div className="mt-6">
          <p className={tx('cardMeta', 'mb-3 text-warm-grey-600')}>horizontal · status: investigating</p>
          <Spine status="investigating" orientation="horizontal" />
        </div>
      </Section>

      <Section title="Approval · evidence" subtitle="Approval is advisory UI only — the real auto-vs-human gate is server-side. Evidence links never fabricate a destination.">
        <div className="grid gap-8 lg:grid-cols-2">
          <ElevationSurface level={2} highlight className="p-5">
            <ApprovalAction requiresApproval onApprove={() => {}} onReject={() => {}} onModify={() => {}} />
          </ElevationSurface>
          <div className="flex flex-col gap-3">
            <EvidenceLink href="https://github.com/acme/repo/pull/482" label="PR #482 · remediation" source="GitHub" />
            <EvidenceLink href="https://example.com/trace/abc" label="Distributed trace" source="Datadog" />
            <EvidenceLink href="/audit/inc_01H9" label="Audit chain entry" source="audit log" />
            <EvidenceLink href="9c4f2a1e8b" label="9c4f2a1e8b" source="commit" mono />
            <EvidenceLink href={null} label="Root-cause log bundle" />
          </div>
        </div>
      </Section>
    </main>
  );
}

