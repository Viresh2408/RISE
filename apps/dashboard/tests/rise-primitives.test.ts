import { describe, it, expect } from 'vitest';
import {
  resolveConfidence,
  deriveLifecycle,
  RISE_LIFECYCLE,
  SEVERITY_META,
  INCIDENT_STATUS_META,
  RISK_TIER_META,
  AGENT_STATE_META,
  TONE_BADGE_CLASSES,
  TONE_DOT_CLASSES,
  TONE_TEXT_CLASSES,
} from '../components/rise/tokens';

/**
 * Phase 0 primitive logic tests. Vitest runs in a `node` environment (no DOM),
 * so these exercise the PURE mappings only — the honesty contract and the
 * lifecycle derivation, which are where the real risk of "more confident than
 * the evidence" lives.
 */
describe('resolveConfidence — honesty contract', () => {
  it('treats null / undefined / NaN as "Not computed" and never fabricates a value', () => {
    for (const v of [null, undefined, NaN]) {
      const r = resolveConfidence(v as number | null | undefined);
      expect(r.state).toBe('not-computed');
      expect(r.fraction).toBeNull();
      expect(r.percent).toBeNull();
      expect(r.display).toBe('—');
      expect(r.label).toBe('Not computed');
      expect(r.band).toBe('none');
    }
  });

  it('keeps a real 0 as 0% band low (the old `score || 0.85` bug case)', () => {
    const r = resolveConfidence(0);
    expect(r.state).toBe('computed');
    expect(r.percent).toBe(0);
    expect(r.display).toBe('0%');
    expect(r.band).toBe('low');
  });

  it('bands medium (>=0.5) and high (>=0.8)', () => {
    expect(resolveConfidence(0.49).band).toBe('low');
    expect(resolveConfidence(0.5).band).toBe('medium');
    expect(resolveConfidence(0.79).band).toBe('medium');
    expect(resolveConfidence(0.8).band).toBe('high');
    expect(resolveConfidence(0.88).percent).toBe(88);
    expect(resolveConfidence(1).percent).toBe(100);
  });

  it('honours scale=100 and clamps out-of-range input', () => {
    expect(resolveConfidence(72, 100).percent).toBe(72);
    expect(resolveConfidence(0, 100).percent).toBe(0);
    expect(resolveConfidence(1.5).percent).toBe(100);
    expect(resolveConfidence(-0.2).percent).toBe(0);
    expect(resolveConfidence(150, 100).percent).toBe(100);
  });
});

describe('deriveLifecycle — pipeline stage derivation', () => {
  const keysOf = (status: Parameters<typeof deriveLifecycle>[0]) =>
    RISE_LIFECYCLE.map((s) => deriveLifecycle(status)[s.key]);

  it('returns a state for every one of the 9 canonical stages, in order', () => {
    expect(RISE_LIFECYCLE).toHaveLength(9);
    expect(Object.keys(deriveLifecycle('open'))).toHaveLength(9);
  });

  it('open → first stage active, everything after it pending', () => {
    const states = keysOf('open');
    expect(states[0]).toBe('active');
    expect(states.slice(1).every((s) => s === 'pending')).toBe(true);
  });

  it('investigating → stages before index 2 complete, index 2 active, rest pending', () => {
    const states = keysOf('investigating');
    expect(states[0]).toBe('complete');
    expect(states[1]).toBe('complete');
    expect(states[2]).toBe('active');
    expect(states.slice(3).every((s) => s === 'pending')).toBe(true);
  });

  it('awaiting_approval → the human-gate stage (index 6) is active', () => {
    const states = keysOf('awaiting_approval');
    expect(states[6]).toBe('active');
    expect(states.slice(0, 6).every((s) => s === 'complete')).toBe(true);
    expect(states.slice(7).every((s) => s === 'pending')).toBe(true);
  });

  it('resolved and closed → all stages complete (no active/pending left)', () => {
    for (const terminal of ['resolved', 'closed'] as const) {
      const states = keysOf(terminal);
      expect(states.every((s) => s === 'complete')).toBe(true);
    }
  });
});

describe('semantic meta maps — completeness', () => {
  it('SEVERITY_META covers SEV1–SEV4', () => {
    expect(Object.keys(SEVERITY_META).sort()).toEqual(['SEV1', 'SEV2', 'SEV3', 'SEV4']);
  });

  it('INCIDENT_STATUS_META covers every incident status', () => {
    expect(Object.keys(INCIDENT_STATUS_META).sort()).toEqual(
      ['awaiting_approval', 'closed', 'investigating', 'open', 'resolved'],
    );
  });

  it('RISK_TIER_META covers every risk tier', () => {
    expect(Object.keys(RISK_TIER_META).sort()).toEqual(['critical', 'high', 'low', 'medium']);
  });

  it('AGENT_STATE_META covers every run state', () => {
    expect(Object.keys(AGENT_STATE_META).sort()).toEqual(
      ['failed', 'pending', 'running', 'skipped', 'success'],
    );
  });

  it('every tone has badge, dot, and text classes (no missing tone in any map)', () => {
    const tones = Object.keys(TONE_BADGE_CLASSES).sort();
    expect(tones).toEqual(['amber', 'green', 'neutral', 'red', 'slate', 'violet']);
    expect(Object.keys(TONE_DOT_CLASSES).sort()).toEqual(tones);
    expect(Object.keys(TONE_TEXT_CLASSES).sort()).toEqual(tones);
    // No fabricated empties — every tone actually maps to a non-empty class string.
    for (const t of tones) {
      expect(TONE_BADGE_CLASSES[t as keyof typeof TONE_BADGE_CLASSES].length).toBeGreaterThan(0);
      expect(TONE_DOT_CLASSES[t as keyof typeof TONE_DOT_CLASSES].length).toBeGreaterThan(0);
      expect(TONE_TEXT_CLASSES[t as keyof typeof TONE_TEXT_CLASSES].length).toBeGreaterThan(0);
    }
  });
});
