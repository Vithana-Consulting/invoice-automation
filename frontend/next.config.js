/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    missingSuspenseWithCSRBailout: false,
  },
  async rewrites() {
    return [
      {
        // Server-side proxy: runs inside the Next.js container, so it must
        // reach the backend by its docker-network name, NOT localhost.
        // BACKEND_INTERNAL_URL is set in docker-compose; falls back to the
        // public URL for local (non-docker) `npm run dev`.
        source: '/api/:path*',
        destination: `${process.env.BACKEND_INTERNAL_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
