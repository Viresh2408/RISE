import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Canonical class-name combiner for the RISE dashboard.
 *
 * `clsx` resolves conditional/array/object class inputs; `twMerge` then
 * de-duplicates conflicting Tailwind utilities so the last-wins (e.g. a caller
 * passing `text-cream` overrides a primitive's default `text-warm-grey-600`).
 *
 * Both deps were already installed but unused — this consolidates the ad-hoc
 * template-string class joins scattered across components onto one helper.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
