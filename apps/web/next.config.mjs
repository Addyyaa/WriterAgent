/** @type {import('next').NextConfig} */
const backendBaseUrl = (process.env.BACKEND_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

const nextConfig = {
  reactStrictMode: true,
  typedRoutes: true,

  // 👇 关键：转发 /v2/* 到后端 FastAPI
  async rewrites() {
    return [
      {
        source: "/v2/:path*",
        destination: `${backendBaseUrl}/v2/:path*`
      }
    ];
  }
};

export default nextConfig;
