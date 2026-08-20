import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['tests/**/*.test.{ts,tsx}'],
    exclude: ['tests/**/*.spec.ts', 'node_modules', '.next'],
    environment: 'node',
  },
});
