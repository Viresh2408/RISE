'use client';

import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import { useRouter } from 'next/navigation';
import { Search, CornerDownLeft, ArrowRight } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { cn } from '../../lib/cn';
import { tx } from '../../lib/typography';
import { useBodyScrollLock, useMounted, useOnEscape } from './hooks';
import { NAV_LINKS } from '../navbar';

export interface PaletteCommand {
  id: string;
  label: string;
  /** Secondary line (e.g. the destination route). */
  hint?: string;
  /** Extra searchable text not shown in the label. */
  keywords?: string;
  icon?: LucideIcon;
  perform: () => void;
}

/**
 * Pure substring match over label + hint + keywords. Extracted so the ranking
 * is unit-testable in the node (non-DOM) Vitest environment.
 */
export function filterCommands(commands: PaletteCommand[], query: string): PaletteCommand[] {
  const q = query.trim().toLowerCase();
  if (!q) return commands;
  return commands.filter((c) =>
    [c.label, c.hint, c.keywords].some((f) => f?.toLowerCase().includes(q)),
  );
}

/** True when `query` is a plausible incident identifier (no spaces). */
export function isIncidentQuery(query: string): boolean {
  return /^[\w-]{1,64}$/.test(query.trim());
}

interface PaletteApi {
  open: () => void;
  close: () => void;
  toggle: () => void;
}

const PaletteContext = createContext<PaletteApi | null>(null);

/** Programmatic access to the command palette (e.g. a toolbar button). */
export function useCommandPalette(): PaletteApi {
  const ctx = useContext(PaletteContext);
  if (!ctx) throw new Error('useCommandPalette must be used within a <CommandPaletteProvider>.');
  return ctx;
}

/**
 * Global command palette host (Cmd/Ctrl+K). Mount once near the app root.
 * Navigation-only by design: it routes to existing pages and to an incident by
 * ID. It intentionally exposes no remediation/execution actions — every safety
 * gate stays server-side and must not be reachable from here.
 */
export function CommandPaletteProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const api = useMemo<PaletteApi>(
    () => ({
      open: () => setOpen(true),
      close: () => setOpen(false),
      toggle: () => setOpen((o) => !o),
    }),
    [],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        api.toggle();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [api]);

  return (
    <PaletteContext.Provider value={api}>
      {children}
      <CommandPalette open={open} onClose={api.close} />
    </PaletteContext.Provider>
  );
}
function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const mounted = useMounted();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);

  useBodyScrollLock(open);
  useOnEscape(onClose, open);

  const baseCommands = useMemo<PaletteCommand[]>(
    () =>
      NAV_LINKS.map((link) => ({
        id: `nav-${link.href}`,
        label: link.label,
        hint: link.href,
        keywords: 'navigate go to page',
        icon: link.icon ?? undefined,
        perform: () => router.push(link.href),
      })),
    [router],
  );

  const results = useMemo(() => {
    const matches = filterCommands(baseCommands, query);
    const trimmed = query.trim();
    if (trimmed && isIncidentQuery(trimmed)) {
      return [
        ...matches,
        {
          id: 'incident-lookup',
          label: `Go to incident ${trimmed}`,
          hint: `/incidents/${trimmed}`,
          icon: ArrowRight,
          perform: () => router.push(`/incidents/${encodeURIComponent(trimmed)}`),
        },
      ];
    }
    return matches;
  }, [baseCommands, query, router]);

  useEffect(() => {
    if (!open) return;
    setQuery('');
    setActiveIndex(0);
    const t = setTimeout(() => inputRef.current?.focus(), 0);
    return () => clearTimeout(t);
  }, [open]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  const run = (cmd?: PaletteCommand) => {
    if (!cmd) return;
    onClose();
    cmd.perform();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((i) => (results.length ? (i + 1) % results.length : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((i) => (results.length ? (i - 1 + results.length) % results.length : 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      run(results[activeIndex]);
    }
  };

  if (!mounted || !open) return null;
  /* __APPEND_PALETTE_3__ */
}
