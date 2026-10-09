import React from 'react';
import { cn } from '../../lib/cn';
import type { ElevationLevel } from '../../lib/design-tokens';

/**
 * The dimensional (2.5D) building block. Renders a token-driven substrate at
 * one of five elevation levels, with optional depth-aware interaction, a top
 * inner-highlight lip, and a translucent "glass" treatment. All visuals come
 * from the CSS classes in `globals.css` (`.rise-surface`, `.rise-elev-*`,
 * `.rise-surface--interactive`, `.rise-surface--highlight`, `.glass-panel`) so
 * a single token edit re-themes every surface (including Day Mode).
 */
const ELEV_CLASS: Record<ElevationLevel, string> = {
  0: 'rise-elev-0',
  1: 'rise-elev-1',
  2: 'rise-elev-2',
  3: 'rise-elev-3',
  4: 'rise-elev-4',
};

export interface ElevationSurfaceProps extends React.HTMLAttributes<HTMLElement> {
  /** 0 (flush with the page) … 4 (floating). Ignored when `glass`. */
  level?: ElevationLevel;
  /** Lift toward the viewer on hover/focus (adds pointer + keyboard affordance). */
  interactive?: boolean;
  /** Draw the top inner-highlight edge (light catching the raised lip). */
  highlight?: boolean;
  /** Use the translucent blurred panel instead of an opaque substrate. */
  glass?: boolean;
  /** Element/component to render as. Defaults to a div. */
  as?: React.ElementType<React.HTMLAttributes<HTMLElement>>;
  className?: string;
  children?: React.ReactNode;
}

export function ElevationSurface({
  level = 1,
  interactive = false,
  highlight = false,
  glass = false,
  as: Tag = 'div',
  className,
  children,
  ...rest
}: ElevationSurfaceProps) {
  return (
    <Tag
      className={cn(
        glass ? 'glass-panel' : 'rise-surface',
        !glass && ELEV_CLASS[level],
        interactive && 'rise-surface--interactive',
        highlight && 'rise-surface--highlight',
        className,
      )}
      {...rest}
    >
      {children}
    </Tag>
  );
}
