import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The backend URL is read at runtime from NEXT_PUBLIC_API_URL so the same
  // build works against a local backend and against one in Docker.
  reactStrictMode: true,
};

export default nextConfig;
