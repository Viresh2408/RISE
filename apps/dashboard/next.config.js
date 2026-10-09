/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Emit a self-contained server bundle (.next/standalone) for a minimal
  // production container image; see apps/dashboard/Dockerfile.
  output: 'standalone',
  // Pin the file-tracing root to the app for a flat standalone server bundle.
  outputFileTracingRoot: __dirname,
  transpilePackages: ['@supabase/supabase-js'],
  async rewrites() {
    return [
      {
        source: '/api/v1/:path*',
        destination: `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8888'}/api/v1/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
