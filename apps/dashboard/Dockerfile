# syntax=docker/dockerfile:1.7
# RISE dashboard (Next.js 15, App Router) image.  Build context MUST be the
# repo root (pnpm workspace):  docker build -f apps/dashboard/Dockerfile -t rise-dashboard .
# Uses Next standalone output (next.config.js: output:'standalone').

# --- Builder: install the pnpm workspace and build the dashboard ---
FROM node:22-alpine AS builder
RUN corepack enable
WORKDIR /app
# Copy the whole workspace (node_modules/.next are excluded via .dockerignore)
# so pnpm resolves the dashboard's workspace dependencies.
COPY . .
RUN pnpm install --frozen-lockfile
RUN pnpm --filter rise-dashboard build

# --- Runtime: minimal standalone server ---
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup -S nodejs && adduser -S nextjs -G nodejs
# Standalone bundle. With outputFileTracingRoot pinned to the app dir
# (next.config.js), Next emits a FLAT layout: server.js and its .next/ live at
# the standalone root, so we copy the bundle to /app and static into /app/.next.
COPY --from=builder --chown=nextjs:nodejs /app/apps/dashboard/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/apps/dashboard/.next/static ./.next/static
# NOTE: apps/dashboard/public/ does not exist yet; add a COPY for it here if
# static assets are introduced.
USER nextjs
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:3000/ || exit 1
CMD ["node", "server.js"]
