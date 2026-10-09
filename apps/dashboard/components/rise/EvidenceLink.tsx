import React from 'react';
import { ExternalLink, Link2, Ban } from 'lucide-react';
import { cn } from '../../lib/cn';
import { tx } from '../../lib/typography';

/**
 * A link to a piece of evidence backing an incident (a log, trace, commit, PR,
 * dashboard, runbook, …).
 *
 * Honesty contract: a link is rendered only when a real `href` is supplied.
 * A missing/empty href renders a non-interactive "Unavailable" state — it never
 * fabricates a destination or presents dead evidence as clickable. Use `mono`
 * for technical identifiers (hashes, IDs, PR numbers, file paths).
 */
export interface EvidenceLinkProps {
  href?: string | null;
  label: string;
  /** Optional origin caption (e.g. "GitHub", "Datadog", "audit log"). */
  source?: string;
  /** Force external-link affordance; auto-detected for absolute http(s) URLs. */
  external?: boolean;
  /** Render the label in JetBrains Mono for technical data. */
  mono?: boolean;
  className?: string;
}

export function EvidenceLink({ href, label, source, external, mono = false, className }: EvidenceLinkProps) {
  const labelClass = cn(tx('cardMeta'), mono && 'font-mono');
  const hasHref = typeof href === 'string' && href.trim().length > 0;

  if (!hasHref) {
    return (
      <span
        className={cn('inline-flex items-center gap-1.5 text-warm-grey-600', labelClass, className)}
        title="No evidence link available"
      >
        <Ban className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span>{label}</span>
        <span className="text-warm-grey-700">— Unavailable</span>
      </span>
    );
  }

  const isExternal = external ?? /^https?:\/\//i.test(href);
  const Icon = isExternal ? ExternalLink : Link2;

  return (
    <a
      href={href}
      {...(isExternal ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
      className={cn(
        'group inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] text-violet-accent transition-colors duration-base hover:text-cream focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-accent focus-visible:ring-offset-2 focus-visible:ring-offset-near-black',
        labelClass,
        className,
      )}
    >
      <Icon className="h-3.5 w-3.5 shrink-0 opacity-70 group-hover:opacity-100" aria-hidden />
      <span className="underline decoration-violet-accent/30 underline-offset-2 group-hover:decoration-violet-accent">
        {label}
      </span>
      {source && <span className="text-warm-grey-600">· {source}</span>}
    </a>
  );
}
